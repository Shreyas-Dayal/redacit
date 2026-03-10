from presidio_analyzer import Pattern, PatternRecognizer


class EinRecognizer(PatternRecognizer):
    """
    Detects US Employer Identification Numbers (EINs / FEINs).

    Format: XX-XXXXXXX  (2 digits, hyphen, 7 digits)

    This pattern overlaps with SSN (XXX-XX-XXXX) and dates (MM-DDDDDD would
    be unusual, but YY-NNNNNNN is possible). The score is kept moderate (0.4)
    without context and boosted when EIN-specific words are nearby. Presidio's
    US_SSN recognizer uses XXX-XX-XXXX, so the two patterns are disjoint.
    """

    PATTERNS = [
        Pattern(
            name="ein",
            regex=r"\b\d{2}-\d{7}\b",
            score=0.4,
        ),
    ]

    CONTEXT = [
        "ein", "fein", "employer identification", "employer identification number",
        "employer id", "tax id", "federal tax", "taxpayer id",
    ]

    def __init__(self):
        super().__init__(
            supported_entity="EIN",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="en",
        )
