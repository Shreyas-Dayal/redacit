"""
CLI entry point for wrapper-llm.

Usage:
    wrapper-llm init
    wrapper-llm anonymize "John Smith called 555-1234"
    wrapper-llm serve --host 0.0.0.0 --port 8000
    wrapper-llm stats audit.jsonl
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(
    name="wrapper-llm",
    help="Privacy-preserving LLM wrapper with PII anonymization.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

_MODEL_CHOICES = {
    "None   (regex-only, no download)": "none",
    "en_core_web_sm  (11 MB, fast)": "en_core_web_sm",
    "en_core_web_md  (43 MB, recommended)": "en_core_web_md",
    "en_core_web_lg  (560 MB, max accuracy)": "en_core_web_lg",
}

_PROVIDER_CHOICES = {
    "OpenAI": "openai",
    "Anthropic": "anthropic",
    "Google Gemini": "gemini",
    "LiteLLM (multi-provider)": "litellm",
    "None (anonymization only)": "none",
}

_DEFAULT_ENTITIES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD",
    "US_SSN", "IP_ADDRESS", "LOCATION", "DATE_TIME", "URL",
    "IBAN_CODE", "US_BANK_ACCOUNT", "US_ROUTING_NUMBER", "EIN", "API_KEY",
]

def _example_dropin(provider: str) -> str:
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


_EXAMPLE_SIMPLIFIED = '''\
"""Simplified .query() API — works with any SDK client."""
from privacy_wrapper import PrivacyClient
{import_line}

client = PrivacyClient({client_init})

# .query() handles anonymize -> LLM call -> deanonymize in one step
reply = client.query("Summarise the contract for Alice Jones at alice@corp.com")
print(reply)
'''

_EXAMPLE_SESSION = '''\
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

_EXAMPLE_AUDIT = '''\
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

_PROVIDER_IMPORTS = {
    "openai":    ("from openai import OpenAI", "OpenAI()"),
    "anthropic": ("from anthropic import Anthropic", "Anthropic()"),
    "gemini":    ("from google import genai", "genai.Client()"),
    "litellm":   ("from privacy_wrapper import LiteLLMPrivacyClient", 'LiteLLMPrivacyClient("openai/gpt-4o-mini")'),
    "none":      ("", ""),
}


def _prompt_model() -> str:
    import questionary
    label = questionary.select(
        "Which spaCy model do you want?",
        choices=list(_MODEL_CHOICES.keys()),
        default=list(_MODEL_CHOICES.keys())[2],  # en_core_web_md
    ).ask()
    if label is None:
        raise typer.Abort()
    return _MODEL_CHOICES[label]


def _prompt_provider() -> str:
    import questionary
    label = questionary.select(
        "Which LLM provider will you use?",
        choices=list(_PROVIDER_CHOICES.keys()),
        default=list(_PROVIDER_CHOICES.keys())[0],
    ).ask()
    if label is None:
        raise typer.Abort()
    return _PROVIDER_CHOICES[label]


def _prompt_entities() -> list[str]:
    import questionary
    choices = [
        questionary.Choice(e, checked=(e in _DEFAULT_ENTITIES))
        for e in [
            "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD",
            "US_SSN", "IP_ADDRESS", "LOCATION", "ORGANIZATION",
            "DATE_TIME", "URL", "IBAN_CODE", "US_PASSPORT",
            "US_DRIVER_LICENSE", "US_BANK_ACCOUNT", "US_ROUTING_NUMBER",
            "EIN", "API_KEY",
        ]
    ]
    selected = questionary.checkbox(
        "Which PII entities should be detected?",
        choices=choices,
    ).ask()
    if selected is None:
        raise typer.Abort()
    return selected


_MODEL_PACKAGES = {
    "en_core_web_sm": "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
    "en_core_web_md": "en-core-web-md @ https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl",
    "en_core_web_lg": "en-core-web-lg @ https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl",
}

_EXTRA_PACKAGES = {
    "server": ["fastapi>=0.111", "uvicorn[standard]>=0.29"],
    "litellm": ["litellm>=1.40"],
}


def _collect_packages(model: str, provider: str, server: bool) -> list[str]:
    """Return the list of pip-installable package specs based on user selections."""
    packages: list[str] = []
    if model in _MODEL_PACKAGES:
        packages.append(_MODEL_PACKAGES[model])
    if server:
        packages.extend(_EXTRA_PACKAGES["server"])
    if provider == "litellm":
        packages.extend(_EXTRA_PACKAGES["litellm"])
    return packages


def _install_packages(packages: list[str]) -> None:
    """Install packages directly without re-installing wrapper-llm itself."""
    if not packages:
        return
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "pip", "install", *packages]
    else:
        cmd = [sys.executable, "-m", "pip", "install", *packages]
    typer.echo(f"  Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=False)


def _write_config(config: dict[str, Any], path: Path) -> None:
    """Append [tool.wrapper-llm] section to pyproject.toml."""
    # Check if section already exists
    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)
        if data.get("tool", {}).get("wrapper-llm"):
            typer.echo("  [tool.wrapper-llm] already exists — overwriting.")
            # Read file, remove old section, rewrite
            lines = path.read_text().splitlines(keepends=True)
            out: list[str] = []
            skip = False
            for line in lines:
                if line.strip() == "[tool.wrapper-llm]":
                    skip = True
                    continue
                if skip and line.strip().startswith("["):
                    skip = False
                if not skip:
                    out.append(line)
            path.write_text("".join(out))

    section = "\n[tool.wrapper-llm]\n"
    for key, value in config.items():
        if isinstance(value, list):
            section += f"{key} = [\n"
            for item in value:
                section += f'    "{item}",\n'
            section += "]\n"
        elif isinstance(value, bool):
            section += f"{key} = {'true' if value else 'false'}\n"
        elif isinstance(value, (int, float)):
            section += f"{key} = {value}\n"
        elif isinstance(value, str):
            section += f'{key} = "{value}"\n'

    with open(path, "a") as f:
        f.write(section)


# ---------------------------------------------------------------------------
# AI agent instructions file
# ---------------------------------------------------------------------------

_AGENT_CHOICES = {
    "CLAUDE.md       (Claude Code)": "claude",
    ".cursorrules    (Cursor)": "cursor",
    "copilot         (.github/copilot-instructions.md)": "copilot",
    "All of the above": "all",
    "None": "none",
}


def _build_agent_instructions(provider: str, model: str, entities: list[str]) -> str:
    """Build the AI agent instructions content based on project config."""

    import_line, client_init = _PROVIDER_IMPORTS.get(provider, _PROVIDER_IMPORTS["none"])

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

All text sent to an LLM is anonymized first (PII replaced with placeholders
like `<PERSON_0>`, `<EMAIL_ADDRESS_0>`). The LLM response is then deanonymized
(placeholders restored to original values). This happens transparently.

## Key rules for AI agents

1. **Never bypass the privacy wrapper.** All LLM calls must go through
   `PrivacyClient` or the module-level `anonymize()`/`deanonymize()` functions.
   Never call the LLM SDK directly for user-facing text.

2. **Do not log or print the `mapping` dict.** It contains the original PII
   values. Use `AuditLogger` for compliance-safe logging (metadata only).

3. **Use the drop-in proxy pattern** — wrap the SDK client, don't change call sites:
   ```python
   {import_line}
   from privacy_wrapper import PrivacyClient
   client = PrivacyClient({client_init})
   # All existing SDK call patterns work unchanged
   ```

4. **For multi-turn chat**, use `PrivacySession` to persist placeholder
   mappings across turns:
   ```python
   from privacy_wrapper import PrivacyClient, PrivacySession
   session = PrivacySession(max_size=500)
   client = PrivacyClient({client_init}, session=session)
   ```

5. **For compliance logging**, pass an `AuditLogger`:
   ```python
   from privacy_wrapper import AuditLogger
   with AuditLogger("audit.jsonl") as log:
       client = PrivacyClient({client_init}, audit_logger=log)
   ```

## API reference

| Class / Function | Purpose |
|---|---|
| `PrivacyClient(sdk_client)` | Drop-in proxy for any SDK (OpenAI, Anthropic, Gemini) |
| `client.query(prompt)` | Simplified API: anonymize, call LLM, deanonymize |
| `anonymize(text)` | Module-level anonymization (returns AnonymizationResult) |
| `deanonymize(text, mapping)` | Restore placeholders to original values |
| `Anonymizer(model=...)` | Core engine — `"auto"`, `"none"`, or explicit model name |
| `PrivacySession(max_size=N)` | Cross-turn placeholder persistence |
| `AuditLogger(path)` | Append-only JSONL log (metadata only, never raw text) |
| `CsvAnonymizer` / `JsonAnonymizer` | Structured data anonymization |
| `configure(model=...)` | Set module-level Anonymizer model before first use |

## Configuration

Project config is in `pyproject.toml` under `[tool.wrapper-llm]`.
Constructor arguments override config values.

## Common mistakes to avoid

- Do not call `OpenAI()` / `Anthropic()` / `genai.Client()` directly for user text
- Do not store `result.mapping` in logs, databases, or error messages
- Do not forget `session.clear()` between independent conversations
- Do not use `stream=True` in proxy mode if you need deanonymized output
  (use `.query()` or `OpenAIPrivacyClient.stream()` instead)
"""


def _write_agent_file(content: str, agent: str) -> list[str]:
    """Write the agent instructions file(s). Returns list of paths written."""
    written: list[str] = []

    targets: list[str] = []
    if agent in ("claude", "all"):
        targets.append("claude")
    if agent in ("cursor", "all"):
        targets.append("cursor")
    if agent in ("copilot", "all"):
        targets.append("copilot")

    for target in targets:
        if target == "claude":
            path = Path("CLAUDE.md")
        elif target == "cursor":
            path = Path(".cursorrules")
        elif target == "copilot":
            path = Path(".github") / "copilot-instructions.md"
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            continue

        path.write_text(content)
        written.append(str(path))

    return written


@app.command()
def init(
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept all defaults, no prompts."),
    model: str = typer.Option(None, "--model", "-m", help="Model: none, sm, md, lg."),
    provider: str = typer.Option(None, "--provider", help="Provider: openai, anthropic, gemini, litellm, none."),
    server: bool = typer.Option(None, "--server/--no-server", help="Enable REST API server."),
    no_install: bool = typer.Option(False, "--no-install", help="Skip dependency installation."),
    agent: str = typer.Option(None, "--agent", help="AI agent file: claude, cursor, copilot, all, none."),
) -> None:
    """Interactive setup wizard for wrapper-llm."""
    typer.echo("\n  wrapper-llm setup\n")

    # -- Resolve each setting: CLI flag > interactive prompt > default ------

    if model is not None:
        # Normalize short names
        model_map = {"sm": "en_core_web_sm", "md": "en_core_web_md", "lg": "en_core_web_lg", "none": "none"}
        resolved_model = model_map.get(model, model)
    elif yes:
        resolved_model = "en_core_web_md"
    else:
        resolved_model = _prompt_model()

    if provider is not None:
        resolved_provider = provider
    elif yes:
        resolved_provider = "openai"
    else:
        resolved_provider = _prompt_provider()

    if server is not None:
        resolved_server = server
    elif yes:
        resolved_server = False
    else:
        import questionary
        resolved_server = questionary.confirm("Enable the REST API server?", default=False).ask()
        if resolved_server is None:
            raise typer.Abort()

    if yes:
        resolved_entities = _DEFAULT_ENTITIES
        resolved_threshold = 0.4
    else:
        resolved_entities = _prompt_entities()
        import questionary
        threshold_str = questionary.text(
            "Detection confidence threshold (0.0-1.0):",
            default="0.4",
        ).ask()
        if threshold_str is None:
            raise typer.Abort()
        resolved_threshold = float(threshold_str)

    # -- Build config ------------------------------------------------------

    config_model = "auto" if resolved_model == "none" else resolved_model
    if resolved_model == "none":
        config_model = "none"

    config: dict[str, Any] = {
        "model": config_model,
        "score_threshold": resolved_threshold,
        "entities": resolved_entities,
    }

    # -- Write config to pyproject.toml ------------------------------------

    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        typer.echo("  No pyproject.toml found — creating one.")
        pyproject.write_text('[project]\nname = "my-project"\nversion = "0.1.0"\n')

    _write_config(config, pyproject)
    typer.echo(f"  Config written to {pyproject} [tool.wrapper-llm]")

    # -- AI agent instructions file ----------------------------------------

    if agent is not None:
        resolved_agent = agent
    elif yes:
        resolved_agent = "none"
    else:
        import questionary
        label = questionary.select(
            "Generate AI agent instructions file?",
            choices=list(_AGENT_CHOICES.keys()),
            default=list(_AGENT_CHOICES.keys())[-1],  # None
        ).ask()
        if label is None:
            raise typer.Abort()
        resolved_agent = _AGENT_CHOICES[label]

    if resolved_agent != "none":
        agent_content = _build_agent_instructions(
            resolved_provider, config_model, resolved_entities,
        )
        agent_files = _write_agent_file(agent_content, resolved_agent)
        for f in agent_files:
            typer.echo(f"  Agent file written: {f}")

    # -- Install packages --------------------------------------------------

    packages = _collect_packages(resolved_model, resolved_provider, resolved_server)

    if packages and not no_install:
        # Build a human-readable summary of what will be installed
        pkg_names = [p.split("@")[0].split(">")[0].strip() for p in packages]
        if yes:
            do_install = True
        else:
            import questionary
            do_install = questionary.confirm(
                f"Install dependencies ({', '.join(pkg_names)})?", default=True,
            ).ask()
            if do_install is None:
                do_install = False

        if do_install:
            _install_packages(packages)
    elif packages:
        typer.echo("\n  To install manually:")
        for pkg in packages:
            typer.echo(f"    pip install '{pkg}'")

    # -- Generate example files --------------------------------------------

    examples_dir = Path("examples")
    examples_dir.mkdir(exist_ok=True)

    import_line, client_init = _PROVIDER_IMPORTS.get(
        resolved_provider, _PROVIDER_IMPORTS["none"]
    )

    files_written: list[str] = []

    # 1. Drop-in proxy / basic usage
    dropin = _example_dropin(resolved_provider)
    (examples_dir / "01_basic_usage.py").write_text(dropin)
    files_written.append("examples/01_basic_usage.py")

    # 2. Simplified .query() API (skip for "none" provider)
    if resolved_provider != "none":
        simplified = _EXAMPLE_SIMPLIFIED.format(
            import_line=import_line, client_init=client_init,
        )
        (examples_dir / "02_query_api.py").write_text(simplified)
        files_written.append("examples/02_query_api.py")

    # 3. Multi-turn session (skip for "none" provider)
    if resolved_provider != "none":
        session_ex = _EXAMPLE_SESSION.format(
            import_line=import_line, client_init=client_init,
        )
        (examples_dir / "03_session.py").write_text(session_ex)
        files_written.append("examples/03_session.py")

    # 4. Audit logging (skip for "none" provider)
    if resolved_provider != "none":
        audit_ex = _EXAMPLE_AUDIT.format(
            import_line=import_line, client_init=client_init,
        )
        (examples_dir / "04_audit_logging.py").write_text(audit_ex)
        files_written.append("examples/04_audit_logging.py")

    # -- Print summary -----------------------------------------------------

    typer.echo("\n  Examples generated:")
    for f in files_written:
        typer.echo(f"    {f}")

    typer.echo("\n  Quick start:\n")
    # Show first 6 lines of the basic example as a preview
    preview = dropin.strip().splitlines()
    for line in preview[:8]:
        typer.echo(f"    {line}")
    if len(preview) > 8:
        typer.echo(f"    ...  (see {files_written[0]} for full example)")
    typer.echo()


# ---------------------------------------------------------------------------
# anonymize
# ---------------------------------------------------------------------------

@app.command()
def anonymize(
    text: str = typer.Argument(..., help="Text to anonymize."),
    entities: list[str] = typer.Option(
        None, "--entity", "-e", help="PII entity types to detect (repeatable)."
    ),
    threshold: float = typer.Option(
        0.35, "--threshold", "-t", help="Detection confidence threshold."
    ),
) -> None:
    """Anonymize PII in TEXT and print the result."""
    from privacy_wrapper.anonymizer import Anonymizer

    anon = Anonymizer()
    result = anon.anonymize(text, entities=entities or None, score_threshold=threshold)

    typer.echo(f"\nAnonymized:\n{result.anonymized_text}")

    if result.mapping:
        typer.echo("\nMapping:")
        for placeholder, original in result.mapping.items():
            typer.echo(f"  {placeholder:<32} {original}")
    else:
        typer.echo("\nNo PII detected.")


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port."),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (dev)."),
) -> None:
    """Start the anonymization API server."""
    missing = [pkg for pkg in ("fastapi", "uvicorn") if _missing(pkg)]
    if missing:
        typer.echo(
            f"{', '.join(missing)} is required to run the server.\n"
            "Install with: uv add 'wrapper-llm[server]'",
            err=True,
        )
        raise typer.Exit(1)

    import uvicorn  # noqa: PLC0415 — guarded above

    typer.echo(f"Starting wrapper-llm server on http://{host}:{port}")
    uvicorn.run("privacy_wrapper.server:app", host=host, port=port, reload=reload)


def _missing(pkg: str) -> bool:
    """Return True if *pkg* cannot be imported."""
    from importlib.util import find_spec
    return find_spec(pkg) is None


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

@app.command()
def stats(
    audit_log: str = typer.Argument(..., help="Path to audit JSONL file."),
    top: int = typer.Option(10, "--top", "-n", help="Show top N entity types."),
) -> None:
    """Print aggregated statistics from an audit log."""
    path = Path(audit_log)
    if not path.exists():
        typer.echo(f"File not found: {audit_log}", err=True)
        raise typer.Exit(1)

    counts: Counter[str] = Counter()
    total_records = 0
    total_redacted = 0

    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            total_records += 1
            total_redacted += record.get("total_redacted", 0)
            for entity, count in record.get("entity_counts", {}).items():
                counts[entity] += count

    typer.echo(f"\nAudit log : {audit_log}")
    typer.echo(f"Records   : {total_records}")
    typer.echo(f"Total PII : {total_redacted}")

    if counts:
        shown = min(top, len(counts))
        typer.echo(f"\nTop {shown} entity type{'s' if shown != 1 else ''}:")
        for entity, count in counts.most_common(top):
            typer.echo(f"  {entity:<30} {count}")
    else:
        typer.echo("\nNo PII events found.")
