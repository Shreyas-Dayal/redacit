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
    uv run python demo.py                      # run all files
    uv run python demo.py financial            # run demo_data/financial.py
    uv run python demo.py financial_records    # run demo_data/financial_records.json
    uv run python demo.py financial_transactions  # run demo_data/financial_transactions.csv
"""

import csv
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from src.privacy_wrapper.anonymizer import Anonymizer, AnonymizationResult

DEMO_DATA_DIR = Path(__file__).parent / "demo_data"
WIDTH = 72
anon = Anonymizer()


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

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
    sidecar_path = path.with_suffix(".json")
    sidecar, field_config = _load_sidecar(sidecar_path)
    title = sidecar.get("title") or stem.replace("_", " ").title()

    _print_header(f"{title}  [CSV]")
    if field_config:
        print(f"  Config: {sidecar_path.name}\n")

    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []

        for row in reader:
            cell_results = _anonymize_flat(row, headers, field_config)

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
                        print(f"  {col:<28} {all_mappings[col]}")

            for col in headers:
                restored = anon.deanonymize(anon_row[col], cell_results[col].mapping)
                assert restored == row[col], (
                    f"Roundtrip failed for field '{col}': "
                    f"{row[col]!r} → {restored!r}"
                )

            print("-" * WIDTH)
    print()


def run_json(stem: str) -> None:
    path = DEMO_DATA_DIR / f"{stem}.json"
    config_path = DEMO_DATA_DIR / f"{stem}.config.json"
    sidecar, field_config = _load_sidecar(config_path)
    title = sidecar.get("title") or stem.replace("_", " ").title()

    records = json.loads(path.read_text())

    # Array of plain strings → treat each as a text sample (same as .py)
    if records and isinstance(records[0], str):
        _print_header(f"{title}  [JSON]")
        for text in records:
            result = anon.anonymize(text)
            restored = anon.deanonymize(result.anonymized_text, result.mapping)
            print(f"\nOriginal:\n{text}")
            print(f"\nAnonymized:\n{result.anonymized_text}")
            print(f"\nMapping: {result.mapping}")
            print(f"\nRestored:\n{restored}")
            assert restored == text, f"Roundtrip failed:\n{text}"
            print("-" * WIDTH)
        print()
        return

    # Array of objects → walk each record, anonymize string leaves
    _print_header(f"{title}  [JSON]")
    if field_config:
        print(f"  Config: {config_path.name}\n")

    for record in records:
        flat_orig = _flatten(record)
        cell_results = _anonymize_flat(flat_orig, list(flat_orig.keys()), field_config)

        # Preserve original non-string types (numbers, booleans, nulls).
        # Only string fields go through anonymization; everything else is
        # kept at its original Python type when reconstructing the record.
        anon_flat: dict[str, Any] = {
            path_: (
                cell_results[path_].anonymized_text
                if isinstance(flat_orig[path_], str)
                else flat_orig[path_]
            )
            for path_ in flat_orig
        }
        all_mappings = {path_: cell_results[path_].mapping for path_ in flat_orig}
        flat_mapping = {k: v for m in all_mappings.values() for k, v in m.items()}

        anon_record  = _unflatten(anon_flat)

        print("Original:")
        print(json.dumps(record,      indent=2))
        print("\nAnonymized:")
        print(json.dumps(anon_record, indent=2))

        if flat_mapping:
            print("\nMapping:")
            for path_ in flat_orig:
                if all_mappings[path_]:
                    print(f"  {path_:<36} {all_mappings[path_]}")

        for path_ in flat_orig:
            if isinstance(flat_orig[path_], str):
                restored = anon.deanonymize(anon_flat[path_], cell_results[path_].mapping)
                assert restored == flat_orig[path_], (
                    f"Roundtrip failed for '{path_}': "
                    f"{flat_orig[path_]!r} → {restored!r}"
                )

        print("-" * WIDTH)
    print()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_sidecar(path: Path) -> tuple[dict, dict]:
    """Load a sidecar config file. Returns (full config, fields dict)."""
    if not path.exists():
        return {}, {}
    sidecar = json.loads(path.read_text())
    return sidecar, sidecar.get("fields", {})


def _anonymize_flat(
    row: dict[str, Any],
    keys: list[str],
    field_config: dict[str, dict],
) -> dict[str, AnonymizationResult]:
    """
    Anonymize a flat key→value dict. Non-string values are passed through.
    field_config controls per-key entities/skip/score_threshold.
    """
    results: dict[str, AnonymizationResult] = {}
    for key in keys:
        value = row[key]
        cfg   = field_config.get(key, {})
        if not isinstance(value, str) or cfg.get("skip"):
            results[key] = AnonymizationResult(anonymized_text=value if isinstance(value, str) else "")
        else:
            results[key] = anon.anonymize(
                value,
                entities=cfg.get("entities"),
                score_threshold=cfg.get("score_threshold"),
            )
    return results


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """
    Recursively flatten a nested dict into dot-notation keys.
      {"payer": {"name": "Alice"}} → {"payer.name": "Alice"}
    Non-dict values (including lists) are kept as-is at their path.
    """
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(_flatten(v, full_key))
            else:
                out[full_key] = v
    return out


def _unflatten(flat: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct a nested dict from dot-notation keys."""
    result: dict[str, Any] = {}
    for dot_key, value in flat.items():
        parts = dot_key.split(".")
        node = result
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return result


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
    csv_stems = {p.stem for p in DEMO_DATA_DIR.glob("*.csv")}
    py_stems  = [p.stem for p in DEMO_DATA_DIR.glob("*.py") if p.stem != "__init__"]
    json_stems = [
        p.stem for p in DEMO_DATA_DIR.glob("*.json")
        if p.stem not in csv_stems              # not a CSV sidecar
        and not p.name.endswith(".config.json") # not a JSON data sidecar
    ]
    return sorted(set(py_stems + list(csv_stems) + json_stems))


def _run(stem: str) -> None:
    if   (DEMO_DATA_DIR / f"{stem}.csv").exists():  run_csv(stem)
    elif (DEMO_DATA_DIR / f"{stem}.json").exists():  run_json(stem)
    else:                                             run_py(stem)


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
