"""Generate synthetic German personal data with errors for record linkage.

Inspired by FEBRL's dsgen data generator.  Produces realistic German personal
records and creates duplicate records with various types of corruption:

  - Typographical errors (insertion, deletion, substitution, transposition)
  - Missing / empty values
  - Phonetic errors (German sound-alike substitutions)
  - OCR-like errors (visually similar characters)
  - Date component errors
  - Field swaps (two fields exchanged)

Output
------
  data/dataset_original.csv   – clean original records
  data/dataset_dirty.csv      – originals + corrupted duplicates (shuffled)
  data/true_links.csv         – ground-truth duplicate pairs

Usage
-----
    python generate_dataset.py --num-originals 5000 --max-dups 3 --output-dir data
"""

from __future__ import annotations

import argparse
import csv
import random
import string
from pathlib import Path

from faker import Faker

# ---------------------------------------------------------------------------
# Faker setup – German locale
# ---------------------------------------------------------------------------
fake = Faker("de_DE")
Faker.seed(42)
random.seed(42)

# ---------------------------------------------------------------------------
# Field names (FEBRL-compatible)
# ---------------------------------------------------------------------------
FIELDS = [
    "rec_id",
    "given_name",
    "surname",
    "street_number",
    "address_1",
    "suburb",
    "postcode",
    "state",
    "date_of_birth",
    "phone_number",
    "soc_sec_id",
]

# ---------------------------------------------------------------------------
# German QWERTZ keyboard neighbourhood (for typo simulation)
# ---------------------------------------------------------------------------
KEYBOARD_NEARBY: dict[str, str] = {
    "q": "wa", "w": "qeas", "e": "wrds", "r": "etdf", "t": "rzfg",
    "z": "tugh", "u": "zhji", "i": "ujko", "o": "iklp", "p": "olü",
    "a": "qwsy", "s": "wedxa", "d": "erfsc", "f": "rtgdv",
    "g": "tzfhb", "h": "zugjn", "j": "uhkm", "k": "ijl",
    "l": "okö", "y": "xsa", "x": "ysd", "c": "xdf", "v": "cfg",
    "b": "vgh", "n": "bhj", "m": "njk",
    "ä": "öl", "ö": "äklp", "ü": "po",
}

# ---------------------------------------------------------------------------
# German phonetic substitution pairs
# ---------------------------------------------------------------------------
PHONETIC_SUBS: list[tuple[str, str]] = [
    ("sch", "sh"),  ("sh", "sch"),
    ("ei", "ai"),   ("ai", "ei"),
    ("ie", "i"),    ("i", "ie"),
    ("tz", "z"),    ("z", "tz"),
    ("dt", "t"),    ("t", "dt"),
    ("ph", "f"),    ("f", "ph"),
    ("v", "f"),     ("f", "v"),
    ("ck", "k"),    ("k", "ck"),
    ("ss", "ß"),    ("ß", "ss"),
    ("ae", "ä"),    ("ä", "ae"),
    ("oe", "ö"),    ("ö", "oe"),
    ("ue", "ü"),    ("ü", "ue"),
    ("th", "t"),    ("t", "th"),
    ("mann", "man"), ("man", "mann"),
]

# ---------------------------------------------------------------------------
# OCR-like substitution pairs (visually similar characters)
# ---------------------------------------------------------------------------
OCR_SUBS: dict[str, str] = {
    "0": "O", "O": "0", "o": "0",
    "1": "l", "l": "1", "I": "l",
    "5": "S", "S": "5",
    "8": "B", "B": "8",
    "2": "Z", "Z": "2",
    "6": "G", "G": "6",
    "m": "rn", "rn": "m",
    "cl": "d", "d": "cl",
    "h": "b", "b": "h",
}

# ---------------------------------------------------------------------------
# German Bundesländer
# ---------------------------------------------------------------------------
BUNDESLAENDER = [
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen",
    "Hamburg", "Hessen", "Mecklenburg-Vorpommern", "Niedersachsen",
    "Nordrhein-Westfalen", "Rheinland-Pfalz", "Saarland", "Sachsen",
    "Sachsen-Anhalt", "Schleswig-Holstein", "Thüringen",
]


# ===================================================================
# Record generation
# ===================================================================

def _random_soc_sec_id() -> str:
    """Generate a fake German social-security-style number (12 digits)."""
    return "".join(random.choices(string.digits, k=12))


def generate_original_record(rec_id: int) -> dict[str, str]:
    """Return a single clean personal record."""
    dob = fake.date_of_birth(minimum_age=18, maximum_age=90)
    return {
        "rec_id": f"rec-{rec_id:06d}-org",
        "given_name": fake.first_name(),
        "surname": fake.last_name(),
        "street_number": str(random.randint(1, 200)),
        "address_1": fake.street_name(),
        "suburb": fake.city(),
        "postcode": fake.postcode(),
        "state": random.choice(BUNDESLAENDER),
        "date_of_birth": dob.strftime("%Y%m%d"),
        "phone_number": fake.phone_number(),
        "soc_sec_id": _random_soc_sec_id(),
    }


# ===================================================================
# Corruption functions
# ===================================================================

def _typo(value: str) -> str:
    """Introduce a single keyboard-proximity typo."""
    if len(value) < 2:
        return value
    pos = random.randint(0, len(value) - 1)
    char = value[pos].lower()

    # Choose corruption sub-type: substitute / insert / delete / transpose
    action = random.choices(
        ["substitute", "insert", "delete", "transpose"],
        weights=[0.4, 0.2, 0.2, 0.2],
        k=1,
    )[0]

    if action == "substitute" and char in KEYBOARD_NEARBY:
        replacement = random.choice(KEYBOARD_NEARBY[char])
        return value[:pos] + replacement + value[pos + 1:]
    elif action == "insert":
        insert_char = random.choice(string.ascii_lowercase)
        return value[:pos] + insert_char + value[pos:]
    elif action == "delete" and len(value) > 2:
        return value[:pos] + value[pos + 1:]
    elif action == "transpose" and pos < len(value) - 1:
        lst = list(value)
        lst[pos], lst[pos + 1] = lst[pos + 1], lst[pos]
        return "".join(lst)
    return value  # fallback: unchanged


def _phonetic(value: str) -> str:
    """Apply a German phonetic substitution."""
    lower = value.lower()
    applicable = [(a, b) for a, b in PHONETIC_SUBS if a in lower]
    if not applicable:
        return value
    old, new = random.choice(applicable)
    idx = lower.find(old)
    if idx == -1:
        return value
    # Preserve rough casing of first character
    replaced = value[:idx] + new + value[idx + len(old):]
    return replaced


def _ocr(value: str) -> str:
    """Apply an OCR-like character substitution."""
    applicable = [(i, c) for i, c in enumerate(value) if c in OCR_SUBS]
    if not applicable:
        return value
    pos, char = random.choice(applicable)
    return value[:pos] + OCR_SUBS[char] + value[pos + 1:]


def _missing(_value: str) -> str:
    """Return empty string (missing value)."""
    return ""


def _date_error(value: str) -> str:
    """Corrupt a YYYYMMDD date string."""
    if len(value) != 8 or not value.isdigit():
        return _typo(value)  # not a date – fall back to typo
    parts = list(value)
    action = random.choice(["swap_digits", "wrong_month", "wrong_day", "off_by_one"])
    if action == "swap_digits":
        i = random.randint(0, 6)
        parts[i], parts[i + 1] = parts[i + 1], parts[i]
    elif action == "wrong_month":
        parts[4:6] = list(f"{random.randint(1, 12):02d}")
    elif action == "wrong_day":
        parts[6:8] = list(f"{random.randint(1, 28):02d}")
    elif action == "off_by_one":
        pos = random.randint(0, 7)
        digit = int(parts[pos])
        parts[pos] = str((digit + random.choice([-1, 1])) % 10)
    return "".join(parts)


# Corruption dispatch keyed by name → (function, eligible fields)
CORRUPTIBLE_FIELDS = [
    "given_name", "surname", "street_number", "address_1",
    "suburb", "postcode", "state", "phone_number", "soc_sec_id",
]

CORRUPTION_DISPATCH: dict[str, tuple] = {
    "typo":       (_typo,       CORRUPTIBLE_FIELDS),
    "phonetic":   (_phonetic,   ["given_name", "surname", "address_1", "suburb"]),
    "ocr":        (_ocr,        CORRUPTIBLE_FIELDS),
    "missing":    (_missing,    CORRUPTIBLE_FIELDS),
    "date_error": (_date_error, ["date_of_birth"]),
}

CORRUPTION_WEIGHTS = {
    "typo": 0.30,
    "phonetic": 0.15,
    "ocr": 0.10,
    "missing": 0.20,
    "date_error": 0.10,
    "field_swap": 0.15,
}


def _choose_corruption() -> str:
    names = list(CORRUPTION_WEIGHTS.keys())
    weights = [CORRUPTION_WEIGHTS[n] for n in names]
    return random.choices(names, weights=weights, k=1)[0]


def corrupt_record(
    record: dict[str, str],
    num_corruptions: int,
) -> tuple[dict[str, str], list[str]]:
    """Apply *num_corruptions* random corruptions to a copy of *record*.

    Returns the corrupted record and a list of descriptions of what changed.
    """
    rec = dict(record)
    changes: list[str] = []

    for _ in range(num_corruptions):
        ctype = _choose_corruption()

        if ctype == "field_swap":
            # Swap two randomly chosen corruptible fields
            f1, f2 = random.sample(CORRUPTIBLE_FIELDS, 2)
            rec[f1], rec[f2] = rec[f2], rec[f1]
            changes.append(f"field_swap({f1}<->{f2})")
            continue

        func, eligible = CORRUPTION_DISPATCH[ctype]
        field = random.choice(eligible)
        old_val = rec[field]
        new_val = func(old_val)
        if new_val != old_val:
            rec[field] = new_val
            changes.append(f"{ctype}({field})")

    return rec, changes


# ===================================================================
# Dataset assembly
# ===================================================================

def generate_dataset(
    num_originals: int = 5000,
    max_dups: int = 3,
    dup_probability: float = 0.40,
    max_corruptions: int = 3,
) -> tuple[list[dict], list[dict], list[tuple[str, str]]]:
    """Generate originals, duplicates with errors, and ground-truth links.

    Returns
    -------
    originals : list of dicts
    all_records : list of dicts  (originals + duplicates, shuffled)
    true_links : list of (orig_id, dup_id) tuples
    """
    originals: list[dict[str, str]] = []
    duplicates: list[dict[str, str]] = []
    true_links: list[tuple[str, str]] = []

    for i in range(num_originals):
        org = generate_original_record(i)
        originals.append(org)

        if random.random() < dup_probability:
            n_dups = random.randint(1, max_dups)
            for d in range(n_dups):
                n_corr = random.randint(1, max_corruptions)
                dup, _changes = corrupt_record(org, n_corr)
                dup_id = f"rec-{i:06d}-dup-{d}"
                dup["rec_id"] = dup_id
                duplicates.append(dup)
                true_links.append((org["rec_id"], dup_id))

    all_records = originals + duplicates
    random.shuffle(all_records)
    return originals, all_records, true_links


# ===================================================================
# I/O helpers
# ===================================================================

def write_csv(path: Path, records: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


def write_links(path: Path, links: list[tuple[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id_original", "id_duplicate"])
        for a, b in links:
            writer.writerow([a, b])


# ===================================================================
# CLI
# ===================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate a synthetic German personal-data dataset with "
                    "duplicates and errors for record-linkage benchmarking.",
    )
    p.add_argument(
        "--num-originals", type=int, default=5000,
        help="Number of unique original records (default: 5000)",
    )
    p.add_argument(
        "--max-dups", type=int, default=3,
        help="Maximum duplicates per original record (default: 3)",
    )
    p.add_argument(
        "--dup-probability", type=float, default=0.40,
        help="Probability that a record gets at least one duplicate (default: 0.40)",
    )
    p.add_argument(
        "--max-corruptions", type=int, default=3,
        help="Maximum number of corruptions per duplicate (default: 3)",
    )
    p.add_argument(
        "--output-dir", type=str, default="data",
        help="Output directory (default: data/)",
    )
    p.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Re-seed with user-provided seed
    random.seed(args.seed)
    Faker.seed(args.seed)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Generating {args.num_originals} original records …")
    originals, all_records, true_links = generate_dataset(
        num_originals=args.num_originals,
        max_dups=args.max_dups,
        dup_probability=args.dup_probability,
        max_corruptions=args.max_corruptions,
    )

    n_dups = len(all_records) - len(originals)
    print(f"  → {len(originals)} originals, {n_dups} duplicates "
          f"({len(all_records)} total)")
    print(f"  → {len(true_links)} ground-truth link pairs")

    path_orig = out / "dataset_original.csv"
    path_dirty = out / "dataset_dirty.csv"
    path_links = out / "true_links.csv"

    write_csv(path_orig, originals)
    write_csv(path_dirty, all_records)
    write_links(path_links, true_links)

    print(f"\nFiles written:")
    print(f"  {path_orig}  ({len(originals)} records)")
    print(f"  {path_dirty}  ({len(all_records)} records)")
    print(f"  {path_links}  ({len(true_links)} link pairs)")


if __name__ == "__main__":
    main()
