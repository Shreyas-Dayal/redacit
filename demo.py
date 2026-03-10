"""
Anonymization demo.

Runs all data files in demo_data/ by default, or a specific one by name.
Supports both .py sample files and .csv data files.

Usage:
    uv run python demo.py                          # run all files
    uv run python demo.py financial                # run demo_data/financial.py
    uv run python demo.py financial_transactions   # run demo_data/financial_transactions.csv
"""

import csv
import importlib
import sys
from pathlib import Path

from src.privacy_wrapper.anonymizer import Anonymizer

DEMO_DATA_DIR = Path(__file__).parent / "demo_data"
WIDTH = 72
anon = Anonymizer()


# --- runners -----------------------------------------------------------------

def run_py(stem: str) -> None:
    mod = importlib.import_module(f"demo_data.{stem}")
    title = getattr(mod, "TITLE", stem)
    samples: list[str] = mod.SAMPLES

    _print_header(title)
    for text in samples:
        result = anon.anonymize(text)
        restored = anon.deanonymize(result.anonymized_text, result.mapping)

        print(f"\nOriginal:\n{text}")
        print(f"\nAnonymized:\n{result.anonymized_text}")
        print(f"\nMapping: {result.mapping}")
        print(f"\nRestored:\n{restored}")

        assert restored == text, f"Roundtrip failed:\n{text}"
        print("-" * WIDTH)
    print()


def run_csv(stem: str) -> None:
    path = DEMO_DATA_DIR / f"{stem}.csv"
    title = stem.replace("_", " ").title()

    _print_header(f"{title}  [CSV]")

    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []

        for row in reader:
            # Anonymize each cell independently so the CSV structure
            # (column names, delimiters) is preserved.
            # Keep per-field results separate — merging mappings would cause
            # collisions when two cells produce the same placeholder name
            # (e.g. both an account number and a routing number become
            # <PHONE_NUMBER_0> when each cell is processed in isolation).
            cell_results = {field: anon.anonymize(row[field]) for field in headers}

            anon_row  = {field: cell_results[field].anonymized_text for field in headers}
            all_mappings = {field: cell_results[field].mapping for field in headers}
            flat_mapping = {k: v for m in all_mappings.values() for k, v in m.items()}

            print(f"\nOriginal row:")
            _print_row(row, headers)

            print(f"\nAnonymized row:")
            _print_row(anon_row, headers)

            if flat_mapping:
                print(f"\nMapping:")
                for field in headers:
                    if all_mappings[field]:
                        print(f"  {field:<18} {all_mappings[field]}")

            # Restore each cell using only its own mapping
            for field in headers:
                restored = anon.deanonymize(anon_row[field], cell_results[field].mapping)
                assert restored == row[field], (
                    f"Roundtrip failed for field '{field}': "
                    f"{row[field]!r} → {restored!r}"
                )

            print("-" * WIDTH)
    print()


# --- helpers -----------------------------------------------------------------

def _print_header(title: str) -> None:
    print("=" * WIDTH)
    print(f"  {title}")
    print("=" * WIDTH)


def _print_row(row: dict, headers: list[str]) -> None:
    for h in headers:
        print(f"  {h:<18} {row[h]}")


def _all_stems() -> list[str]:
    """Return all demo file stems (.py and .csv) sorted alphabetically."""
    py_stems  = [p.stem for p in DEMO_DATA_DIR.glob("*.py")  if p.stem != "__init__"]
    csv_stems = [p.stem for p in DEMO_DATA_DIR.glob("*.csv")]
    return sorted(set(py_stems + csv_stems))


def _run(stem: str) -> None:
    if (DEMO_DATA_DIR / f"{stem}.csv").exists():
        run_csv(stem)
    else:
        run_py(stem)


# --- entrypoint --------------------------------------------------------------

def main() -> None:
    requested = sys.argv[1] if len(sys.argv) > 1 else None

    if requested:
        py_exists  = (DEMO_DATA_DIR / f"{requested}.py").exists()
        csv_exists = (DEMO_DATA_DIR / f"{requested}.csv").exists()
        if not py_exists and not csv_exists:
            print(f"Unknown demo file '{requested}'. Available: {_all_stems()}")
            sys.exit(1)
        _run(requested)
    else:
        for stem in _all_stems():
            _run(stem)


if __name__ == "__main__":
    main()
