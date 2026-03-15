"""
FastAPI server for wrapper-llm.

Endpoints:
    GET  /health        — liveness check
    POST /anonymize     — detect and replace PII in text
    POST /deanonymize   — restore original values from anonymized text + mapping
    POST /chat          — proxy OpenAI chat with automatic PII anonymization

Start with:
    wrapper-llm serve
    # or directly:
    uvicorn privacy_wrapper.server:app --reload
"""

from __future__ import annotations

from functools import lru_cache

try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "FastAPI is required to run the server. "
        "Install with: uv add 'wrapper-llm[server]'"
    ) from exc

from .anonymizer import Anonymizer


@lru_cache(maxsize=1)
def _get_anonymizer() -> Anonymizer:
    """Lazily initialise a shared Anonymizer (Presidio startup is expensive)."""
    return Anonymizer()


app = FastAPI(
    title="wrapper-llm",
    description="Privacy-preserving LLM proxy with PII anonymization.",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AnonymizeRequest(BaseModel):
    text: str
    entities: list[str] | None = None
    score_threshold: float | None = None


class AnonymizeResponse(BaseModel):
    anonymized_text: str
    mapping: dict[str, str]


class DeanonymizeRequest(BaseModel):
    text: str
    mapping: dict[str, str]


class DeanonymizeResponse(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    """Liveness check."""
    return {"status": "ok"}


@app.post("/anonymize", response_model=AnonymizeResponse)
def anonymize_endpoint(body: AnonymizeRequest) -> AnonymizeResponse:
    """Anonymize PII in the provided text."""
    result = _get_anonymizer().anonymize(
        body.text,
        entities=body.entities,
        score_threshold=body.score_threshold,
    )
    return AnonymizeResponse(
        anonymized_text=result.anonymized_text,
        mapping=result.mapping,
    )


@app.post("/deanonymize", response_model=DeanonymizeResponse)
def deanonymize_endpoint(body: DeanonymizeRequest) -> DeanonymizeResponse:
    """Restore original values from an anonymized text + mapping."""
    text = _get_anonymizer().deanonymize(body.text, body.mapping)
    return DeanonymizeResponse(text=text)


@app.post("/chat")
async def chat(body: dict) -> dict:
    """Proxy a chat completion request with automatic PII anonymization."""
    return {"status": "not_implemented"}
