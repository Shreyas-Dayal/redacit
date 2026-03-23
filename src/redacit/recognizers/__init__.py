from presidio_analyzer import PatternRecognizer

from .api_key import ApiKeyRecognizer
from .bank_account import UsBankAccountRecognizer
from .ein import EinRecognizer
from .routing_number import UsRoutingNumberRecognizer

__all__ = [
    "ApiKeyRecognizer",
    "UsBankAccountRecognizer",
    "EinRecognizer",
    "UsRoutingNumberRecognizer",
]


def build_custom_recognizers() -> list[PatternRecognizer]:
    """Return one instance of every custom recognizer."""
    return [
        UsBankAccountRecognizer(),
        UsRoutingNumberRecognizer(),
        EinRecognizer(),
        ApiKeyRecognizer(),
    ]
