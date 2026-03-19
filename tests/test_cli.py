"""CLI command tests using Typer's test runner."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from privacy_wrapper.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# anonymize command
# ---------------------------------------------------------------------------

class TestAnonymizeCommand:

    def test_pii_replaced(self):
        result = runner.invoke(app, ["anonymize", "Call John Smith at 555-867-5309."])
        assert result.exit_code == 0
        assert "Anonymized:" in result.output
        # PII must not appear in the anonymized text section (before "Mapping:")
        anonymized_section = result.output.split("Mapping:")[0]
        assert "John Smith" not in anonymized_section
        assert "555-867-5309" not in anonymized_section

    def test_no_pii_message(self):
        result = runner.invoke(app, ["anonymize", "What is the boiling point of water?"])
        assert result.exit_code == 0
        assert "No PII detected." in result.output

    def test_anonymized_text_printed(self):
        result = runner.invoke(app, ["anonymize", "Email alice@example.com"])
        assert result.exit_code == 0
        assert "Anonymized:" in result.output
        assert "alice@example.com" not in result.output.split("Mapping:")[0].split("Anonymized:")[1]

    def test_mapping_section_printed(self):
        result = runner.invoke(app, ["anonymize", "Email alice@example.com"])
        assert result.exit_code == 0
        assert "Mapping:" in result.output
        # original value appears in the mapping section
        assert "alice@example.com" in result.output

    def test_entity_filter_limits_detection(self):
        result = runner.invoke(
            app,
            ["anonymize", "John Smith at alice@example.com", "--entity", "PERSON"],
        )
        assert result.exit_code == 0
        # Email not in entity filter → not redacted
        assert "alice@example.com" in result.output

    def test_threshold_respected(self):
        # Very high threshold should suppress low-confidence detections
        result = runner.invoke(
            app,
            ["anonymize", "What is the boiling point of water?", "--threshold", "0.99"],
        )
        assert result.exit_code == 0
        assert "No PII detected." in result.output


# ---------------------------------------------------------------------------
# stats command
# ---------------------------------------------------------------------------

class TestStatsCommand:

    def _write_audit(self, path: Path, records: list[dict]) -> None:
        with path.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

    def test_basic_stats_output(self, tmp_path):
        records = [
            {
                "ts": "2024-01-01T00:00:00Z",
                "input_hash": "abc123",
                "entity_counts": {"PERSON": 2, "EMAIL_ADDRESS": 1},
                "total_redacted": 3,
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
            {
                "ts": "2024-01-01T00:00:01Z",
                "input_hash": "def456",
                "entity_counts": {"PERSON": 1},
                "total_redacted": 1,
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        ]
        path = tmp_path / "audit.jsonl"
        self._write_audit(path, records)

        result = runner.invoke(app, ["stats", str(path)])
        assert result.exit_code == 0
        assert "Records   : 2" in result.output
        assert "Total PII : 4" in result.output
        assert "PERSON" in result.output
        assert "EMAIL_ADDRESS" in result.output

    def test_file_not_found(self):
        result = runner.invoke(app, ["stats", "/nonexistent/audit.jsonl"])
        assert result.exit_code == 1

    def test_empty_log(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        result = runner.invoke(app, ["stats", str(path)])
        assert result.exit_code == 0
        assert "Records   : 0" in result.output
        assert "No PII events found." in result.output

    def test_top_n_limits_output(self, tmp_path):
        records = [
            {
                "ts": "x",
                "input_hash": "x",
                "entity_counts": {
                    "PERSON": 5,
                    "EMAIL_ADDRESS": 4,
                    "PHONE_NUMBER": 3,
                    "SSN": 2,
                },
                "total_redacted": 14,
                "provider": "x",
                "model": "x",
            }
        ]
        path = tmp_path / "audit.jsonl"
        self._write_audit(path, records)

        result = runner.invoke(app, ["stats", str(path), "--top", "2"])
        assert result.exit_code == 0
        assert "PERSON" in result.output
        assert "EMAIL_ADDRESS" in result.output
        # Ranked 3rd and 4th — excluded with --top 2
        assert "PHONE_NUMBER" not in result.output
        assert "SSN" not in result.output

    def test_malformed_lines_skipped(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        path.write_text(
            '{"entity_counts": {"PERSON": 1}, "total_redacted": 1, "ts": "x", "input_hash": "x", "provider": "x", "model": "x"}\n'
            "not valid json\n"
            '{"entity_counts": {"EMAIL_ADDRESS": 2}, "total_redacted": 2, "ts": "x", "input_hash": "x", "provider": "x", "model": "x"}\n'
        )
        result = runner.invoke(app, ["stats", str(path)])
        assert result.exit_code == 0
        assert "Records   : 2" in result.output
        assert "Total PII : 3" in result.output


# ---------------------------------------------------------------------------
# init command (non-interactive mode)
# ---------------------------------------------------------------------------

class TestInitCommand:

    def test_yes_flag_creates_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\nversion = "0.1.0"\n')

        result = runner.invoke(app, ["init", "--yes", "--no-install"])
        assert result.exit_code == 0
        assert "Config written" in result.output

        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        cfg = data["tool"]["wrapper-llm"]
        assert cfg["model"] == "en_core_web_sm"
        assert cfg["score_threshold"] == 0.4
        assert "EMAIL_ADDRESS" in cfg["entities"]

    def test_flags_override_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\n')

        result = runner.invoke(
            app, ["init", "--yes", "--model", "none", "--provider", "anthropic", "--no-install"],
        )
        assert result.exit_code == 0

        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        cfg = data["tool"]["wrapper-llm"]
        assert cfg["model"] == "none"

    def test_creates_pyproject_if_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["init", "--yes", "--no-install"])
        assert result.exit_code == 0

        pyproject = tmp_path / "pyproject.toml"
        assert pyproject.exists()
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        assert "wrapper-llm" in data.get("tool", {})

    def test_quick_start_snippet_shown(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["init", "--yes", "--provider", "anthropic", "--no-install"],
        )
        assert result.exit_code == 0
        assert "PrivacyClient(Anthropic())" in result.output

    def test_provider_none_shows_anonymize_snippet(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["init", "--yes", "--provider", "none", "--no-install"],
        )
        assert result.exit_code == 0
        assert "anonymize" in result.output
