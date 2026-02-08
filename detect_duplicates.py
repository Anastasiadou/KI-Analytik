"""Detect potential duplicates in the FEBRL-generated dataset.

Adds two new boolean columns to the dataset:

  1. ``dublette_name_vertauscht``
     True when another record exists with given_name/surname swapped
     AND at least one more shared field (soc_sec_id, date_of_birth,
     phone_number, or postcode) to avoid false positives.

  2. ``dublette_phonetisch``
     True when another record exists whose name *sounds* the same
     (Cologne phonetics / Kölner Phonetik) but is spelled differently.

Usage:
    python detect_duplicates.py [--input data/febrl_generated.csv]
                                [--output data/febrl_generated_checked.csv]
"""

from __future__ import annotations

import argparse
import csv
import time
from collections import defaultdict
from pathlib import Path

import jellyfish
import pandas as pd

# ---------------------------------------------------------------------------
# Cologne Phonetics (Kölner Phonetik) — optimised for German names
# ---------------------------------------------------------------------------
# jellyfish ships with cologne_phonetics since v1.0; fall back to a
# simplified implementation if unavailable.

try:
    from jellyfish import cologne_phonetics as _cologne
except ImportError:
    _cologne = None

# Mapping table for Cologne phonetics
_COLOGNE_MAP = {
    "a": "0", "e": "0", "i": "0", "o": "0", "u": "0",
    "ä": "0", "ö": "0", "ü": "0",
    "h": "",
    "b": "1", "p": "1",
    "d": "2", "t": "2",
    "f": "3", "v": "3", "w": "3",
    "g": "4", "k": "4", "q": "4",
    "l": "5",
    "m": "6", "n": "6",
    "r": "7",
    "s": "8", "z": "8", "ß": "8",
    "c": "4", "j": "0", "x": "48", "y": "0",
}


def cologne_phonetics(s: str) -> str:
    """Return the Cologne phonetic code for a German string."""
    if _cologne is not None:
        return _cologne(s)
    # Simple fallback
    s = s.lower().strip()
    code = []
    for ch in s:
        mapped = _COLOGNE_MAP.get(ch, "")
        if mapped and (not code or code[-1] != mapped):
            code.append(mapped)
    # Remove leading zeros (vowels) except if the code is just "0"
    result = "".join(code).lstrip("0") or "0"
    return result


def phonetic_key(given_name: str, surname: str) -> str:
    """Build a combined phonetic key for a full name."""
    gn = str(given_name).strip() if pd.notna(given_name) else ""
    sn = str(surname).strip() if pd.notna(surname) else ""
    if not gn and not sn:
        return ""
    return cologne_phonetics(gn) + "|" + cologne_phonetics(sn)


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

def detect_name_swap(df: pd.DataFrame) -> pd.Series:
    """Detect records where given_name and surname are swapped compared to
    another record, with at least one additional matching field as
    confirmation.
    """
    confirm_fields = ["soc_sec_id", "date_of_birth", "phone_number", "postcode"]

    # Build lookup: (surname, given_name) → list of row indices
    # i.e. the REVERSED name pair
    swap_index: dict[tuple, list[int]] = defaultdict(list)
    for idx, row in df.iterrows():
        gn = str(row["given_name"]).strip().lower() if pd.notna(row["given_name"]) else ""
        sn = str(row["surname"]).strip().lower() if pd.notna(row["surname"]) else ""
        if gn and sn and gn != sn:
            swap_index[(gn, sn)].append(idx)

    flags = pd.Series(False, index=df.index)

    for idx, row in df.iterrows():
        gn = str(row["given_name"]).strip().lower() if pd.notna(row["given_name"]) else ""
        sn = str(row["surname"]).strip().lower() if pd.notna(row["surname"]) else ""
        if not gn or not sn or gn == sn:
            continue

        # Look for records with the SWAPPED name pair
        candidates = swap_index.get((sn, gn), [])
        for cand_idx in candidates:
            if cand_idx == idx:
                continue
            cand = df.loc[cand_idx]
            # Require at least one confirming field
            for cf in confirm_fields:
                val_a = str(row[cf]).strip() if pd.notna(row[cf]) else ""
                val_b = str(cand[cf]).strip() if pd.notna(cand[cf]) else ""
                if val_a and val_b and val_a == val_b:
                    flags[idx] = True
                    flags[cand_idx] = True
                    break
            if flags[idx]:
                break

    return flags


def detect_phonetic_duplicates(df: pd.DataFrame) -> pd.Series:
    """Detect records that sound the same (Cologne phonetics) but are
    spelled differently.
    """
    # Build phonetic key → list of (idx, original_name) tuples
    phon_index: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for idx, row in df.iterrows():
        gn = str(row["given_name"]).strip().lower() if pd.notna(row["given_name"]) else ""
        sn = str(row["surname"]).strip().lower() if pd.notna(row["surname"]) else ""
        pk = phonetic_key(row["given_name"], row["surname"])
        if pk:
            phon_index[pk].append((idx, gn, sn))

    flags = pd.Series(False, index=df.index)

    for pk, members in phon_index.items():
        if len(members) < 2:
            continue
        # Check if any pair has different spelling
        for i in range(len(members)):
            idx_a, gn_a, sn_a = members[i]
            for j in range(i + 1, len(members)):
                idx_b, gn_b, sn_b = members[j]
                # Only flag if spelling actually differs
                if gn_a != gn_b or sn_a != sn_b:
                    flags[idx_a] = True
                    flags[idx_b] = True

    return flags


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect potential duplicates in a FEBRL-generated dataset.",
    )
    parser.add_argument(
        "--input", default="data/febrl_generated.csv",
        help="Input CSV file (default: data/febrl_generated.csv)",
    )
    parser.add_argument(
        "--output", default="data/febrl_generated_checked.csv",
        help="Output CSV file (default: data/febrl_generated_checked.csv)",
    )
    args = parser.parse_args()

    print(f"Lade {args.input} …")
    df = pd.read_csv(args.input, skipinitialspace=True)
    print(f"  {len(df)} Datensätze, {len(df.columns)} Spalten")

    # --- Detection 1: Name swap ---
    print("\nPrüfe Vor-/Nachname vertauscht …")
    t0 = time.time()
    df["dublette_name_vertauscht"] = detect_name_swap(df)
    n_swap = df["dublette_name_vertauscht"].sum()
    print(f"  → {n_swap} Datensätze markiert ({time.time() - t0:.1f}s)")

    # --- Detection 2: Phonetic similarity ---
    print("\nPrüfe phonetische Ähnlichkeit …")
    t0 = time.time()
    df["dublette_phonetisch"] = detect_phonetic_duplicates(df)
    n_phon = df["dublette_phonetisch"].sum()
    print(f"  → {n_phon} Datensätze markiert ({time.time() - t0:.1f}s)")

    # --- Summary ---
    both = (df["dublette_name_vertauscht"] & df["dublette_phonetisch"]).sum()
    either = (df["dublette_name_vertauscht"] | df["dublette_phonetisch"]).sum()
    print(f"\nZusammenfassung:")
    print(f"  Name vertauscht:        {n_swap}")
    print(f"  Phonetisch ähnlich:     {n_phon}")
    print(f"  Beides zutreffend:      {both}")
    print(f"  Mindestens eines:       {either}")

    # --- Save ---
    df.to_csv(args.output, index=False)
    print(f"\nGespeichert: {args.output}")

    # Also export to Excel
    xlsx_path = args.output.replace(".csv", ".xlsx")
    df.to_excel(xlsx_path, index=False, sheet_name="Dataset")
    print(f"Gespeichert: {xlsx_path}")


if __name__ == "__main__":
    main()
