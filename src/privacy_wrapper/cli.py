"""
CLI entry point for wrapper-llm.

Commands are structural stubs — implementations are added in later phases.

Usage:
    wrapper-llm anonymize "John Smith called 555-1234"
    wrapper-llm serve --host 0.0.0.0 --port 8000
    wrapper-llm stats audit.jsonl
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import typer

app = typer.Typer(
    name="wrapper-llm",
    help="Privacy-preserving LLM wrapper with PII anonymization.",
    no_args_is_help=True,
)


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
