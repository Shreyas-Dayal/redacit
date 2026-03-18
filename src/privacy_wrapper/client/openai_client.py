"""
OpenAI-specific privacy-aware clients.

OpenAIPrivacyClient
    Simplified privacy-aware OpenAI chat client. Inherits BaseLLMClient for
    the ``.chat(prompt)`` / ``.stream(prompt)`` API. Use this if you want the
    simplified interface; use ``PrivacyClient(OpenAI())`` if you want a
    drop-in proxy that preserves all SDK call patterns.

PrivacyOpenAI
    Drop-in replacement for openai.OpenAI. Change ONE line in existing code:

        client = OpenAI()         # before
        client = PrivacyOpenAI()  # after

    All other call-site code — messages, tools, response_format, stream,
    embeddings, etc. — is identical. Implemented via delegation (not
    subclassing) for forward-compatibility with OpenAI SDK version changes.

    Note: isinstance(client, OpenAI) returns False for PrivacyOpenAI.
    Code relying on that check must use isinstance(client, PrivacyOpenAI)
    or duck-typing instead.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Iterator

from openai import OpenAI

from ..anonymizer import Anonymizer
from .base import BaseLLMClient

if TYPE_CHECKING:
    from ..audit import AuditLogger
    from ..session import PrivacySession


# ---------------------------------------------------------------------------
# OpenAIPrivacyClient — direct API wrapper (replaces client.py)
# ---------------------------------------------------------------------------

class OpenAIPrivacyClient(BaseLLMClient):
    """
    Privacy-aware OpenAI chat client.

    Anonymizes the prompt before sending and restores original values in the
    response. The public interface is identical to the original client.py.

    Args:
        api_key:      OpenAI API key. Reads OPENAI_API_KEY env var if omitted.
        model:        Model to use. Defaults to "gpt-4o-mini".
        anonymizer:   Custom Anonymizer instance.
        session:      PrivacySession for multi-turn mapping persistence.
        audit_logger: AuditLogger for compliance logging.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        anonymizer: Anonymizer | None = None,
        session: PrivacySession | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        super().__init__(anonymizer=anonymizer, session=session, audit_logger=audit_logger)
        self._openai = OpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
        self.model = model

    def _call(self, prompt: str, system: str | None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self._openai.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
        )
        return response.choices[0].message.content or ""

    def _stream_raw(self, prompt: str, system: str | None) -> Iterator[str]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        with self._openai.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            stream=True,
        ) as stream:
            for chunk in stream:
                yield chunk.choices[0].delta.content or ""

    def _provider_name(self) -> str:
        return "openai"

    def _model_name(self) -> str:
        return self.model


# ---------------------------------------------------------------------------
# PrivacyOpenAI — transparent proxy for openai.OpenAI
# ---------------------------------------------------------------------------

class _PrivacyCompletions:
    """
    Wraps openai.resources.chat.completions.Completions.

    Anonymizes user and assistant message content before the call.
    System prompts, tool results, and image_url blocks pass through unchanged.
    Deanonymizes response choices in-place after the call.
    """

    def __init__(self, completions: Any, anonymizer: Anonymizer) -> None:
        self._completions = completions
        self._anon = anonymizer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._completions, name)

    def create(self, *, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        merged_mapping: dict[str, str] = {}
        safe_messages: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str):
                result = self._anon.anonymize(content)
                merged_mapping.update(result.mapping)
                safe_messages.append({**msg, "content": result.anonymized_text})
            else:
                safe_messages.append(msg)

        response = self._completions.create(messages=safe_messages, **kwargs)

        if hasattr(response, "choices"):
            for choice in response.choices:
                if hasattr(choice, "message") and choice.message.content:
                    choice.message.content = self._anon.deanonymize(
                        choice.message.content, merged_mapping
                    )

        return response


class _PrivacyChat:
    def __init__(self, chat: Any, anonymizer: Anonymizer) -> None:
        self._chat = chat
        self.completions = _PrivacyCompletions(chat.completions, anonymizer)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


class PrivacyOpenAI:
    """
    Drop-in replacement for openai.OpenAI that anonymizes message content
    before every API call and restores original values in the response.

    Usage — change one line:
        client = OpenAI()         # before
        client = PrivacyOpenAI()  # after

    All OpenAI SDK call patterns continue to work unchanged:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[...],
            tools=[...],           # function calling — unchanged
            response_format=...,   # structured output — unchanged
        )

    Non-intercepted attributes (audio, beta, embeddings, files, fine_tuning,
    images, models, moderations) delegate transparently to the underlying
    openai.OpenAI instance via __getattr__.
    """

    def __init__(
        self,
        *args: Any,
        anonymizer: Anonymizer | None = None,
        **kwargs: Any,
    ) -> None:
        self._inner = OpenAI(*args, **kwargs)
        _anon = anonymizer or Anonymizer()
        self.chat = _PrivacyChat(self._inner.chat, _anon)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
