"""
JSON anonymization format handler.

Provides JsonAnonymizer, an iterator-based handler that processes an array of
JSON objects. Nested objects are flattened to dot-notation paths, each string
leaf is anonymized independently, and the structure is reconstructed. Non-string
values (numbers, booleans, nulls) pass through unchanged.

Sidecar config (.config.json file alongside the data file) controls per-path rules:
    {
      "fields": {
        "payer.name":    { "entities": ["PERSON"] },
        "taxpayer.ein":  { "entities": ["EIN"], "score_threshold": 0.0 },
        "meta.version":  { "skip": true }
      }
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .._types import FieldConfig, SidecarConfig
from ..anonymizer import Anonymizer
from ._helpers import anonymize_flat, deduplicate_placeholders, flatten, load_sidecar, unflatten


@dataclass
class JsonRecordResult:
    """Anonymization result for a single JSON record (object)."""

    record_index: int
    original: dict[str, Any]
    anonymized: dict[str, Any]
    flat_mapping: dict[str, str] = field(default_factory=dict)


class JsonAnonymizer:
    """
    Anonymize an array of JSON objects, applying optional per-path config.

    Args:
        anonymizer: Shared Anonymizer instance. A default is created if omitted.
    """

    def __init__(self, anonymizer: Anonymizer | None = None) -> None:
        self._anon = anonymizer or Anonymizer()

    def anonymize_records(
        self,
        records: list[dict[str, Any]],
        field_config: dict[str, FieldConfig] | None = None,
    ) -> Iterator[JsonRecordResult]:
        """
        Yield one JsonRecordResult per record in the list.

        Nested dicts are flattened to dot-notation for per-path config matching,
        anonymized, then unflattened back to the original structure. Non-string
        leaf values are preserved at their original Python type.

        Args:
            records:      List of JSON objects (dicts).
            field_config: Per-dot-path FieldConfig rules. If omitted, default
                          Anonymizer settings are applied to every string field.
        """
        cfg: dict[str, FieldConfig] = field_config or {}

        for idx, record in enumerate(records):
            flat_orig = flatten(record)
            cell_results = anonymize_flat(flat_orig, list(flat_orig.keys()), cfg, self._anon)
            cell_results = deduplicate_placeholders(cell_results)

            # Preserve original non-string types (numbers, booleans, nulls).
            anon_flat: dict[str, Any] = {
                path: (
                    cell_results[path].anonymized_text
                    if isinstance(flat_orig[path], str)
                    else flat_orig[path]
                )
                for path in flat_orig
            }

            flat_mapping: dict[str, str] = {
                k: v
                for path in flat_orig
                for k, v in cell_results[path].mapping.items()
            }

            yield JsonRecordResult(
                record_index=idx,
                original=record,
                anonymized=unflatten(anon_flat),
                flat_mapping=flat_mapping,
            )

    def anonymize_file(
        self,
        input_path: str | Path,
        config_path: str | Path | None = None,
    ) -> Iterator[JsonRecordResult]:
        """
        Load a JSON file and yield one JsonRecordResult per record.

        Args:
            input_path:  Path to the JSON data file (array of objects).
            config_path: Path to the .config.json sidecar. If omitted, a
                         file named <stem>.config.json alongside input_path
                         is tried automatically.
        """
        input_path = Path(input_path)
        if config_path is None:
            config_path = input_path.with_suffix("").with_suffix(".config.json")

        _, field_config = load_sidecar(Path(config_path))
        records: list[dict[str, Any]] = json.loads(
            input_path.read_text(encoding="utf-8")
        )

        yield from self.anonymize_records(records, field_config)

    @staticmethod
    def load_sidecar(
        path: str | Path,
    ) -> tuple[SidecarConfig, dict[str, FieldConfig]]:
        """
        Load a .config.json sidecar file.
        Returns (full_config, fields_dict). Both empty if file not found.
        """
        return load_sidecar(Path(path))
