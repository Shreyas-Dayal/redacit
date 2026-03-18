from .anonymizer import Anonymizer, AnonymizationResult
from .audit import AuditLogger
from .client import (
    BaseLLMClient,
    LiteLLMPrivacyClient,
    OpenAIPrivacyClient,
    PrivacyClient,
    PrivacyOpenAI,
)
from .formats import CsvAnonymizer, CsvRowResult, JsonAnonymizer, JsonRecordResult
from .session import PrivacySession
from ._types import (
    FieldConfig,
    LLMClient,
    ModelNotFoundError,
    PrivacyWrapperError,
    SidecarConfig,
    UnsupportedProviderError,
)

__all__ = [
    # Core
    "Anonymizer",
    "AnonymizationResult",
    # Convenience — module-level wrappers around a shared Anonymizer instance
    "anonymize",
    "deanonymize",
    # Clients
    "BaseLLMClient",
    "PrivacyClient",
    "OpenAIPrivacyClient",
    "PrivacyOpenAI",
    "LiteLLMPrivacyClient",
    # Session & audit
    "PrivacySession",
    "AuditLogger",
    # Format handlers
    "CsvAnonymizer",
    "CsvRowResult",
    "JsonAnonymizer",
    "JsonRecordResult",
    # Types
    "FieldConfig",
    "SidecarConfig",
    "LLMClient",
    # Exceptions
    "PrivacyWrapperError",
    "UnsupportedProviderError",
    "ModelNotFoundError",
]

_default_anonymizer: Anonymizer | None = None


def _get_default() -> Anonymizer:
    global _default_anonymizer
    if _default_anonymizer is None:
        _default_anonymizer = Anonymizer()
    return _default_anonymizer


def anonymize(
    text: str,
    entities: list[str] | None = None,
    score_threshold: float | None = None,
) -> AnonymizationResult:
    """Anonymize *text* using a shared module-level Anonymizer instance."""
    return _get_default().anonymize(text, entities=entities, score_threshold=score_threshold)


def deanonymize(text: str, mapping: dict[str, str]) -> str:
    """Restore original values in *text* using *mapping*."""
    return _get_default().deanonymize(text, mapping)
