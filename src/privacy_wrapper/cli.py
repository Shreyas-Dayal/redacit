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
# init — interactive setup wizard
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

_MODEL_PACKAGES = {
    "en_core_web_sm": "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
    "en_core_web_md": "en-core-web-md @ https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl",
    "en_core_web_lg": "en-core-web-lg @ https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl",
}

_EXTRA_PACKAGES = {
    "server": ["fastapi>=0.111", "uvicorn[standard]>=0.29"],
    "litellm": ["litellm>=1.40"],
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


def _collect_packages(model: str, provider: str, server: bool) -> list[str]:
    """Return pip-installable package specs based on user selections."""
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
    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)
        if data.get("tool", {}).get("wrapper-llm"):
            typer.echo("  [tool.wrapper-llm] already exists — overwriting.")
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


@app.command()
def init(
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept all defaults, no prompts."),
    model: str = typer.Option(None, "--model", "-m", help="Model: none, sm, md, lg."),
    provider: str = typer.Option(None, "--provider", help="Provider: openai, anthropic, gemini, litellm, none."),
    server: bool = typer.Option(None, "--server/--no-server", help="Enable REST API server."),
    no_install: bool = typer.Option(False, "--no-install", help="Skip dependency installation."),
    agent: str = typer.Option(None, "--agent", help="AI agent file: claude, codex, antigravity, cursor, copilot, all, none."),
) -> None:
    """Interactive setup wizard for wrapper-llm."""
    from ._init_templates import (
        AGENT_CHOICES,
        build_agent_instructions,
        example_dropin,
        write_agent_files,
        write_examples,
    )

    typer.echo("\n  wrapper-llm setup\n")

    # -- Resolve each setting: CLI flag > interactive prompt > default ------

    if model is not None:
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

    config_model = resolved_model if resolved_model != "none" else "none"

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
            choices=list(AGENT_CHOICES.keys()),
            default=list(AGENT_CHOICES.keys())[-1],  # None
        ).ask()
        if label is None:
            raise typer.Abort()
        resolved_agent = AGENT_CHOICES[label]

    if resolved_agent != "none":
        agent_content = build_agent_instructions(
            resolved_provider, config_model, resolved_entities,
        )
        agent_files = write_agent_files(agent_content, resolved_agent)
        for f in agent_files:
            typer.echo(f"  Agent file written: {f}")

    # -- Install packages --------------------------------------------------

    packages = _collect_packages(resolved_model, resolved_provider, resolved_server)

    if packages and not no_install:
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

    files_written = write_examples(resolved_provider, Path("examples"))

    typer.echo("\n  Examples generated:")
    for f in files_written:
        typer.echo(f"    {f}")

    # -- Print quick-start preview -----------------------------------------

    dropin = example_dropin(resolved_provider)
    typer.echo("\n  Quick start:\n")
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
