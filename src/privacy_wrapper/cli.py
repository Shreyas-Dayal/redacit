"""
CLI entry point for wrapper-llm.

Commands are structural stubs — implementations are added in later phases.

Usage:
    wrapper-llm anonymize "John Smith called 555-1234"
    wrapper-llm serve --host 0.0.0.0 --port 8000
    wrapper-llm stats audit.jsonl
"""

from __future__ import annotations

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
    raise NotImplementedError("serve command not yet implemented")


@app.command()
def stats(
    audit_log: str = typer.Argument(..., help="Path to audit JSONL file."),
    top: int = typer.Option(10, "--top", "-n", help="Show top N entity types."),
) -> None:
    """Print aggregated statistics from an audit log."""
    raise NotImplementedError("stats command not yet implemented")
