"""
Shared type definitions used across the package.

Centralising these in one place prevents circular imports and gives a single
source of truth for the TypedDicts and Protocols that format handlers,
clients, and the public API all depend on.
"""

from __future__ import annotations

from typing import Iterator, Protocol, TypedDict, runtime_checkable


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PrivacyWrapperError(Exception):
    """Base exception for all redacit errors."""


class UnsupportedProviderError(PrivacyWrapperError):
    """Raised when an SDK client type is not recognised by PrivacyClient."""


class ModelNotFoundError(PrivacyWrapperError):
    """Raised when an explicitly requested spaCy model is not installed."""


# ---------------------------------------------------------------------------
# TypedDicts
# ---------------------------------------------------------------------------

class FieldConfig(TypedDict, total=False):
    """Per-field anonymization rules used in CSV and JSON sidecar configs."""

    entities: list[str]       # entity types to detect for this field only
    skip: bool                # if True, pass the field through unchanged
    score_threshold: float    # override confidence threshold for this field


class SidecarConfig(TypedDict, total=False):
    """Top-level structure of a .json or .config.json sidecar file."""

    title: str
    fields: dict[str, FieldConfig]


@runtime_checkable
class LLMClient(Protocol):
    """
    Structural protocol satisfied by any privacy-aware LLM client.

    Useful for type-checking code that accepts any client implementation
    without importing a concrete class.
    """

    def chat(self, prompt: str, system: str | None = None) -> str:
        """Anonymize prompt, call LLM, return deanonymized response."""
        ...

    def stream(self, prompt: str, system: str | None = None) -> Iterator[str]:
        """Streaming variant — yields response chunks with PII restored."""
        ...
