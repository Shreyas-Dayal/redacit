"""
Core anonymization layer using Microsoft Presidio (in-process, no Docker).

Flow:
  text → analyze (detect PII spans) → anonymize (replace with placeholders)
  → returns anonymized text + mapping for later restoration
"""

from dataclasses import dataclass, field
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.recognizer_result import RecognizerResult

DEFAULT_ENTITIES = [
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


class Anonymizer:
    def __init__(
        self,
        entities: list[str] = DEFAULT_ENTITIES,
        score_threshold: float = 0.4,
        language: str = "en",
    ):
        self.entities = entities
        self.score_threshold = score_threshold
        self.language = language
        self._analyzer = AnalyzerEngine()

    def anonymize(self, text: str) -> AnonymizationResult:
        """Detect and replace PII in text. Returns anonymized text and a restore map."""
        hits = self._analyzer.analyze(
            text=text,
            entities=self.entities,
            language=self.language,
            score_threshold=self.score_threshold,
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

    def deanonymize(self, text: str, mapping: dict[str, str]) -> str:
        """Replace placeholders in an LLM response with the original values."""
        for placeholder, original in mapping.items():
            text = text.replace(placeholder, original)
        return text
