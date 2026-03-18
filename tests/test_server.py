"""FastAPI server endpoint tests."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from privacy_wrapper.server import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /anonymize
# ---------------------------------------------------------------------------

class TestAnonymizeEndpoint:

    def test_pii_redacted(self):
        resp = client.post("/anonymize", json={"text": "Contact alice@example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert "alice@example.com" not in data["anonymized_text"]
        assert "alice@example.com" in data["mapping"].values()

    def test_no_pii_passthrough(self):
        resp = client.post("/anonymize", json={"text": "What is 2 + 2?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["anonymized_text"] == "What is 2 + 2?"
        assert data["mapping"] == {}

    def test_mapping_keys_are_placeholders(self):
        resp = client.post("/anonymize", json={"text": "Email bob@test.com"})
        assert resp.status_code == 200
        for key in resp.json()["mapping"]:
            assert key.startswith("<") and key.endswith(">")

    def test_entity_filter(self):
        resp = client.post(
            "/anonymize",
            json={"text": "John Smith at alice@example.com", "entities": ["PERSON"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "John Smith" not in data["anonymized_text"]
        # Email not in entities filter → not redacted
        assert "alice@example.com" in data["anonymized_text"]

    def test_score_threshold_accepted(self):
        resp = client.post(
            "/anonymize",
            json={"text": "No PII here.", "score_threshold": 0.9},
        )
        assert resp.status_code == 200

    def test_missing_text_field_returns_422(self):
        resp = client.post("/anonymize", json={"score_threshold": 0.5})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /deanonymize
# ---------------------------------------------------------------------------

class TestDeanonymizeEndpoint:

    def test_restores_original(self):
        resp = client.post(
            "/deanonymize",
            json={
                "text": "Contact <EMAIL_ADDRESS_0>",
                "mapping": {"<EMAIL_ADDRESS_0>": "alice@example.com"},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "Contact alice@example.com"

    def test_empty_mapping_is_noop(self):
        resp = client.post(
            "/deanonymize",
            json={"text": "Nothing to restore.", "mapping": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "Nothing to restore."

    def test_multiple_placeholders(self):
        resp = client.post(
            "/deanonymize",
            json={
                "text": "Sent to <PERSON_0> at <EMAIL_ADDRESS_0>.",
                "mapping": {
                    "<PERSON_0>": "Alice",
                    "<EMAIL_ADDRESS_0>": "alice@corp.com",
                },
            },
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "Sent to Alice at alice@corp.com."

    def test_missing_fields_returns_422(self):
        resp = client.post("/deanonymize", json={"text": "hello"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Roundtrip via API
# ---------------------------------------------------------------------------

def test_roundtrip_via_api():
    original = "Send the report to bob@company.com by Friday."

    anon_resp = client.post("/anonymize", json={"text": original})
    assert anon_resp.status_code == 200
    anon_data = anon_resp.json()

    deano_resp = client.post(
        "/deanonymize",
        json={
            "text": anon_data["anonymized_text"],
            "mapping": anon_data["mapping"],
        },
    )
    assert deano_resp.status_code == 200
    assert deano_resp.json()["text"] == original


# ---------------------------------------------------------------------------
# POST /chat — only tests the no-API-key error path (avoids real LLM calls)
# ---------------------------------------------------------------------------

def test_chat_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = client.post("/chat", json={"prompt": "Hello"})
    assert resp.status_code == 503
    assert "OPENAI_API_KEY" in resp.json()["detail"]

def test_chat_missing_prompt_returns_422():
    resp = client.post("/chat", json={"model": "gpt-4o-mini"})
    assert resp.status_code == 422
