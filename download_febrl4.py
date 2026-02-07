"""Download the FEBRL4 dataset and save it to the data/ directory."""

import os
from pathlib import Path

import recordlinkage
from recordlinkage.datasets import load_febrl4


def main():
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    print("Downloading FEBRL4 dataset...")
    dfA, dfB = load_febrl4()

    path_a = data_dir / "febrl4a.csv"
    path_b = data_dir / "febrl4b.csv"

    dfA.to_csv(path_a)
    dfB.to_csv(path_b)

    print(f"Dataset A: {len(dfA)} records -> {path_a}")
    print(f"Dataset B: {len(dfB)} records -> {path_b}")
    print("Done.")


if __name__ == "__main__":
    main()
