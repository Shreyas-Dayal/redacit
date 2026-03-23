"""
Anonymization demo.

Runs all data files in demo_data/ by default, or a specific one by name.
Supports .py, .csv, and .json data files.

Sidecar configs
---------------
CSV  files: optional {stem}.json        — per-column entity/skip rules
JSON files: optional {stem}.config.json — per dot-path entity/skip rules

A .json file whose stem matches an existing .csv is treated as that CSV's
sidecar config, not as a standalone JSON dataset.

Sidecar schema (same for CSV and JSON):
  {
    "title": "...",
    "fields": {
      "field_or.dot.path": { "entities": ["PERSON", "EMAIL_ADDRESS"] },
      "another_field":      { "skip": true },
      "typed_field":        { "entities": ["US_BANK_ACCOUNT"], "score_threshold": 0.0 }
    }
  }

  - "entities": [...]       only those PII types detected for this field
  - "skip": true            field passed through unchanged
  - "score_threshold": N    per-field detection threshold (useful for isolated
                            cell values that have no surrounding context words)
  - (no entry)              full default entity list at default threshold

Usage:
    uv run python demo.py                         # run all files
    uv run python demo.py financial               # run demo_data/financial.py
    uv run python demo.py financial_records       # run demo_data/financial_records.json
    uv run python demo.py financial_transactions  # run demo_data/financial_transactions.csv
"""

import importlib
import json
import sys
from pathlib import Path

from redacit.anonymizer import Anonymizer
from redacit.formats import CsvAnonymizer, JsonAnonymizer

DEMO_DATA_DIR = Path(__file__).parent / "demo_data"
WIDTH = 72
anon = Anonymizer()
csv_anon  = CsvAnonymizer(anonymizer=anon)
json_anon = JsonAnonymizer(anonymizer=anon)


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

def run_py(stem: str) -> None:
    mod = importlib.import_module(f"demo_data.{stem}")
    title = getattr(mod, "TITLE", stem)
    samples: list[str] = mod.SAMPLES

    _print_header(title)
    for text in samples:
        result   = anon.anonymize(text)
        restored = anon.deanonymize(result.anonymized_text, result.mapping)

        print(f"\nOriginal:\n{text}")
        print(f"\nAnonymized:\n{result.anonymized_text}")
        print(f"\nMapping: {result.mapping}")
        print(f"\nRestored:\n{restored}")

        assert restored == text, f"Roundtrip failed:\n{text}"
        print("-" * WIDTH)
    print()


def run_csv(stem: str) -> None:
    path         = DEMO_DATA_DIR / f"{stem}.csv"
    sidecar_path = path.with_suffix(".json")
    sidecar, field_config = CsvAnonymizer.load_sidecar(sidecar_path)
    title = sidecar.get("title") or stem.replace("_", " ").title()

    _print_header(f"{title}  [CSV]")
    if field_config:
        print(f"  Config: {sidecar_path.name}\n")

    for row_result in csv_anon.anonymize_file(path, field_config):
        headers = list(row_result.original.keys())

        print("Original row:")
        _print_row(row_result.original, headers)
        print("\nAnonymized row:")
        _print_row(row_result.anonymized, headers)

        if row_result.flat_mapping:
            print("\nMapping:")
            for col in headers:
                if row_result.mappings[col]:
                    print(f"  {col:<28} {row_result.mappings[col]}")

        for col in headers:
            restored = anon.deanonymize(
                row_result.anonymized[col], row_result.mappings[col]
            )
            assert restored == row_result.original[col], (
                f"Roundtrip failed for field '{col}': "
                f"{row_result.original[col]!r} → {restored!r}"
            )

        print("-" * WIDTH)
    print()


def run_json(stem: str) -> None:
    path        = DEMO_DATA_DIR / f"{stem}.json"
    config_path = DEMO_DATA_DIR / f"{stem}.config.json"
    sidecar, _  = JsonAnonymizer.load_sidecar(config_path)
    title       = sidecar.get("title") or stem.replace("_", " ").title()

    # Array of plain strings → treat each as a free-text sample
    records = json.loads(path.read_text(encoding="utf-8"))
    if records and isinstance(records[0], str):
        _print_header(f"{title}  [JSON]")
        for text in records:
            result   = anon.anonymize(text)
            restored = anon.deanonymize(result.anonymized_text, result.mapping)
            print(f"\nOriginal:\n{text}")
            print(f"\nAnonymized:\n{result.anonymized_text}")
            print(f"\nMapping: {result.mapping}")
            print(f"\nRestored:\n{restored}")
            assert restored == text, f"Roundtrip failed:\n{text}"
            print("-" * WIDTH)
        print()
        return

    # Array of objects → per-field anonymization via JsonAnonymizer
    _print_header(f"{title}  [JSON]")
    if config_path.exists():
        print(f"  Config: {config_path.name}\n")

    for rec_result in json_anon.anonymize_file(path, config_path):
        print("Original:")
        print(json.dumps(rec_result.original,   indent=2))
        print("\nAnonymized:")
        print(json.dumps(rec_result.anonymized, indent=2))

        if rec_result.flat_mapping:
            print("\nMapping:")
            from redacit.formats._helpers import flatten
            flat_orig = flatten(rec_result.original)
            for path_ in flat_orig:
                matching = {
                    k: v for k, v in rec_result.flat_mapping.items()
                    if v in str(flat_orig.get(path_, ""))
                }
                if matching:
                    print(f"  {path_:<36} {matching}")

        # Roundtrip check: restore each string leaf and compare
        from redacit.formats._helpers import flatten as _flatten
        flat_orig = _flatten(rec_result.original)
        flat_anon = _flatten(rec_result.anonymized)
        for path_ in flat_orig:
            if isinstance(flat_orig[path_], str):
                restored = anon.deanonymize(flat_anon[path_], rec_result.flat_mapping)
                assert restored == flat_orig[path_], (
                    f"Roundtrip failed for '{path_}': "
                    f"{flat_orig[path_]!r} → {restored!r}"
                )

        print("-" * WIDTH)
    print()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_header(title: str) -> None:
    print("=" * WIDTH)
    print(f"  {title}")
    print("=" * WIDTH)


def _print_row(row: dict, headers: list[str]) -> None:
    for h in headers:
        print(f"  {h:<28} {row[h]}")


def _all_stems() -> list[str]:
    """
    Return all runnable demo file stems, sorted alphabetically.
    .json files that share a stem with a .csv are sidecar configs — excluded.
    .config.json files are JSON data sidecars — also excluded.
    """
    csv_stems  = {p.stem for p in DEMO_DATA_DIR.glob("*.csv")}
    py_stems   = [p.stem for p in DEMO_DATA_DIR.glob("*.py") if p.stem != "__init__"]
    json_stems = [
        p.stem for p in DEMO_DATA_DIR.glob("*.json")
        if p.stem not in csv_stems
        and not p.name.endswith(".config.json")
    ]
    return sorted(set(py_stems + list(csv_stems) + json_stems))


def _run(stem: str) -> None:
    if   (DEMO_DATA_DIR / f"{stem}.csv").exists():  run_csv(stem)
    elif (DEMO_DATA_DIR / f"{stem}.json").exists(): run_json(stem)
    else:                                            run_py(stem)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    requested = sys.argv[1] if len(sys.argv) > 1 else None

    if requested:
        exists = any(
            (DEMO_DATA_DIR / f"{requested}{ext}").exists()
            for ext in (".py", ".csv", ".json")
        )
        if not exists:
            print(f"Unknown demo file '{requested}'. Available: {_all_stems()}")
            sys.exit(1)
        _run(requested)
    else:
        for stem in _all_stems():
            _run(stem)


if __name__ == "__main__":
    main()
