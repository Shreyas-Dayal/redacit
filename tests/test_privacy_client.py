"""Tests for the unified PrivacyClient drop-in proxy."""

from __future__ import annotations

import warnings
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from redacit.anonymizer import Anonymizer
from redacit.client.privacy_client import (
    PrivacyClient,
    _detect_adapter,
    _AnthropicAdapter,
    _CallFnAdapter,
    _GeminiAdapter,
    _OpenAIAdapter,
)
from redacit.session import PrivacySession


# ---------------------------------------------------------------------------
# Helpers — lightweight mock SDK clients with correct __module__
# ---------------------------------------------------------------------------

def _make_mock_client(module: str, cls_name: str = "Client") -> Any:
    """Create an object whose type().__module__ matches the expected SDK."""
    cls = type(cls_name, (), {"__module__": module})
    return cls()


def _openai_response(text: str) -> Any:
    """Simulate an OpenAI ChatCompletion response."""
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _anthropic_response(text: str) -> Any:
    """Simulate an Anthropic Message response."""
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


def _gemini_response(text: str) -> Any:
    """Simulate a Gemini GenerateContentResponse."""
    part = SimpleNamespace(text=text)
    content = SimpleNamespace(parts=[part])
    candidate = SimpleNamespace(content=content)
    resp = SimpleNamespace(candidates=[candidate])
    resp.text = text  # convenience property
    return resp


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

class TestDetection:

    def test_openai_detected(self):
        client = _make_mock_client("openai._client", "OpenAI")
        anon = Anonymizer()
        adapter = _detect_adapter(client, anon, None, None)
        assert isinstance(adapter, _OpenAIAdapter)

    def test_anthropic_detected(self):
        client = _make_mock_client("anthropic._client", "Anthropic")
        anon = Anonymizer()
        adapter = _detect_adapter(client, anon, None, None)
        assert isinstance(adapter, _AnthropicAdapter)

    def test_gemini_detected(self):
        client = _make_mock_client("google.genai.client", "Client")
        anon = Anonymizer()
        adapter = _detect_adapter(client, anon, None, None)
        assert isinstance(adapter, _GeminiAdapter)

    def test_unknown_raises(self):
        from redacit._types import UnsupportedProviderError

        client = _make_mock_client("cohere.client", "Client")
        anon = Anonymizer()
        with pytest.raises(UnsupportedProviderError, match="Unsupported SDK client"):
            _detect_adapter(client, anon, None, None)


# ---------------------------------------------------------------------------
# OpenAI proxy
# ---------------------------------------------------------------------------

class TestOpenAIProxy:

    @staticmethod
    def _build_openai_mock():
        mock_client = _make_mock_client("openai._client", "OpenAI")
        mock_chat = SimpleNamespace()
        mock_completions = MagicMock()
        mock_chat.completions = mock_completions
        mock_client.chat = mock_chat
        return mock_client, mock_completions

    def test_proxy_anonymizes_messages(self):
        mock_client, mock_completions = self._build_openai_mock()
        mock_completions.create.return_value = _openai_response("Reply about <PERSON_0>")

        client = PrivacyClient(mock_client)

        client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Tell me about John Smith"}],
        )

        sent_messages = mock_completions.create.call_args.kwargs["messages"]
        assert "John Smith" not in sent_messages[0]["content"]

    def test_proxy_deanonymizes_response(self):
        mock_client, mock_completions = self._build_openai_mock()

        mock_completions.create.side_effect = lambda *, messages, **kw: _openai_response(
            messages[0]["content"]
        )

        client = PrivacyClient(mock_client)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Email alice@example.com please"}],
        )
        # The response has placeholders deanonymized back to original
        assert "alice@example.com" in response.choices[0].message.content

    def test_system_passes_through(self):
        mock_client, mock_completions = self._build_openai_mock()
        mock_completions.create.return_value = _openai_response("ok")

        client = PrivacyClient(mock_client)
        client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
            ],
        )
        sent = mock_completions.create.call_args.kwargs["messages"]
        assert sent[0]["role"] == "system"
        assert sent[0]["content"] == "You are helpful"

    def test_getattr_delegates(self):
        mock_client, _ = self._build_openai_mock()
        mock_client.embeddings = "mock_embeddings"

        client = PrivacyClient(mock_client)
        assert client.embeddings == "mock_embeddings"


# ---------------------------------------------------------------------------
# OpenAI .query()
# ---------------------------------------------------------------------------

class TestOpenAIQuery:

    def test_query_anonymizes_and_deanonymizes(self):
        mock_client = _make_mock_client("openai._client", "OpenAI")
        mock_chat = SimpleNamespace()
        mock_completions = MagicMock()
        mock_chat.completions = mock_completions
        mock_client.chat = mock_chat

        def fake_create(*, model, messages):
            return _openai_response(messages[-1]["content"])

        mock_completions.create.side_effect = fake_create

        client = PrivacyClient(mock_client)
        result = client.query("Send report to alice@example.com", model="gpt-4o-mini")
        assert "alice@example.com" in result


# ---------------------------------------------------------------------------
# Anthropic proxy
# ---------------------------------------------------------------------------

class TestAnthropicProxy:

    @staticmethod
    def _build_anthropic_mock():
        mock_client = _make_mock_client("anthropic._client", "Anthropic")
        mock_messages = MagicMock()
        mock_client.messages = mock_messages
        return mock_client, mock_messages

    def test_proxy_anonymizes_messages(self):
        mock_client, mock_messages = self._build_anthropic_mock()
        mock_messages.create.return_value = _anthropic_response("ok")

        client = PrivacyClient(mock_client)
        client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=100,
            messages=[{"role": "user", "content": "Email alice@example.com"}],
        )
        sent = mock_messages.create.call_args.kwargs["messages"]
        assert "alice@example.com" not in sent[0]["content"]

    def test_proxy_anonymizes_system(self):
        mock_client, mock_messages = self._build_anthropic_mock()
        mock_messages.create.return_value = _anthropic_response("ok")

        client = PrivacyClient(mock_client)
        client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=100,
            system="Assist John Smith at john@acme.com",
            messages=[{"role": "user", "content": "Hello"}],
        )
        sent_system = mock_messages.create.call_args.kwargs.get("system", "")
        assert "john@acme.com" not in sent_system

    def test_proxy_deanonymizes_response(self):
        mock_client, mock_messages = self._build_anthropic_mock()

        def fake_create(*, messages, **kw):
            return _anthropic_response(messages[0]["content"])

        mock_messages.create.side_effect = fake_create
        client = PrivacyClient(mock_client)

        resp = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=100,
            messages=[{"role": "user", "content": "Email alice@example.com"}],
        )
        assert "alice@example.com" in resp.content[0].text

    def test_query_works(self):
        mock_client, mock_messages = self._build_anthropic_mock()

        def fake_create(**kw):
            return _anthropic_response(kw["messages"][0]["content"])

        mock_messages.create.side_effect = fake_create
        client = PrivacyClient(mock_client)
        result = client.query("Send to alice@example.com")
        assert "alice@example.com" in result


# ---------------------------------------------------------------------------
# Gemini proxy
# ---------------------------------------------------------------------------

class TestGeminiProxy:

    @staticmethod
    def _build_gemini_mock():
        mock_client = _make_mock_client("google.genai.client", "Client")
        mock_models = MagicMock()
        mock_client.models = mock_models
        return mock_client, mock_models

    def test_proxy_anonymizes_string_contents(self):
        mock_client, mock_models = self._build_gemini_mock()
        mock_models.generate_content.return_value = _gemini_response("ok")

        client = PrivacyClient(mock_client)
        client.models.generate_content(
            model="gemini-2.0-flash",
            contents="Email alice@example.com",
        )
        sent = mock_models.generate_content.call_args.kwargs["contents"]
        assert "alice@example.com" not in sent

    def test_proxy_deanonymizes_response(self):
        mock_client, mock_models = self._build_gemini_mock()

        def fake_gen(*, model, contents, **kw):
            return _gemini_response(contents)

        mock_models.generate_content.side_effect = fake_gen
        client = PrivacyClient(mock_client)

        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents="Email alice@example.com",
        )
        assert "alice@example.com" in resp.candidates[0].content.parts[0].text

    def test_query_works(self):
        mock_client, mock_models = self._build_gemini_mock()

        def fake_gen(*, model, contents, **kw):
            return _gemini_response(contents)

        mock_models.generate_content.side_effect = fake_gen
        client = PrivacyClient(mock_client)
        result = client.query("Send to alice@example.com")
        assert "alice@example.com" in result


# ---------------------------------------------------------------------------
# call_fn escape hatch
# ---------------------------------------------------------------------------

class TestCallFn:

    def test_query_anonymizes(self):
        calls: list[str] = []

        def my_fn(prompt: str, system: str | None) -> str:
            calls.append(prompt)
            return prompt  # echo

        client = PrivacyClient(call_fn=my_fn)
        result = client.query("Call alice@example.com")

        # The function received anonymized text
        assert "alice@example.com" not in calls[0]
        # The result was deanonymized
        assert "alice@example.com" in result

    def test_no_proxy_attrs(self):
        client = PrivacyClient(call_fn=lambda p, s: "ok")
        assert not hasattr(client, "chat")
        assert not hasattr(client, "messages")
        assert not hasattr(client, "models")


# ---------------------------------------------------------------------------
# Legacy compat
# ---------------------------------------------------------------------------

class TestLegacy:

    def test_api_key_emits_warning(self):
        with pytest.warns(DeprecationWarning, match="deprecated"):
            try:
                PrivacyClient(api_key="sk-test-fake-key-000000")
            except Exception:
                pass  # may fail to connect — we only test the warning

    def test_no_args_emits_warning(self):
        with pytest.warns(DeprecationWarning, match="deprecated"):
            try:
                PrivacyClient()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Session integration
# ---------------------------------------------------------------------------

class TestSessionProxy:

    def test_session_accumulates_across_calls(self):
        mock_client = _make_mock_client("openai._client", "OpenAI")
        mock_chat = SimpleNamespace()
        mock_completions = MagicMock()
        mock_completions.create.return_value = _openai_response("ok")
        mock_chat.completions = mock_completions
        mock_client.chat = mock_chat

        session = PrivacySession()
        client = PrivacyClient(mock_client, session=session)

        client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "I'm Alice Jones at alice@corp.com"}],
        )
        assert len(session) > 0

        first_count = len(session)

        client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "My SSN is 346-12-5678"}],
        )
        assert len(session) > first_count


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------

def test_repr():
    mock_client = _make_mock_client("openai._client", "OpenAI")
    mock_chat = SimpleNamespace()
    mock_chat.completions = MagicMock()
    mock_client.chat = mock_chat
    client = PrivacyClient(mock_client)
    assert "PrivacyClient(OpenAI)" in repr(client)
