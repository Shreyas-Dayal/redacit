"""
Internal helpers shared by CsvAnonymizer and JsonAnonymizer.

All four functions are moved verbatim from demo.py with one change:
anonymize_flat() receives the Anonymizer as an argument instead of
closing over a module-level global, making it testable in isolation.

Not part of the public API — import from privacy_wrapper.formats instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..anonymizer import Anonymizer, AnonymizationResult
from .._types import FieldConfig, SidecarConfig


# ---------------------------------------------------------------------------
# Sidecar config loading
# ---------------------------------------------------------------------------

def load_sidecar(path: Path) -> tuple[SidecarConfig, dict[str, FieldConfig]]:
    """
    Load a sidecar config file (.json or .config.json).
    Returns (full_config, fields_dict). Both are empty dicts if the file
    does not exist.
    """
    if not path.exists():
        return {}, {}  # type: ignore[return-value]
    sidecar: SidecarConfig = json.loads(path.read_text(encoding="utf-8"))
    return sidecar, sidecar.get("fields", {})  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Dict flattening / unflattening
# ---------------------------------------------------------------------------

def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """
    Recursively flatten a nested dict to dot-notation keys.
      {"payer": {"name": "Alice"}} → {"payer.name": "Alice"}
    Non-dict values (including lists) are kept as-is at their leaf path.
    """
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(flatten(v, full_key))
            else:
                out[full_key] = v
    return out


def unflatten(flat: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct a nested dict from dot-notation keys."""
    result: dict[str, Any] = {}
    for dot_key, value in flat.items():
        parts = dot_key.split(".")
        node = result
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return result


# ---------------------------------------------------------------------------
# Per-field anonymization
# ---------------------------------------------------------------------------

def deduplicate_placeholders(
    cell_results: dict[str, AnonymizationResult],
) -> dict[str, AnonymizationResult]:
    """
    Rename placeholders so they are globally unique across all fields.

    When each field is anonymized independently, two fields may both produce
    ``<PERSON_0>`` for different original values.  This helper reassigns
    indices with a single running counter so that no two fields share the
    same placeholder key.
    """
    counters: dict[str, int] = {}  # entity_type → next index

    for path in cell_results:
        result = cell_results[path]
        if not result.mapping:
            continue
        new_mapping: dict[str, str] = {}
        new_text = result.anonymized_text
        for old_ph, original in result.mapping.items():
            # <ENTITY_TYPE_N> → ENTITY_TYPE
            entity = old_ph.strip("<>").rsplit("_", 1)[0]
            idx = counters.get(entity, 0)
            counters[entity] = idx + 1
            new_ph = f"<{entity}_{idx}>"
            if new_ph != old_ph:
                new_text = new_text.replace(old_ph, new_ph)
            new_mapping[new_ph] = original
        cell_results[path] = AnonymizationResult(
            anonymized_text=new_text, mapping=new_mapping,
        )

    return cell_results


def anonymize_flat(
    row: dict[str, Any],
    keys: list[str],
    field_config: dict[str, FieldConfig],
    anonymizer: Anonymizer,
) -> dict[str, AnonymizationResult]:
    """
    Anonymize a flat key→value dict using per-key FieldConfig rules.

    Each string field is anonymized independently via ``anonymizer.anonymize()``.
    For a CSV with *R* rows and *C* columns, this means *R × C* Presidio calls.
    Performance scales linearly with data volume; there is no result caching
    for identical field values.

    - Non-string values pass through wrapped in an empty AnonymizationResult.
    - Keys with skip=True pass through unchanged.
    - Keys absent from field_config use Anonymizer instance defaults.
    """
    results: dict[str, AnonymizationResult] = {}
    for key in keys:
        value = row[key]
        cfg = field_config.get(key, {})

        if not isinstance(value, str) or cfg.get("skip"):
            results[key] = AnonymizationResult(
                anonymized_text=value if isinstance(value, str) else ""
            )
        else:
            results[key] = anonymizer.anonymize(
                value,
                entities=cfg.get("entities"),
                score_threshold=cfg.get("score_threshold"),
            )
    return results
