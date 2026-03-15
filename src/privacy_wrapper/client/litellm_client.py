"""
LiteLLM-based privacy client for multi-provider LLM routing.

Routes anonymized prompts to any provider supported by LiteLLM:
    openai/gpt-4o, anthropic/claude-opus-4-6, gemini/gemini-2.0-flash,
    azure/gpt-4o, ollama/llama3, bedrock/anthropic.claude-3-sonnet, …

litellm is a lazy import — the package is fully importable and usable
without litellm installed. The ImportError surfaces only when
LiteLLMPrivacyClient._call() is first invoked, with a clear install
message pointing to the correct optional extra.

Usage:
    from privacy_wrapper import LiteLLMPrivacyClient

    client = LiteLLMPrivacyClient("anthropic/claude-opus-4-6")
    response = client.chat("Summarize this for Alice at alice@acme.com")
    # Alice and her email are never sent to Anthropic
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

from ..anonymizer import Anonymizer
from .base import BaseLLMClient

if TYPE_CHECKING:
    from ..audit import AuditLogger
    from ..session import PrivacySession

_INSTALL_MSG = (
    "litellm is required for LiteLLMPrivacyClient. "
    "Install it with:  uv add 'wrapper-llm[litellm]'"
)


class LiteLLMPrivacyClient(BaseLLMClient):
    """
    Privacy-aware LLM client that routes to any provider via LiteLLM.

    Args:
        model:           LiteLLM model string, e.g. "anthropic/claude-opus-4-6",
                         "ollama/llama3", "gemini/gemini-2.0-flash".
        anonymizer:      Custom Anonymizer instance.
        session:         PrivacySession for multi-turn mapping persistence.
        audit_logger:    AuditLogger for compliance logging.
        **litellm_kwargs Passed directly to litellm.completion() —
                         api_key, api_base, temperature, max_tokens, etc.
    """

    def __init__(
        self,
        model: str,
        anonymizer: Anonymizer | None = None,
        session: PrivacySession | None = None,
        audit_logger: AuditLogger | None = None,
        **litellm_kwargs: object,
    ) -> None:
        super().__init__(anonymizer=anonymizer, session=session, audit_logger=audit_logger)
        self.model = model
        self._litellm_kwargs = litellm_kwargs

    def _call(self, prompt: str, system: str | None) -> str:
        try:
            import litellm
        except ImportError as exc:
            raise ImportError(_INSTALL_MSG) from exc

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = litellm.completion(
            model=self.model,
            messages=messages,
            **self._litellm_kwargs,
        )
        return response.choices[0].message.content or ""

    def _stream_raw(self, prompt: str, system: str | None) -> Iterator[str]:
        try:
            import litellm
        except ImportError as exc:
            raise ImportError(_INSTALL_MSG) from exc

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        for chunk in litellm.completion(
            model=self.model,
            messages=messages,
            stream=True,
            **self._litellm_kwargs,
        ):
            yield chunk.choices[0].delta.content or ""

    def _provider_name(self) -> str:
        # "anthropic/claude-opus-4-6" → "anthropic"
        return self.model.split("/")[0] if "/" in self.model else "litellm"

    def _model_name(self) -> str:
        return self.model
