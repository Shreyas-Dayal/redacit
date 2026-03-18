"""
Abstract base class for all privacy-aware LLM clients.

Every provider subclass (OpenAI, LiteLLM, future Bedrock / Vertex) implements
only _call() and optionally _stream_raw(). The base class owns the full
anonymize → call → deanonymize lifecycle, session management, and audit
logging so that logic is never duplicated across providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Iterator

from ..anonymizer import Anonymizer

if TYPE_CHECKING:
    from ..audit import AuditLogger
    from ..session import PrivacySession


class BaseLLMClient(ABC):
    """
    Abstract base for all privacy-aware LLM clients.

    Args:
        anonymizer:   Anonymizer instance. A default is created if omitted.
        session:      PrivacySession for multi-turn mapping persistence.
                      None (default) gives stateless per-call behaviour.
        audit_logger: AuditLogger for compliance logging. None disables it.
    """

    def __init__(
        self,
        anonymizer: Anonymizer | None = None,
        session: PrivacySession | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self._anonymizer = anonymizer or Anonymizer()
        self._session = session
        self._audit = audit_logger

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def chat(self, prompt: str, system: str | None = None) -> str:
        """
        Anonymize prompt → call LLM → deanonymize response.

        When a PrivacySession is active the mapping is merged into it so
        placeholders remain resolvable across turns.
        """
        result = self._anonymizer.anonymize(prompt)

        if self._session is not None:
            self._session.update(result.mapping)
            mapping = self._session.mapping
        else:
            mapping = result.mapping

        if self._audit is not None:
            self._audit.log(
                prompt,
                result.mapping,
                provider=self._provider_name(),
                model=self._model_name(),
            )

        raw = self._call(result.anonymized_text, system)
        return self._anonymizer.deanonymize(raw, mapping)

    def stream(self, prompt: str, system: str | None = None) -> Iterator[str]:
        """
        Streaming variant.

        Buffers the full response before deanonymizing because placeholders
        may span token boundaries. A sliding-window optimisation that flushes
        tokens as they arrive is planned for a future sprint.
        """
        result = self._anonymizer.anonymize(prompt)

        if self._session is not None:
            self._session.update(result.mapping)
            mapping = self._session.mapping
        else:
            mapping = result.mapping

        if self._audit is not None:
            self._audit.log(
                prompt,
                result.mapping,
                provider=self._provider_name(),
                model=self._model_name(),
            )

        buffer = ""
        for chunk in self._stream_raw(result.anonymized_text, system):
            buffer += chunk

        yield self._anonymizer.deanonymize(buffer, mapping)

    # ------------------------------------------------------------------
    # Subclass interface
    # ------------------------------------------------------------------

    @abstractmethod
    def _call(self, prompt: str, system: str | None) -> str:
        """Make one non-streaming LLM call. Return the raw response string."""
        ...

    def _stream_raw(self, prompt: str, system: str | None) -> Iterator[str]:
        """Yield raw response chunks. Default: single chunk via _call()."""
        yield self._call(prompt, system)

    def _provider_name(self) -> str:
        """Provider label used in audit records. Override in subclasses."""
        return "unknown"

    def _model_name(self) -> str:
        """Model identifier used in audit records. Override in subclasses."""
        return "unknown"
