"""
Append-only JSONL audit logger for anonymization calls.

Each record contains metadata only — never the original text or mapping
values — so the log file is safe to retain and review for compliance
purposes without re-exposing sensitive data.

Log record fields:
    ts              ISO-8601 UTC timestamp
    input_hash      First 16 hex chars of SHA-256(input_text)
    entity_counts   Mapping of entity_type → count of redacted spans
    total_redacted  Total number of placeholders created
    provider        LLM provider string (e.g. "openai", "anthropic")
    model           Model identifier (e.g. "gpt-4o-mini")

Usage:
    with AuditLogger("privacy_audit.jsonl") as logger:
        client = PrivacyClient(audit_logger=logger)
        client.chat("Hi, I'm Alice at alice@example.com")
    # Appends: {"ts":"...","input_hash":"a3f9b2...","entity_counts":{"PERSON":1,"EMAIL_ADDRESS":1},...}
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import IO


class AuditLogger:
    """
    Append-only JSONL audit log.

    Accepts a file path (opened in append mode) or any writable text stream.
    Thread-safe for single-process use (each write is a single flush call).
    """

    def __init__(self, path: str | Path | IO[str]) -> None:
        if isinstance(path, (str, Path)):
            self._fh: IO[str] = open(path, "a", encoding="utf-8")
            self._owns_fh = True
        else:
            self._fh = path
            self._owns_fh = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(
        self,
        input_text: str,
        mapping: dict[str, str],
        provider: str = "unknown",
        model: str = "unknown",
    ) -> None:
        """Write one audit record. Original text and values are never stored."""
        entity_counts: dict[str, int] = {}
        for placeholder in mapping:
            # Placeholder format: <ENTITY_TYPE_index>
            entity_type = placeholder.strip("<>").rsplit("_", 1)[0]
            entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "input_hash": hashlib.sha256(input_text.encode()).hexdigest()[:16],
            "entity_counts": entity_counts,
            "total_redacted": len(mapping),
            "provider": provider,
            "model": model,
        }
        self._fh.write(json.dumps(record) + "\n")
        self._fh.flush()

    def close(self) -> None:
        """Close the file handle (only if opened by this instance)."""
        if self._owns_fh:
            self._fh.close()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> AuditLogger:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
