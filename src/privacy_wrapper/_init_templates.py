"""
Templates and helpers for the ``wrapper-llm init`` wizard.

Separated from cli.py to keep the CLI module focused on command
definitions and argument parsing. This module owns:

- Provider-specific code example templates (drop-in, query, session, audit)
- AI agent instructions content (CLAUDE.md, AGENTS.md, etc.)
- File-writing logic for examples and agent files
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Provider metadata
# ---------------------------------------------------------------------------

PROVIDER_IMPORTS = {
    "openai":    ("from openai import OpenAI", "OpenAI()"),
    "anthropic": ("from anthropic import Anthropic", "Anthropic()"),
    "gemini":    ("from google import genai", "genai.Client()"),
    "litellm":   ("from privacy_wrapper import LiteLLMPrivacyClient", 'LiteLLMPrivacyClient("openai/gpt-4o-mini")'),
    "none":      ("", ""),
}

# ---------------------------------------------------------------------------
# Code example templates
# ---------------------------------------------------------------------------


def example_dropin(provider: str) -> str:
    """Generate a drop-in proxy example for the selected provider."""
    if provider == "openai":
        return '''\
"""Drop-in proxy — one line change to add privacy to existing OpenAI code."""
from openai import OpenAI
from privacy_wrapper import PrivacyClient

# Wrap your existing client — all call sites stay identical
client = PrivacyClient(OpenAI())

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "user", "content": "Summarise the contract for Alice Jones at alice@corp.com"}
    ],
)
# Alice Jones and alice@corp.com were anonymized before the API call
# and restored in the response automatically
print(response.choices[0].message.content)
'''
    if provider == "anthropic":
        return '''\
"""Drop-in proxy — one line change to add privacy to existing Anthropic code."""
from anthropic import Anthropic
from privacy_wrapper import PrivacyClient

client = PrivacyClient(Anthropic())

response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=256,
    messages=[
        {"role": "user", "content": "Summarise the contract for Alice Jones at alice@corp.com"}
    ],
)
print(response.content[0].text)
'''
    if provider == "gemini":
        return '''\
"""Drop-in proxy — one line change to add privacy to existing Gemini code."""
from google import genai
from privacy_wrapper import PrivacyClient

client = PrivacyClient(genai.Client())

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Summarise the contract for Alice Jones at alice@corp.com",
)
print(response.text)
'''
    if provider == "litellm":
        return '''\
"""Multi-provider client via LiteLLM — works with any LLM provider."""
from privacy_wrapper import LiteLLMPrivacyClient

# Change the model string to switch providers:
#   "openai/gpt-4o-mini", "anthropic/claude-sonnet-4-5-20250929",
#   "gemini/gemini-2.0-flash", "ollama/llama3"
client = LiteLLMPrivacyClient("openai/gpt-4o-mini")

reply = client.chat("Summarise the contract for Alice Jones at alice@corp.com")
print(reply)
'''
    # provider == "none" or unknown
    return '''\
"""Anonymize and deanonymize without calling an LLM."""
from privacy_wrapper import anonymize, deanonymize

text = "Email alice@corp.com, SSN 346-12-5678, card 4111-1111-1111-1111"

result = anonymize(text)
print("Anonymized:", result.anonymized_text)
print("Mapping:", result.mapping)

# After getting a response from your own LLM call:
# restored = deanonymize(llm_response, result.mapping)
'''


EXAMPLE_SIMPLIFIED = '''\
"""Simplified .query() API — works with any SDK client."""
from privacy_wrapper import PrivacyClient
{import_line}

client = PrivacyClient({client_init})

# .query() handles anonymize -> LLM call -> deanonymize in one step
reply = client.query("Summarise the contract for Alice Jones at alice@corp.com")
print(reply)
'''

EXAMPLE_SESSION = '''\
"""Multi-turn conversation with session persistence."""
from privacy_wrapper import PrivacyClient, PrivacySession
{import_line}

session = PrivacySession(max_size=500)
client = PrivacyClient({client_init}, session=session)

# Turn 1: PII is mapped and stored in the session
reply1 = client.query("My name is Alice Jones, email alice@corp.com")
print("Turn 1:", reply1)

# Turn 2: Placeholders from turn 1 are still resolvable
reply2 = client.query("What is my email?")
print("Turn 2:", reply2)

# New conversation — clear the session
session.clear()
'''

EXAMPLE_AUDIT = '''\
"""Audit logging — metadata-only compliance log (never stores raw text)."""
from privacy_wrapper import PrivacyClient, AuditLogger
{import_line}

with AuditLogger("privacy_audit.jsonl") as log:
    client = PrivacyClient({client_init}, audit_logger=log)
    reply = client.query("Wire $50,000 to account 7823901645 for Alice Jones")
    print(reply)

# Analyse the log:
#   wrapper-llm stats privacy_audit.jsonl
'''


# ---------------------------------------------------------------------------
# Example file generation
# ---------------------------------------------------------------------------

def write_examples(provider: str, target_dir: Path) -> list[str]:
    """Write example files into *target_dir*. Returns list of relative paths."""
    target_dir.mkdir(exist_ok=True)

    import_line, client_init = PROVIDER_IMPORTS.get(provider, PROVIDER_IMPORTS["none"])
    written: list[str] = []

    # 1. Drop-in / basic usage
    dropin = example_dropin(provider)
    (target_dir / "01_basic_usage.py").write_text(dropin)
    written.append(f"{target_dir}/01_basic_usage.py")

    # 2–4 only for providers with an LLM client
    if provider != "none":
        (target_dir / "02_query_api.py").write_text(
            EXAMPLE_SIMPLIFIED.format(import_line=import_line, client_init=client_init)
        )
        written.append(f"{target_dir}/02_query_api.py")

        (target_dir / "03_session.py").write_text(
            EXAMPLE_SESSION.format(import_line=import_line, client_init=client_init)
        )
        written.append(f"{target_dir}/03_session.py")

        (target_dir / "04_audit_logging.py").write_text(
            EXAMPLE_AUDIT.format(import_line=import_line, client_init=client_init)
        )
        written.append(f"{target_dir}/04_audit_logging.py")

    return written


# ---------------------------------------------------------------------------
# AI agent instructions
# ---------------------------------------------------------------------------

AGENT_CHOICES = {
    "CLAUDE.md       (Claude Code)": "claude",
    "AGENTS.md       (Codex / shared)": "codex",
    "GEMINI.md       (Antigravity)": "antigravity",
    ".cursorrules    (Cursor)": "cursor",
    "copilot         (.github/copilot-instructions.md)": "copilot",
    "All of the above": "all",
    "None": "none",
}

_AGENT_PATHS = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "antigravity": "GEMINI.md",
    "cursor": ".cursorrules",
    "copilot": ".github/copilot-instructions.md",
}


def build_agent_instructions(provider: str, model: str, entities: list[str]) -> str:
    """Build the AI agent instructions content based on project config."""

    import_line, client_init = PROVIDER_IMPORTS.get(provider, PROVIDER_IMPORTS["none"])

    model_note = (
        f"The project uses `{model}` for NER. "
        if model not in ("none", "auto")
        else "The project uses regex-only PII detection (no NLP model). "
    )

    entity_list = ", ".join(f"`{e}`" for e in entities[:8])
    if len(entities) > 8:
        entity_list += f", and {len(entities) - 8} more"

    return f"""\
# wrapper-llm Integration Guide

This project uses **wrapper-llm** for automatic PII anonymization in LLM calls.
{model_note}Detected entity types: {entity_list}.

## How wrapper-llm works

```
User text → Anonymizer (Presidio, in-process)
  → replaces PII with placeholders: <PERSON_0>, <EMAIL_ADDRESS_0>
  → records placeholder → original mapping
  → sends anonymized text to LLM
LLM response → Deanonymizer
  → restores placeholders to original values
  → returns clean response to app
```

Everything runs locally in-process. No external services, no Docker.

## Key rules for AI agents

1. **Never bypass the privacy wrapper.** All LLM calls must go through
   `PrivacyClient` or the module-level `anonymize()`/`deanonymize()` functions.
   Never call the LLM SDK directly for user-facing text.

2. **Do not log or print the `mapping` dict.** It contains the original PII
   values. Use `AuditLogger` for compliance-safe logging (metadata only).

3. **Do not store PII in variables longer than needed.** After anonymization,
   work with `result.anonymized_text` — the original text should not persist.

---

## Python integration examples

### Drop-in proxy (recommended — zero call-site changes)

```python
{import_line}
from privacy_wrapper import PrivacyClient

# One line change — wrap your existing client
client = PrivacyClient({client_init})

# All existing SDK call patterns work unchanged
# PII is anonymized before sending, restored in the response
```

### Simplified .query() API

```python
from privacy_wrapper import PrivacyClient
{import_line}

client = PrivacyClient({client_init})
reply = client.query("Summarise the contract for Alice Jones at alice@corp.com")
# Alice Jones and alice@corp.com never reach the LLM
print(reply)
```

### Low-level anonymize / deanonymize (no LLM)

```python
from privacy_wrapper import anonymize, deanonymize

result = anonymize("SSN: 346-12-5678, email: alice@corp.com")
print(result.anonymized_text)  # SSN: <US_SSN_0>, email: <EMAIL_ADDRESS_0>
print(result.mapping)          # {{'<US_SSN_0>': '346-12-5678', ...}}

# After your own LLM call:
restored = deanonymize(llm_response, result.mapping)
```

### Multi-turn session

```python
from privacy_wrapper import PrivacyClient, PrivacySession
{import_line}

session = PrivacySession(max_size=500)
client = PrivacyClient({client_init}, session=session)

client.query("My name is Alice Jones")      # <PERSON_0> → Alice stored
client.query("What is my name?")            # placeholder resolved across turns
session.clear()                             # reset between conversations
```

### Audit logging

```python
from privacy_wrapper import PrivacyClient, AuditLogger
{import_line}

with AuditLogger("privacy_audit.jsonl") as log:
    client = PrivacyClient({client_init}, audit_logger=log)
    client.query("Wire $50,000 to account 7823901645")

# Log contains metadata only — never raw text or PII values:
# {{"ts": "...", "input_hash": "a3f9...", "entity_counts": {{"US_BANK_ACCOUNT": 1}}, ...}}
```

### Structured data (CSV / JSON)

```python
from privacy_wrapper import CsvAnonymizer, JsonAnonymizer

# CSV — one result per row
for row in CsvAnonymizer().anonymize_file("customers.csv"):
    print(row.anonymized)      # dict with PII replaced per column
    print(row.flat_mapping)    # combined placeholder map

# JSON — one result per record (handles nested structures)
for rec in JsonAnonymizer().anonymize_file("records.json"):
    print(rec.anonymized)      # nested dict with PII replaced
```

### FastAPI / Django integration

```python
{import_line}
from privacy_wrapper import PrivacyClient

# Create once at startup / in dependency injection
client = PrivacyClient({client_init})

# Use in any route — all calls are privacy-aware automatically
@app.post("/chat")
def chat(body: dict):
    reply = client.query(body["message"])
    return {{"reply": reply}}
```

---

## CLI usage

```bash
# Quick anonymization check
wrapper-llm anonymize "John Smith at john@acme.com, SSN 346-12-5678"

# Filter to specific entity types
wrapper-llm anonymize "John Smith at john@acme.com" --entity PERSON --entity EMAIL_ADDRESS

# Adjust detection confidence
wrapper-llm anonymize "some text" --threshold 0.6

# Start the REST API server
wrapper-llm serve --host 0.0.0.0 --port 8000

# Analyse an audit log
wrapper-llm stats privacy_audit.jsonl --top 5
```

### REST API endpoints (when server is running)

```bash
# Anonymize text
curl -X POST http://localhost:8000/anonymize \\
  -H "Content-Type: application/json" \\
  -d '{{"text": "Email alice@corp.com"}}'

# Deanonymize
curl -X POST http://localhost:8000/deanonymize \\
  -H "Content-Type: application/json" \\
  -d '{{"text": "Email <EMAIL_ADDRESS_0>", "mapping": {{"<EMAIL_ADDRESS_0>": "alice@corp.com"}}}}'

# Chat proxy (requires OPENAI_API_KEY on server)
curl -X POST http://localhost:8000/chat \\
  -H "Content-Type: application/json" \\
  -d '{{"prompt": "Summarise this for Alice Jones"}}'

# Health check
curl http://localhost:8000/health

# OpenAPI docs
# http://localhost:8000/docs
```

---

## API reference

| Class / Function | Purpose |
|---|---|
| `PrivacyClient(sdk_client)` | Drop-in proxy for any SDK (OpenAI, Anthropic, Gemini) |
| `client.query(prompt)` | Simplified API: anonymize → call LLM → deanonymize |
| `anonymize(text)` | Module-level anonymization (returns `AnonymizationResult`) |
| `deanonymize(text, mapping)` | Restore placeholders to original values |
| `Anonymizer(model=...)` | Core engine — `"auto"`, `"none"`, or explicit model name |
| `PrivacySession(max_size=N)` | Cross-turn placeholder persistence with LRU eviction |
| `AuditLogger(path)` | Append-only JSONL log (metadata only, never raw text) |
| `CsvAnonymizer` | Row-by-row CSV anonymization with sidecar config |
| `JsonAnonymizer` | Record-by-record JSON anonymization (handles nesting) |
| `configure(model=...)` | Set module-level Anonymizer model before first use |
| `OpenAIPrivacyClient` | Simplified `.chat()` / `.stream()` API (OpenAI only) |
| `LiteLLMPrivacyClient(model)` | Multi-provider via LiteLLM (`"anthropic/claude-..."`) |

## Configuration

Project config is in `pyproject.toml` under `[tool.wrapper-llm]`:

```toml
[tool.wrapper-llm]
model = "{model}"
score_threshold = 0.4
entities = [...]
```

Constructor arguments override config values. Config values override defaults.

## Common mistakes to avoid

- Do not call `OpenAI()` / `Anthropic()` / `genai.Client()` directly for user text
- Do not store `result.mapping` in logs, databases, or error messages
- Do not forget `session.clear()` between independent conversations
- Do not use `stream=True` in proxy mode if you need deanonymized output
  (use `.query()` or `OpenAIPrivacyClient.stream()` instead)
- Do not hardcode entity types — use the configured defaults from `pyproject.toml`
"""


def write_agent_files(content: str, agent: str) -> list[str]:
    """Write agent instructions file(s). Returns list of paths written."""
    written: list[str] = []

    targets: list[str] = []
    if agent == "all":
        targets = list(_AGENT_PATHS.keys())
    elif agent in _AGENT_PATHS:
        targets = [agent]

    for target in targets:
        path = Path(_AGENT_PATHS[target])
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        written.append(str(path))

    return written
