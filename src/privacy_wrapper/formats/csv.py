"""
CSV anonymization format handler.

Provides CsvAnonymizer, an iterator-based handler that processes a CSV file
one row at a time. The caller controls output — rows can be written to a new
file, streamed over HTTP, or collected for assertion in tests.

Sidecar config (.json file alongside the CSV) controls per-column rules:
    {
      "fields": {
        "name":           { "entities": ["PERSON"] },
        "account_number": { "entities": ["US_BANK_ACCOUNT"], "score_threshold": 0.0 },
        "date":           { "skip": true }
      }
    }
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .._types import FieldConfig, SidecarConfig
from ..anonymizer import Anonymizer
from ._helpers import anonymize_flat, load_sidecar


@dataclass
class CsvRowResult:
    """Anonymization result for a single CSV row."""

    row_index: int
    original: dict[str, str]
    anonymized: dict[str, str]
    # per-column placeholder→original mappings kept separate to prevent
    # collisions when the same placeholder appears in multiple columns
    mappings: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def flat_mapping(self) -> dict[str, str]:
        """Combined mapping across all columns — for deanonymizing free text."""
        return {k: v for m in self.mappings.values() for k, v in m.items()}


class CsvAnonymizer:
    """
    Anonymize a CSV file row by row, applying optional per-column config.

    Args:
        anonymizer: Shared Anonymizer instance. A default is created if omitted.
    """

    def __init__(self, anonymizer: Anonymizer | None = None) -> None:
        self._anon = anonymizer or Anonymizer()

    def anonymize_file(
        self,
        input_path: str | Path,
        field_config: dict[str, FieldConfig] | None = None,
    ) -> Iterator[CsvRowResult]:
        """
        Yield one CsvRowResult per data row.

        Args:
            input_path:   Path to the CSV file.
            field_config: Per-column FieldConfig rules. If omitted, default
                          Anonymizer settings are applied to every column.
                          Use load_sidecar() to build this from a .json file.
        """
        input_path = Path(input_path)
        cfg: dict[str, FieldConfig] = field_config or {}

        with input_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            headers = list(reader.fieldnames or [])

            for idx, row in enumerate(reader):
                cell_results = anonymize_flat(row, headers, cfg, self._anon)

                yield CsvRowResult(
                    row_index=idx,
                    original={col: row[col] for col in headers},
                    anonymized={
                        col: cell_results[col].anonymized_text for col in headers
                    },
                    mappings={
                        col: cell_results[col].mapping for col in headers
                    },
                )

    @staticmethod
    def load_sidecar(
        path: str | Path,
    ) -> tuple[SidecarConfig, dict[str, FieldConfig]]:
        """
        Load a .json sidecar config file alongside a CSV.
        Returns (full_config, fields_dict). Both empty if file not found.
        """
        return load_sidecar(Path(path))
