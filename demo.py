"""
Anonymization demo.

Runs all data files in demo_data/ by default, or a specific one by name.
Supports both .py sample files and .csv data files.

CSV files can have an optional sidecar .json config (same stem) that controls
which columns are anonymized and which entity types to detect per column —
enabling selective anonymization without modifying the CSV itself.

Usage:
    uv run python demo.py                          # run all files
    uv run python demo.py financial                # run demo_data/financial.py
    uv run python demo.py financial_transactions   # run demo_data/financial_transactions.csv
"""

import csv
import importlib
import json
import sys
from pathlib import Path

from src.privacy_wrapper.anonymizer import Anonymizer, AnonymizationResult

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

    # Optional sidecar config — same filename, .json extension.
    # Controls which fields are anonymized and which entity types to use per
    # field, enabling selective anonymization without touching the CSV itself.
    #
    # Schema:
    #   {
    #     "title": "My Dataset",
    #     "fields": {
    #       "name":           { "entities": ["PERSON"] },
    #       "email":          { "entities": ["EMAIL_ADDRESS"] },
    #       "amount":         { "skip": true },
    #       "description":    { "skip": true }
    #     }
    #   }
    #
    # Fields absent from "fields" → anonymized with the full default entity list.
    # Fields with "skip": true    → passed through unchanged.
    # Fields with "entities": [...] → only those entity types detected.
    sidecar_path = path.with_suffix(".json")
    sidecar: dict = json.loads(sidecar_path.read_text()) if sidecar_path.exists() else {}
    field_config: dict[str, dict] = sidecar.get("fields", {})
    title = sidecar.get("title") or stem.replace("_", " ").title()

    _print_header(f"{title}  [CSV]")
    if field_config:
        print(f"  Config: {sidecar_path.name}\n")

    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []

        for row in reader:
            # Anonymize each cell independently to preserve CSV structure.
            # Per-field results are kept separate — merging would cause
            # placeholder collisions when two cells produce the same name
            # (e.g. account_number and routing_number both → <PHONE_NUMBER_0>).
            cell_results: dict[str, AnonymizationResult] = {}
            for col in headers:
                cfg = field_config.get(col, {})
                if cfg.get("skip"):
                    cell_results[col] = AnonymizationResult(anonymized_text=row[col])
                else:
                    cell_results[col] = anon.anonymize(
                        row[col],
                        entities=cfg.get("entities"),          # None → use all defaults
                        score_threshold=cfg.get("score_threshold"),  # None → use instance default
                    )

            anon_row     = {col: cell_results[col].anonymized_text for col in headers}
            all_mappings = {col: cell_results[col].mapping          for col in headers}
            flat_mapping = {k: v for m in all_mappings.values() for k, v in m.items()}

            print(f"Original row:")
            _print_row(row, headers)

            print(f"\nAnonymized row:")
            _print_row(anon_row, headers)

            if flat_mapping:
                print(f"\nMapping:")
                for col in headers:
                    if all_mappings[col]:
                        print(f"  {col:<18} {all_mappings[col]}")

            # Restore each cell using only its own mapping
            for col in headers:
                restored = anon.deanonymize(anon_row[col], cell_results[col].mapping)
                assert restored == row[col], (
                    f"Roundtrip failed for field '{col}': "
                    f"{row[col]!r} → {restored!r}"
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
