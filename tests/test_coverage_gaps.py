"""
Tests for previously uncovered functionality: streaming, session lifecycle,
audit log format, format handlers, edge cases, and module-level convenience
functions.
"""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

import pytest

from privacy_wrapper import anonymize, deanonymize
from privacy_wrapper.anonymizer import Anonymizer, AnonymizationResult
from privacy_wrapper.audit import AuditLogger
from privacy_wrapper.session import PrivacySession


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:

    def test_anonymize_returns_result(self):
        result = anonymize("Email alice@example.com")
        assert isinstance(result, AnonymizationResult)
        assert "alice@example.com" not in result.anonymized_text

    def test_deanonymize_restores_text(self):
        mapping = {"<EMAIL_ADDRESS_0>": "alice@example.com"}
        restored = deanonymize("Contact <EMAIL_ADDRESS_0>", mapping)
        assert restored == "Contact alice@example.com"

    def test_roundtrip(self):
        text = "Call John Smith at john@acme.com"
        result = anonymize(text)
        restored = deanonymize(result.anonymized_text, result.mapping)
        assert restored == text


# ---------------------------------------------------------------------------
# Edge cases for Anonymizer
# ---------------------------------------------------------------------------

class TestAnonymizerEdgeCases:

    @pytest.fixture(scope="class")
    def anon(self):
        return Anonymizer()

    def test_empty_string(self, anon):
        result = anon.anonymize("")
        assert result.anonymized_text == ""
        assert result.mapping == {}

    def test_whitespace_only(self, anon):
        result = anon.anonymize("   \n\t  ")
        assert result.anonymized_text == "   \n\t  "
        assert result.mapping == {}

    def test_unicode_text(self, anon):
        result = anon.anonymize("Café résumé naïve")
        assert isinstance(result.anonymized_text, str)

    def test_very_long_text(self, anon):
        text = "Hello world. " * 1000
        result = anon.anonymize(text)
        assert isinstance(result.anonymized_text, str)

    def test_deanonymize_with_empty_mapping(self, anon):
        text = "Nothing to restore"
        assert anon.deanonymize(text, {}) == text

    def test_deanonymize_with_missing_placeholder(self, anon):
        # Stale placeholder in text that isn't in the mapping
        text = "Hello <PERSON_99>"
        result = anon.deanonymize(text, {"<EMAIL_0>": "a@b.com"})
        assert "<PERSON_99>" in result  # left intact

    def test_overlapping_entities_resolved(self, anon):
        # Text where email contains a person name — should not double-detect
        result = anon.anonymize("john.smith@company.com")
        assert "john.smith@company.com" not in result.anonymized_text


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

class TestSessionLifecycle:

    def test_clear_resets_mapping(self):
        session = PrivacySession()
        session.update({"<PERSON_0>": "Alice"})
        assert len(session) == 1
        session.clear()
        assert len(session) == 0

    def test_first_value_wins(self):
        session = PrivacySession()
        session.update({"<PERSON_0>": "Alice"})
        session.update({"<PERSON_0>": "Bob"})
        assert session.mapping["<PERSON_0>"] == "Alice"

    def test_accumulates_across_updates(self):
        session = PrivacySession()
        session.update({"<PERSON_0>": "Alice"})
        session.update({"<EMAIL_0>": "alice@corp.com"})
        assert len(session) == 2

    def test_repr(self):
        session = PrivacySession()
        session.update({"<PERSON_0>": "Alice"})
        assert "1 entries" in repr(session)


# ---------------------------------------------------------------------------
# Audit log format
# ---------------------------------------------------------------------------

class TestAuditLogFormat:

    def test_log_writes_valid_jsonl(self):
        buf = io.StringIO()
        logger = AuditLogger(buf)
        logger.log("Hello Alice", {"<PERSON_0>": "Alice"}, provider="openai", model="gpt-4o")

        buf.seek(0)
        line = buf.readline()
        record = json.loads(line)
        assert "ts" in record
        assert "input_hash" in record
        assert record["entity_counts"] == {"PERSON": 1}
        assert record["total_redacted"] == 1
        assert record["provider"] == "openai"
        assert record["model"] == "gpt-4o"

    def test_log_never_contains_original_text(self):
        buf = io.StringIO()
        logger = AuditLogger(buf)
        logger.log("Secret text Alice", {"<PERSON_0>": "Alice"})

        buf.seek(0)
        raw = buf.read()
        assert "Alice" not in raw
        assert "Secret text" not in raw

    def test_multiple_logs_are_separate_lines(self):
        buf = io.StringIO()
        logger = AuditLogger(buf)
        logger.log("First", {})
        logger.log("Second", {"<PERSON_0>": "Bob"})

        buf.seek(0)
        lines = [l for l in buf.readlines() if l.strip()]
        assert len(lines) == 2
        assert json.loads(lines[0])["total_redacted"] == 0
        assert json.loads(lines[1])["total_redacted"] == 1

    def test_context_manager(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        with AuditLogger(path) as logger:
            logger.log("Test", {})
        # File should be closed — verify content was written
        assert path.read_text().strip() != ""

    def test_entity_counts_multiple_types(self):
        buf = io.StringIO()
        logger = AuditLogger(buf)
        logger.log(
            "Test",
            {"<PERSON_0>": "A", "<PERSON_1>": "B", "<EMAIL_ADDRESS_0>": "a@b.com"},
        )
        buf.seek(0)
        record = json.loads(buf.readline())
        assert record["entity_counts"]["PERSON"] == 2
        assert record["entity_counts"]["EMAIL_ADDRESS"] == 1


# ---------------------------------------------------------------------------
# Format handlers — CSV
# ---------------------------------------------------------------------------

class TestCsvAnonymizer:

    def test_anonymize_csv_file(self, tmp_path):
        from privacy_wrapper.formats.csv import CsvAnonymizer

        csv_content = "name,email,amount\nAlice,alice@corp.com,500\nBob,bob@test.com,300\n"
        csv_path = tmp_path / "test.csv"
        csv_path.write_text(csv_content)

        anon = CsvAnonymizer()
        results = list(anon.anonymize_file(csv_path))
        assert len(results) == 2

        row0 = results[0]
        assert row0.row_index == 0
        assert row0.original["name"] == "Alice"
        assert row0.original["email"] == "alice@corp.com"
        # Email should be anonymized
        assert "alice@corp.com" not in row0.anonymized["email"]

    def test_skip_field(self, tmp_path):
        from privacy_wrapper.formats.csv import CsvAnonymizer

        csv_path = tmp_path / "test.csv"
        csv_path.write_text("name,amount\nAlice,500\n")

        anon = CsvAnonymizer()
        results = list(anon.anonymize_file(csv_path, field_config={"amount": {"skip": True}}))
        assert results[0].anonymized["amount"] == "500"

    def test_flat_mapping_property(self, tmp_path):
        from privacy_wrapper.formats.csv import CsvAnonymizer

        csv_path = tmp_path / "test.csv"
        csv_path.write_text("email\nalice@corp.com\n")

        anon = CsvAnonymizer()
        results = list(anon.anonymize_file(csv_path))
        mapping = results[0].flat_mapping
        assert "alice@corp.com" in mapping.values()


# ---------------------------------------------------------------------------
# Format handlers — JSON
# ---------------------------------------------------------------------------

class TestJsonAnonymizer:

    def test_anonymize_json_file(self, tmp_path):
        from privacy_wrapper.formats.json_format import JsonAnonymizer

        records = [
            {"name": "Alice", "email": "alice@corp.com"},
            {"name": "Bob", "email": "bob@test.com"},
        ]
        json_path = tmp_path / "test.json"
        json_path.write_text(json.dumps(records))

        anon = JsonAnonymizer()
        results = list(anon.anonymize_file(json_path))
        assert len(results) == 2
        assert "alice@corp.com" not in json.dumps(results[0].anonymized)

    def test_nested_json(self, tmp_path):
        from privacy_wrapper.formats.json_format import JsonAnonymizer

        records = [{"person": {"name": "Alice", "contact": {"email": "alice@corp.com"}}}]
        json_path = tmp_path / "test.json"
        json_path.write_text(json.dumps(records))

        anon = JsonAnonymizer()
        results = list(anon.anonymize_file(json_path))
        flat = results[0].flat_mapping
        assert "alice@corp.com" in flat.values()

    def test_non_string_values_preserved(self, tmp_path):
        from privacy_wrapper.formats.json_format import JsonAnonymizer

        records = [{"name": "Alice", "age": 30, "active": True, "score": None}]
        json_path = tmp_path / "test.json"
        json_path.write_text(json.dumps(records))

        anon = JsonAnonymizer()
        results = list(anon.anonymize_file(json_path))
        r = results[0].anonymized
        assert r["age"] == 30
        assert r["active"] is True
        assert r["score"] is None

    def test_roundtrip_no_collision(self, tmp_path):
        from privacy_wrapper.formats.json_format import JsonAnonymizer
        from privacy_wrapper.formats._helpers import flatten

        records = [
            {
                "payer": {"name": "Sarah", "email": "sarah@corp.com"},
                "payee": {"name": "Bob", "email": "bob@test.com"},
            }
        ]
        json_path = tmp_path / "test.json"
        json_path.write_text(json.dumps(records))

        anon_obj = Anonymizer()
        json_anon = JsonAnonymizer(anonymizer=anon_obj)
        results = list(json_anon.anonymize_file(json_path))
        r = results[0]
        flat_orig = flatten(r.original)
        flat_anon = flatten(r.anonymized)

        for path_ in flat_orig:
            if isinstance(flat_orig[path_], str):
                restored = anon_obj.deanonymize(flat_anon[path_], r.flat_mapping)
                assert restored == flat_orig[path_], (
                    f"Roundtrip failed for '{path_}': {flat_orig[path_]!r} → {restored!r}"
                )


# ---------------------------------------------------------------------------
# Streaming (BaseLLMClient)
# ---------------------------------------------------------------------------

class TestStreaming:

    def test_stream_yields_deanonymized_text(self):
        from privacy_wrapper.client.base import BaseLLMClient

        class EchoClient(BaseLLMClient):
            def _call(self, prompt, system):
                return prompt

        client = EchoClient()
        chunks = list(client.stream("Email alice@example.com"))
        assert len(chunks) == 1
        assert "alice@example.com" in chunks[0]

    def test_stream_with_session(self):
        from privacy_wrapper.client.base import BaseLLMClient

        class EchoClient(BaseLLMClient):
            def _call(self, prompt, system):
                return prompt

        session = PrivacySession()
        client = EchoClient(session=session)
        list(client.stream("My name is Alice Jones"))
        assert len(session) > 0

    def test_stream_multi_chunk(self):
        from privacy_wrapper.client.base import BaseLLMClient

        class ChunkyClient(BaseLLMClient):
            def _call(self, prompt, system):
                return prompt

            def _stream_raw(self, prompt, system):
                # Split into character-level chunks
                for char in prompt:
                    yield char

        client = ChunkyClient()
        chunks = list(client.stream("Email alice@example.com"))
        assert len(chunks) == 1
        # Even with character-level chunking, the final output is deanonymized
        assert "alice@example.com" in chunks[0]
