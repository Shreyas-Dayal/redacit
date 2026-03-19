"""
Core anonymization layer using Microsoft Presidio (in-process, no Docker).

Flow:
  text → analyze (detect PII spans) → anonymize (replace with placeholders)
  → returns anonymized text + mapping for later restoration
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import spacy
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider, SpacyNlpEngine
from presidio_analyzer.recognizer_result import RecognizerResult

from ._types import ModelNotFoundError
from .recognizers import build_custom_recognizers

_log = logging.getLogger(__name__)

_MODEL_CHAIN = ["en_core_web_lg", "en_core_web_md", "en_core_web_sm"]

DEFAULT_ENTITIES = [
    # Built-in Presidio entities
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
    "IP_ADDRESS",
    "LOCATION",
    "ORGANIZATION",
    "DATE_TIME",
    "URL",
    "IBAN_CODE",
    "US_PASSPORT",
    "US_DRIVER_LICENSE",
    # Custom entities
    "US_BANK_ACCOUNT",
    "US_ROUTING_NUMBER",
    "EIN",
    "API_KEY",
]


@dataclass
class AnonymizationResult:
    anonymized_text: str
    # placeholder → original value, used to restore the LLM response
    mapping: dict[str, str] = field(default_factory=dict)


def _resolve_overlaps(hits: list[RecognizerResult]) -> list[RecognizerResult]:
    """
    When two detected spans overlap, keep the one with the higher confidence
    score. Ties are broken by preferring the longer (wider) span.
    Runs in O(n log n).
    """
    # Highest score first; on equal score prefer the wider span
    ranked = sorted(hits, key=lambda h: (h.score, h.end - h.start), reverse=True)
    kept: list[RecognizerResult] = []
    for candidate in ranked:
        overlaps = any(
            candidate.start < kept_hit.end and candidate.end > kept_hit.start
            for kept_hit in kept
        )
        if not overlaps:
            kept.append(candidate)
    return kept


class _LoadedSpacyNlpEngine(SpacyNlpEngine):
    """SpacyNlpEngine that wraps an already-loaded spaCy Language object."""

    def __init__(self, loaded_model: spacy.language.Language) -> None:
        super().__init__()
        self.nlp = {"en": loaded_model}


def _build_nlp_engine(model: str | None, language: str) -> SpacyNlpEngine:
    """Build the NLP engine based on the requested model.

    ``"auto"`` (default) tries installed models in size order and falls
    back to ``spacy.blank()`` if none are found — giving regex-only
    detection with zero download overhead.

    Named models are created via ``NlpEngineProvider`` so that Presidio's
    default ``NerModelConfiguration`` (including ``labels_to_ignore``) is
    preserved exactly as it would be with a bare ``AnalyzerEngine()``.
    """
    if model is None or model == "none":
        _log.info("NLP model disabled — using regex-only detection")
        return _LoadedSpacyNlpEngine(spacy.blank(language))

    if model == "auto":
        for name in _MODEL_CHAIN:
            if spacy.util.is_package(name):
                _log.info("Using NLP model: %s", name)
                return _provider_engine(name, language)
        _log.warning(
            "No spaCy NER model found — PERSON, LOCATION, and ORGANIZATION "
            "detection is disabled. Install a model with: "
            "pip install 'wrapper-llm[model-sm]'"
        )
        return _LoadedSpacyNlpEngine(spacy.blank(language))

    # Explicit model name
    if not spacy.util.is_package(model):
        raise ModelNotFoundError(
            f"spaCy model {model!r} is not installed. "
            f"Install with: python -m spacy download {model}"
        )
    _log.info("Using NLP model: %s", model)
    return _provider_engine(model, language)


def _provider_engine(model_name: str, language: str) -> SpacyNlpEngine:
    """Create a SpacyNlpEngine via NlpEngineProvider with Presidio's defaults.

    The ``ner_model_configuration`` is passed explicitly because
    ``NlpEngineProvider`` with a dict config does not apply the same
    defaults as the bare ``AnalyzerEngine()`` constructor (notably
    ``labels_to_ignore``).
    """
    config = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": language, "model_name": model_name}],
        "ner_model_configuration": {
            "model_to_presidio_entity_mapping": {
                "PER": "PERSON",
                "PERSON": "PERSON",
                "NORP": "NRP",
                "FAC": "LOCATION",
                "LOC": "LOCATION",
                "GPE": "LOCATION",
                "LOCATION": "LOCATION",
                "ORG": "ORGANIZATION",
                "ORGANIZATION": "ORGANIZATION",
                "DATE": "DATE_TIME",
                "TIME": "DATE_TIME",
            },
            "low_confidence_score_multiplier": 0.4,
            "low_score_entity_names": [],
            "labels_to_ignore": [
                "ORGANIZATION",
                "CARDINAL",
                "EVENT",
                "LANGUAGE",
                "LAW",
                "MONEY",
                "ORDINAL",
                "PERCENT",
                "PRODUCT",
                "QUANTITY",
                "WORK_OF_ART",
            ],
        },
    }
    return NlpEngineProvider(nlp_configuration=config).create_engine()


_NO_VALUE = "___UNSET___"

_cached_project_config: dict | None = None


def _load_project_config() -> dict:
    """Load ``[tool.wrapper-llm]`` from ``pyproject.toml`` if it exists.

    The result is cached after the first call so repeated ``Anonymizer()``
    instantiations (e.g. in tests) don't re-read the file each time.

    .. note::

       The lookup uses the **current working directory** at the time of the
       first call.  In deployed applications where the CWD differs from the
       project root, the config will not be found — pass settings explicitly
       via constructor arguments or :func:`privacy_wrapper.configure` instead.
    """
    global _cached_project_config
    if _cached_project_config is not None:
        return _cached_project_config

    path = Path("pyproject.toml")
    if not path.exists():
        _cached_project_config = {}
        return _cached_project_config
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        _cached_project_config = data.get("tool", {}).get("wrapper-llm", {})
    except Exception:
        _cached_project_config = {}
    return _cached_project_config


def reset_config_cache() -> None:
    """Clear the cached project config so it is re-read on next use.

    Primarily useful for tests that write a temporary ``pyproject.toml``
    and need ``Anonymizer()`` to pick up the new values.
    """
    global _cached_project_config
    _cached_project_config = None


class Anonymizer:
    def __init__(
        self,
        entities: list[str] | None = None,
        score_threshold: float | None = None,
        language: str | None = None,
        model: str = _NO_VALUE,
    ):
        cfg = _load_project_config()

        self.entities = entities or cfg.get("entities", DEFAULT_ENTITIES)
        self.score_threshold = score_threshold if score_threshold is not None else cfg.get("score_threshold", 0.4)
        self.language = language or cfg.get("language", "en")

        resolved_model = model if model != _NO_VALUE else cfg.get("model", "auto")
        nlp_engine = _build_nlp_engine(resolved_model, self.language)
        self._analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            supported_languages=[self.language],
        )
        for recognizer in build_custom_recognizers():
            self._analyzer.registry.add_recognizer(recognizer)

    def anonymize(
        self,
        text: str,
        entities: list[str] | None = None,
        score_threshold: float | None = None,
    ) -> AnonymizationResult:
        """
        Detect and replace PII in text. Returns anonymized text and a restore map.

        entities:        override the instance-level entity list for this call only.
        score_threshold: override the instance-level threshold for this call only.
                         Useful when the caller already knows the field type (e.g.
                         a CSV column explicitly declared as US_BANK_ACCOUNT) and
                         wants to lower the bar without surrounding context words.
        """
        hits = self._analyzer.analyze(
            text=text,
            entities=entities if entities is not None else self.entities,
            language=self.language,
            score_threshold=score_threshold if score_threshold is not None else self.score_threshold,
        )

        if not hits:
            return AnonymizationResult(anonymized_text=text)

        # Drop lower-confidence spans that overlap with a higher-confidence one
        # (e.g. URL sub-spans inside a detected EMAIL_ADDRESS).
        hits = _resolve_overlaps(hits)

        # Assign unique placeholders in left-to-right reading order so that
        # PERSON_0 always refers to the first person mentioned, PERSON_1 the
        # second, etc. — regardless of how many of the same entity type appear.
        hits_by_position = sorted(hits, key=lambda h: h.start)
        counters: dict[str, int] = {}
        span_to_placeholder: dict[tuple[int, int], str] = {}
        mapping: dict[str, str] = {}

        for hit in hits_by_position:
            idx = counters.get(hit.entity_type, 0)
            counters[hit.entity_type] = idx + 1
            placeholder = f"<{hit.entity_type}_{idx}>"
            span_to_placeholder[(hit.start, hit.end)] = placeholder
            mapping[placeholder] = text[hit.start:hit.end]

        # Replace spans right-to-left so earlier offsets stay valid as we go.
        result_text = text
        for hit in sorted(hits, key=lambda h: h.start, reverse=True):
            placeholder = span_to_placeholder[(hit.start, hit.end)]
            result_text = result_text[:hit.start] + placeholder + result_text[hit.end:]

        return AnonymizationResult(anonymized_text=result_text, mapping=mapping)

    def __repr__(self) -> str:
        return (
            f"Anonymizer(entities={len(self.entities)}, "
            f"score_threshold={self.score_threshold})"
        )

    def deanonymize(self, text: str, mapping: dict[str, str]) -> str:
        """Replace placeholders in an LLM response with the original values."""
        for placeholder, original in mapping.items():
            text = text.replace(placeholder, original)
        return text
