from presidio_analyzer import Pattern, PatternRecognizer


class UsRoutingNumberRecognizer(PatternRecognizer):
    """
    Detects US ABA routing transit numbers.

    Routing numbers are exactly 9 digits. The first two digits encode the
    Federal Reserve district: valid values are 01–12 (banks) and 21–32
    (thrift institutions). This constraint makes the pattern specific enough
    to carry a moderate base score (0.5), raised to 0.85 when context words
    are present.
    """

    PATTERNS = [
        Pattern(
            name="us_routing_number",
            # First two digits: 01-12 (banks) or 21-32 (thrifts)
            regex=r"\b(0[1-9]|1[0-2]|2[1-9]|3[0-2])\d{7}\b",
            score=0.5,
        ),
    ]

    CONTEXT = [
        "routing", "routing number", "routing no", "routing #",
        "aba", "aba number", "transit", "transit number",
    ]

    def __init__(self):
        super().__init__(
            supported_entity="US_ROUTING_NUMBER",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="en",
        )
