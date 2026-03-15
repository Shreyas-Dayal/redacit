"""
FastAPI server skeleton for wrapper-llm.

All endpoints return {"status": "not_implemented"} until Phase 4 implementation.

Start with:
    wrapper-llm serve
    # or directly:
    uvicorn privacy_wrapper.server:app --reload
"""

from __future__ import annotations

try:
    from fastapi import FastAPI
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "FastAPI is required to run the server. "
        "Install with: uv add 'wrapper-llm[server]'"
    ) from exc

app = FastAPI(
    title="wrapper-llm",
    description="Privacy-preserving LLM proxy with PII anonymization.",
    version="0.1.0",
)

_NOT_IMPLEMENTED = {"status": "not_implemented"}


@app.get("/health")
async def health() -> dict:
    """Liveness check."""
    return {"status": "ok"}


@app.post("/anonymize")
async def anonymize(body: dict) -> dict:
    """Anonymize PII in the provided text."""
    return _NOT_IMPLEMENTED


@app.post("/deanonymize")
async def deanonymize(body: dict) -> dict:
    """Restore original values from an anonymized text + mapping."""
    return _NOT_IMPLEMENTED


@app.post("/chat")
async def chat(body: dict) -> dict:
    """Proxy a chat completion request with automatic PII anonymization."""
    return _NOT_IMPLEMENTED
