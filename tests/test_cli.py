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
        assert cfg["model"] == "en_core_web_md"
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

    def test_examples_generated_for_openai(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["init", "--yes", "--provider", "openai", "--no-install"],
        )
        assert result.exit_code == 0
        assert (tmp_path / "examples" / "01_basic_usage.py").exists()
        assert (tmp_path / "examples" / "02_query_api.py").exists()
        assert (tmp_path / "examples" / "03_session.py").exists()
        assert (tmp_path / "examples" / "04_audit_logging.py").exists()

        basic = (tmp_path / "examples" / "01_basic_usage.py").read_text()
        assert "PrivacyClient(OpenAI())" in basic

    def test_examples_generated_for_anthropic(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["init", "--yes", "--provider", "anthropic", "--no-install"],
        )
        assert result.exit_code == 0
        basic = (tmp_path / "examples" / "01_basic_usage.py").read_text()
        assert "PrivacyClient(Anthropic())" in basic

        session = (tmp_path / "examples" / "03_session.py").read_text()
        assert "PrivacySession" in session

    def test_provider_none_generates_basic_only(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["init", "--yes", "--provider", "none", "--no-install"],
        )
        assert result.exit_code == 0
        assert (tmp_path / "examples" / "01_basic_usage.py").exists()
        # No query/session/audit examples for "none" provider
        assert not (tmp_path / "examples" / "02_query_api.py").exists()

    def test_examples_summary_printed(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["init", "--yes", "--no-install"],
        )
        assert result.exit_code == 0
        assert "Examples generated:" in result.output
        assert "01_basic_usage.py" in result.output


# ---------------------------------------------------------------------------
# init --agent (AI agent instructions file)
# ---------------------------------------------------------------------------

class TestInitAgentFile:

    def test_claude_md_generated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["init", "--yes", "--agent", "claude", "--no-install"],
        )
        assert result.exit_code == 0
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "wrapper-llm" in content
        assert "PrivacyClient" in content
        assert "Never bypass" in content

    def test_cursor_rules_generated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["init", "--yes", "--agent", "cursor", "--no-install"],
        )
        assert result.exit_code == 0
        assert (tmp_path / ".cursorrules").exists()

    def test_copilot_instructions_generated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["init", "--yes", "--agent", "copilot", "--no-install"],
        )
        assert result.exit_code == 0
        path = tmp_path / ".github" / "copilot-instructions.md"
        assert path.exists()
        assert "wrapper-llm" in path.read_text()

    def test_codex_agents_md_generated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["init", "--yes", "--agent", "codex", "--no-install"],
        )
        assert result.exit_code == 0
        agents_md = tmp_path / "AGENTS.md"
        assert agents_md.exists()
        assert "wrapper-llm" in agents_md.read_text()

    def test_antigravity_gemini_md_generated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["init", "--yes", "--agent", "antigravity", "--no-install"],
        )
        assert result.exit_code == 0
        gemini_md = tmp_path / "GEMINI.md"
        assert gemini_md.exists()
        assert "PrivacyClient" in gemini_md.read_text()

    def test_all_generates_all_five(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["init", "--yes", "--agent", "all", "--no-install"],
        )
        assert result.exit_code == 0
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / "AGENTS.md").exists()
        assert (tmp_path / "GEMINI.md").exists()
        assert (tmp_path / ".cursorrules").exists()
        assert (tmp_path / ".github" / "copilot-instructions.md").exists()

    def test_none_skips_agent_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["init", "--yes", "--agent", "none", "--no-install"],
        )
        assert result.exit_code == 0
        assert not (tmp_path / "CLAUDE.md").exists()
        assert not (tmp_path / ".cursorrules").exists()

    def test_content_reflects_provider(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(
            app, ["init", "--yes", "--agent", "claude", "--provider", "anthropic", "--no-install"],
        )
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "Anthropic" in content

    def test_content_reflects_regex_only_model(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(
            app, ["init", "--yes", "--agent", "claude", "--model", "none", "--no-install"],
        )
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "regex-only" in content

    def test_yes_flag_skips_agent_by_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init", "--yes", "--no-install"])
        assert not (tmp_path / "CLAUDE.md").exists()
