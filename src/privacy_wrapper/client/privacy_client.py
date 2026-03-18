"""
Unified privacy proxy for any LLM SDK client.

Wraps an existing SDK client (OpenAI, Anthropic, Gemini) and intercepts
the chat/message call path to anonymize PII before sending and restore
original values in the response. All other SDK features delegate
transparently to the inner client.

Usage — change one line:
    client = PrivacyClient(OpenAI())          # was: OpenAI()
    client = PrivacyClient(Anthropic())       # was: Anthropic()
    client = PrivacyClient(genai.Client())    # was: genai.Client()

All existing call-site code stays identical.

Simplified API (works for any SDK):
    reply = client.query("Summarise this for Alice at alice@corp.com")
"""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING, Any, Callable

from ..anonymizer import Anonymizer
from .._types import UnsupportedProviderError

if TYPE_CHECKING:
    from ..audit import AuditLogger
    from ..session import PrivacySession


# ---------------------------------------------------------------------------
# Base adapter — shared anonymize / deanonymize / session / audit lifecycle
# ---------------------------------------------------------------------------

class _BaseAdapter:
    """Internal base for per-SDK adapters."""

    provider: str = "unknown"

    def __init__(
        self,
        inner: Any,
        anonymizer: Anonymizer,
        session: PrivacySession | None,
        audit_logger: AuditLogger | None,
    ) -> None:
        self._inner = inner
        self._anon = anonymizer
        self._session = session
        self._audit = audit_logger

    # -- shared helpers ---------------------------------------------------

    def _anonymize(self, text: str) -> tuple[str, dict[str, str]]:
        """Anonymize *text*, merge into session if active."""
        result = self._anon.anonymize(text)
        if self._session is not None:
            self._session.update(result.mapping)
        return result.anonymized_text, result.mapping

    def _mapping(self, call_mapping: dict[str, str]) -> dict[str, str]:
        """Return the mapping to use for deanonymization."""
        if self._session is not None:
            return self._session.mapping
        return call_mapping

    def _deanonymize(self, text: str, mapping: dict[str, str]) -> str:
        return self._anon.deanonymize(text, mapping)

    def _log(self, input_text: str, mapping: dict[str, str], model: str) -> None:
        if self._audit is not None:
            self._audit.log(input_text, mapping, provider=self.provider, model=model)

    # -- subclass interface -----------------------------------------------

    def setup(self, proxy: PrivacyClient) -> None:
        """Set intercepted attributes on the proxy object."""
        raise NotImplementedError

    def call(self, prompt: str, system: str | None, model: str | None) -> str:
        """Execute a single anonymized call for ``.query()``."""
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════════════════
# OpenAI adapter
# ═══════════════════════════════════════════════════════════════════════════

class _OpenAICompletionsProxy:
    """Wraps ``openai.resources.chat.completions.Completions``."""

    def __init__(self, completions: Any, adapter: _BaseAdapter) -> None:
        self._completions = completions
        self._adapter = adapter

    def create(self, *, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        merged: dict[str, str] = {}
        safe: list[dict[str, Any]] = []
        user_texts: list[str] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str):
                anon_text, m = self._adapter._anonymize(content)
                merged.update(m)
                safe.append({**msg, "content": anon_text})
                if role == "user":
                    user_texts.append(content)
            else:
                safe.append(msg)

        mapping = self._adapter._mapping(merged)
        model = str(kwargs.get("model", "unknown"))
        if user_texts:
            self._adapter._log("\n".join(user_texts), merged, model)

        is_stream = kwargs.get("stream", False)
        if is_stream:
            _log.warning(
                "OpenAI proxy streaming: input is anonymized but response "
                "chunks will contain placeholders. Use .query() for full "
                "deanonymization, or use OpenAIPrivacyClient.stream()."
            )

        response = self._completions.create(messages=safe, **kwargs)

        if not is_stream and hasattr(response, "choices"):
            for choice in response.choices:
                if hasattr(choice, "message") and choice.message.content:
                    choice.message.content = self._adapter._deanonymize(
                        choice.message.content, mapping
                    )
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._completions, name)


class _OpenAIChatProxy:
    """Wraps ``openai.resources.chat.Chat``."""

    def __init__(self, chat: Any, adapter: _BaseAdapter) -> None:
        self._chat = chat
        self.completions = _OpenAICompletionsProxy(chat.completions, adapter)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


class _OpenAIAdapter(_BaseAdapter):
    provider = "openai"

    def setup(self, proxy: PrivacyClient) -> None:
        proxy.chat = _OpenAIChatProxy(self._inner.chat, self)  # type: ignore[attr-defined]

    def call(self, prompt: str, system: str | None, model: str | None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        merged: dict[str, str] = {}
        safe: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str):
                anon_text, m = self._anonymize(content)
                merged.update(m)
                safe.append({**msg, "content": anon_text})
            else:
                safe.append(msg)

        mapping = self._mapping(merged)
        _model = model or "gpt-4o-mini"
        self._log(prompt, merged, _model)

        response = self._inner.chat.completions.create(model=_model, messages=safe)
        return self._deanonymize(response.choices[0].message.content or "", mapping)


# ═══════════════════════════════════════════════════════════════════════════
# Anthropic adapter
# ═══════════════════════════════════════════════════════════════════════════

class _AnthropicMessagesProxy:
    """Wraps ``anthropic.resources.messages.Messages``."""

    def __init__(self, messages_resource: Any, adapter: _BaseAdapter) -> None:
        self._messages = messages_resource
        self._adapter = adapter

    def _anonymize_content(self, content: Any) -> tuple[Any, dict[str, str]]:
        """Anonymize message content — handles str and list-of-blocks forms."""
        if isinstance(content, str):
            return self._adapter._anonymize(content)
        if isinstance(content, list):
            merged: dict[str, str] = {}
            anon_blocks: list[Any] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    anon_text, m = self._adapter._anonymize(block["text"])
                    merged.update(m)
                    anon_blocks.append({**block, "text": anon_text})
                else:
                    anon_blocks.append(block)
            return anon_blocks, merged
        return content, {}

    def create(self, *, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        merged: dict[str, str] = {}
        safe: list[dict[str, Any]] = []
        user_texts: list[str] = []

        # Anonymize system if present (top-level param, not in messages)
        system = kwargs.pop("system", None)
        if isinstance(system, str):
            anon_sys, m = self._adapter._anonymize(system)
            merged.update(m)
            kwargs["system"] = anon_sys
        elif system is not None:
            # list-of-blocks form
            anon_sys, m = self._anonymize_content(system)
            merged.update(m)
            kwargs["system"] = anon_sys

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant"):
                anon_content, m = self._anonymize_content(content)
                merged.update(m)
                safe.append({**msg, "content": anon_content})
                if role == "user" and isinstance(content, str):
                    user_texts.append(content)
            else:
                safe.append(msg)

        mapping = self._adapter._mapping(merged)
        model = str(kwargs.get("model", "unknown"))
        if user_texts:
            self._adapter._log("\n".join(user_texts), merged, model)

        response = self._messages.create(messages=safe, **kwargs)

        # Deanonymize response content blocks
        if hasattr(response, "content"):
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    try:
                        block.text = self._adapter._deanonymize(block.text, mapping)
                    except (AttributeError, TypeError):
                        _log.debug("Could not mutate response field for deanonymization (frozen model?)")

        return response

    def stream(self, **kwargs: Any) -> Any:
        """Wrap Anthropic's streaming context manager with anonymization."""
        # Extract and anonymize messages/system the same way as create()
        messages = kwargs.pop("messages", [])
        merged: dict[str, str] = {}
        safe: list[dict[str, Any]] = []

        system = kwargs.pop("system", None)
        if isinstance(system, str):
            anon_sys, m = self._adapter._anonymize(system)
            merged.update(m)
            kwargs["system"] = anon_sys
        elif system is not None:
            anon_sys, m = self._anonymize_content(system)
            merged.update(m)
            kwargs["system"] = anon_sys

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant"):
                anon_content, m = self._anonymize_content(content)
                merged.update(m)
                safe.append({**msg, "content": anon_content})
            else:
                safe.append(msg)

        mapping = self._adapter._mapping(merged)

        _log.warning(
            "Anthropic proxy streaming: input is anonymized but response "
            "text will contain placeholders. Use .query() for full "
            "deanonymization, or use LiteLLMPrivacyClient.stream()."
        )
        return self._messages.stream(messages=safe, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._messages, name)


class _AnthropicAdapter(_BaseAdapter):
    provider = "anthropic"

    def setup(self, proxy: PrivacyClient) -> None:
        proxy.messages = _AnthropicMessagesProxy(self._inner.messages, self)  # type: ignore[attr-defined]

    def call(self, prompt: str, system: str | None, model: str | None) -> str:
        merged: dict[str, str] = {}
        anon_prompt, m = self._anonymize(prompt)
        merged.update(m)

        kwargs: dict[str, Any] = {
            "model": model or "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": anon_prompt}],
        }
        if system:
            anon_sys, m = self._anonymize(system)
            merged.update(m)
            kwargs["system"] = anon_sys

        mapping = self._mapping(merged)
        self._log(prompt, merged, kwargs["model"])

        response = self._inner.messages.create(**kwargs)
        raw = response.content[0].text if response.content else ""
        return self._deanonymize(raw, mapping)


# ═══════════════════════════════════════════════════════════════════════════
# Gemini adapter
# ═══════════════════════════════════════════════════════════════════════════

class _GeminiModelsProxy:
    """Wraps ``google.genai.models.Models``."""

    def __init__(self, models_resource: Any, adapter: _BaseAdapter) -> None:
        self._models = models_resource
        self._adapter = adapter

    def _anonymize_contents(self, contents: Any) -> tuple[Any, dict[str, str]]:
        """Anonymize contents — handles str, list[str], and Content objects."""
        if isinstance(contents, str):
            return self._adapter._anonymize(contents)
        if isinstance(contents, list):
            merged: dict[str, str] = {}
            anon: list[Any] = []
            for item in contents:
                if isinstance(item, str):
                    anon_text, m = self._adapter._anonymize(item)
                    merged.update(m)
                    anon.append(anon_text)
                elif hasattr(item, "parts"):
                    # Content object — anonymize text parts
                    role = getattr(item, "role", "user")
                    if role in ("user", "model"):
                        for part in item.parts:
                            if hasattr(part, "text") and part.text:
                                anon_text, m = self._adapter._anonymize(part.text)
                                merged.update(m)
                                try:
                                    part.text = anon_text
                                except (AttributeError, TypeError):
                                    _log.debug("Could not mutate Content part for anonymization (frozen model?)")
                    anon.append(item)
                else:
                    anon.append(item)
            return anon, merged
        # Single Content object
        if hasattr(contents, "parts"):
            for part in contents.parts:
                if hasattr(part, "text") and part.text:
                    anon_text, m = self._adapter._anonymize(part.text)
                    try:
                        part.text = anon_text
                    except (AttributeError, TypeError):
                        _log.debug("Could not mutate Content part for anonymization (frozen model?)")
                    return contents, m
        return contents, {}

    def _anonymize_config(self, config: Any) -> dict[str, str]:
        """Anonymize system_instruction inside config if present."""
        if config is None:
            return {}
        si = getattr(config, "system_instruction", None)
        if isinstance(si, str):
            anon_si, m = self._adapter._anonymize(si)
            try:
                config.system_instruction = anon_si
            except (AttributeError, TypeError):
                _log.debug("Could not mutate config.system_instruction (frozen model?)")
            return m
        return {}

    def generate_content(self, *, model: str, contents: Any, **kwargs: Any) -> Any:
        config = kwargs.get("config", None)
        merged: dict[str, str] = {}

        merged.update(self._anonymize_config(config))
        anon_contents, m = self._anonymize_contents(contents)
        merged.update(m)

        mapping = self._adapter._mapping(merged)
        if isinstance(contents, str):
            self._adapter._log(contents, merged, model)

        response = self._models.generate_content(model=model, contents=anon_contents, **kwargs)

        # Deanonymize response parts
        if hasattr(response, "candidates"):
            for candidate in response.candidates:
                if hasattr(candidate, "content") and hasattr(candidate.content, "parts"):
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            try:
                                part.text = self._adapter._deanonymize(part.text, mapping)
                            except (AttributeError, TypeError):
                                _log.debug("Could not mutate response field for deanonymization (frozen model?)")
        return response

    def generate_content_stream(self, *, model: str, contents: Any, **kwargs: Any) -> Any:
        """Streaming variant — anonymizes input, delegates stream as-is."""
        config = kwargs.get("config", None)
        merged: dict[str, str] = {}
        merged.update(self._anonymize_config(config))
        anon_contents, m = self._anonymize_contents(contents)
        merged.update(m)
        _log.warning(
            "Gemini proxy streaming: input is anonymized but response "
            "text will contain placeholders. Use .query() for full "
            "deanonymization, or use LiteLLMPrivacyClient.stream()."
        )
        return self._models.generate_content_stream(model=model, contents=anon_contents, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._models, name)


class _GeminiAdapter(_BaseAdapter):
    provider = "gemini"

    def setup(self, proxy: PrivacyClient) -> None:
        proxy.models = _GeminiModelsProxy(self._inner.models, self)  # type: ignore[attr-defined]

    def call(self, prompt: str, system: str | None, model: str | None) -> str:
        merged: dict[str, str] = {}
        anon_prompt, m = self._anonymize(prompt)
        merged.update(m)

        kwargs: dict[str, Any] = {}
        if system:
            anon_sys, m = self._anonymize(system)
            merged.update(m)
            # Build a config dict — we can't import GenerateContentConfig
            kwargs["config"] = {"system_instruction": anon_sys}

        mapping = self._mapping(merged)
        _model = model or "gemini-2.0-flash"
        self._log(prompt, merged, _model)

        response = self._inner.models.generate_content(
            model=_model, contents=anon_prompt, **kwargs,
        )
        raw = response.text if hasattr(response, "text") else ""
        return self._deanonymize(raw, mapping)


# ═══════════════════════════════════════════════════════════════════════════
# call_fn adapter (escape hatch for unsupported SDKs)
# ═══════════════════════════════════════════════════════════════════════════

class _CallFnAdapter(_BaseAdapter):
    provider = "custom"

    def __init__(
        self,
        inner: Any,
        anonymizer: Anonymizer,
        session: PrivacySession | None,
        audit_logger: AuditLogger | None,
        call_fn: Callable[[str, str | None], str],
    ) -> None:
        super().__init__(inner, anonymizer, session, audit_logger)
        self._call_fn = call_fn

    def setup(self, proxy: PrivacyClient) -> None:
        pass  # no proxy interception — .query() only

    def call(self, prompt: str, system: str | None, model: str | None) -> str:
        anon_prompt, merged = self._anonymize(prompt)
        mapping = self._mapping(merged)
        self._log(prompt, merged, model or "unknown")
        raw = self._call_fn(anon_prompt, system)
        return self._deanonymize(raw, mapping)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

_SDK_PREFIXES = {
    "openai": _OpenAIAdapter,
    "anthropic": _AnthropicAdapter,
    "google": _GeminiAdapter,
}


def _detect_adapter(
    client: Any,
    anonymizer: Anonymizer,
    session: PrivacySession | None,
    audit_logger: AuditLogger | None,
) -> _BaseAdapter:
    module = type(client).__module__
    for prefix, cls in _SDK_PREFIXES.items():
        if module.startswith(prefix):
            return cls(client, anonymizer, session, audit_logger)
    raise UnsupportedProviderError(
        f"Unsupported SDK client: {module}.{type(client).__name__}. "
        "Pass call_fn=... for unsupported SDKs, or use LiteLLMPrivacyClient."
    )


# ---------------------------------------------------------------------------
# Unified PrivacyClient
# ---------------------------------------------------------------------------

class PrivacyClient:
    """
    Unified privacy proxy for any LLM SDK client.

    Wraps an existing SDK client and intercepts the chat/message call path to
    anonymize PII before sending and restore original values in the response.
    All other SDK features delegate transparently to the inner client.

    Supported SDKs:
        openai.OpenAI, anthropic.Anthropic, google.genai.Client

    For other SDKs, pass ``call_fn`` for a simplified interface.

    Args:
        client:       An already-constructed SDK client (e.g. ``OpenAI()``).
        anonymizer:   Custom Anonymizer instance.
        session:      PrivacySession for cross-turn mapping persistence.
        audit_logger: AuditLogger for compliance logging.
        call_fn:      Escape hatch — ``(prompt, system) -> str`` callable for
                      unsupported SDKs.  Only ``.query()`` is available.
        api_key:      *Deprecated.* Creates an OpenAI client internally.
        model:        Default model for ``.query()`` calls.
    """

    def __init__(
        self,
        client: Any = None,
        *,
        anonymizer: Anonymizer | None = None,
        session: PrivacySession | None = None,
        audit_logger: AuditLogger | None = None,
        call_fn: Callable[[str, str | None], str] | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        anon = anonymizer or Anonymizer()
        self._model = model

        if call_fn is not None:
            self._inner = client
            self._adapter = _CallFnAdapter(client, anon, session, audit_logger, call_fn)
            self._adapter.setup(self)
        elif client is not None and not isinstance(client, str):
            self._inner = client
            self._adapter = _detect_adapter(client, anon, session, audit_logger)
            self._adapter.setup(self)
        elif api_key is not None or client is None:
            # Legacy path: PrivacyClient(api_key="sk-...") or PrivacyClient()
            warnings.warn(
                "PrivacyClient(api_key=...) is deprecated. "
                "Use PrivacyClient(openai.OpenAI(api_key=...)) "
                "or OpenAIPrivacyClient(api_key=...).",
                DeprecationWarning,
                stacklevel=2,
            )
            from openai import OpenAI as _OpenAI

            key = api_key or (client if isinstance(client, str) else None)
            self._inner = _OpenAI(api_key=key or os.environ.get("OPENAI_API_KEY"))
            self._model = model or "gpt-4o-mini"
            self._adapter = _OpenAIAdapter(self._inner, anon, session, audit_logger)
            self._adapter.setup(self)

    # -- simplified API ---------------------------------------------------

    def query(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
    ) -> str:
        """
        Simplified API: anonymize → call LLM → deanonymize.

        Works regardless of which SDK client was injected.

        Args:
            prompt: User message text.
            system: Optional system instruction.
            model:  Model override for this call (uses constructor default otherwise).
        """
        return self._adapter.call(prompt, system, model or self._model)

    # -- drop-in proxy delegation -----------------------------------------

    def __getattr__(self, name: str) -> Any:
        # Called only when normal attribute lookup fails.
        # Intercepted attrs (chat / messages / models) are set directly on
        # the instance by the adapter's setup(), so they resolve before this.
        if "_inner" in self.__dict__ and self._inner is not None:
            return getattr(self._inner, name)
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    def __repr__(self) -> str:
        inner = self._inner
        sdk = type(inner).__name__ if inner else "call_fn"
        return f"PrivacyClient({sdk})"
