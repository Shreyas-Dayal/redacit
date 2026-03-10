"""
Core anonymization layer using Microsoft Presidio (in-process, no Docker).

Flow:
  text → analyze (detect PII spans) → anonymize (replace with placeholders)
  → returns anonymized text + mapping for later restoration
"""

from dataclasses import dataclass, field
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

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
        self._anonymizer = AnonymizerEngine()

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

        # Build per-entity placeholder operators
        # Use a counter so duplicate entity types get unique tags
        operators: dict[str, OperatorConfig] = {}
        counters: dict[str, int] = {}
        mapping: dict[str, str] = {}

        for hit in hits:
            entity = hit.entity_type
            idx = counters.get(entity, 0)
            counters[entity] = idx + 1
            placeholder = f"<{entity}_{idx}>"
            original = text[hit.start:hit.end]
            mapping[placeholder] = original
            operators[entity] = OperatorConfig("replace", {"new_value": placeholder})

        result = self._anonymizer.anonymize(
            text=text,
            analyzer_results=hits,
            operators=operators,
        )

        return AnonymizationResult(
            anonymized_text=result.text,
            mapping=mapping,
        )

    def deanonymize(self, text: str, mapping: dict[str, str]) -> str:
        """Replace placeholders in an LLM response with the original values."""
        for placeholder, original in mapping.items():
            text = text.replace(placeholder, original)
        return text
