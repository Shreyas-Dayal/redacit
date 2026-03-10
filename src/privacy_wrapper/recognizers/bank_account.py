from presidio_analyzer import Pattern, PatternRecognizer


class UsBankAccountRecognizer(PatternRecognizer):
    """
    Detects US bank account numbers (8–17 digits).

    Bank account numbers have no universal checksum or fixed format, so
    detection relies on context words. The base regex score is intentionally
    low (0.3) so that bare digit strings are not flagged; the score is
    boosted to 0.8 when a context word appears within the surrounding window.
    """

    PATTERNS = [
        Pattern(
            name="us_bank_account",
            regex=r"\b\d{8,17}\b",
            score=0.3,
        ),
    ]

    CONTEXT = [
        "account", "acct", "account number", "account no", "account #",
        "checking", "savings", "deposit", "bank account",
    ]

    def __init__(self):
        super().__init__(
            supported_entity="US_BANK_ACCOUNT",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="en",
        )
