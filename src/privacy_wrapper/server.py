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

import os
from functools import lru_cache
from importlib.metadata import version as _pkg_version

try:
    from fastapi import FastAPI, HTTPException
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
    version=_pkg_version("wrapper-llm"),
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


class ChatRequest(BaseModel):
    prompt: str
    system: str | None = None
    model: str = "gpt-4o-mini"


class ChatResponse(BaseModel):
    response: str


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


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(body: ChatRequest) -> ChatResponse:
    """
    Proxy a chat completion through OpenAI with automatic PII anonymization.

    Requires OPENAI_API_KEY to be set in the server environment.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured on the server.",
        )

    from .client import OpenAIPrivacyClient

    client = OpenAIPrivacyClient(api_key=api_key, model=body.model, anonymizer=_get_anonymizer())
    response = client.chat(body.prompt, system=body.system)
    return ChatResponse(response=response)
