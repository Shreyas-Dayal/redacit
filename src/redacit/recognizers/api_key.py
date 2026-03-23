from presidio_analyzer import Pattern, PatternRecognizer


class ApiKeyRecognizer(PatternRecognizer):
    """
    Detects API keys, tokens, and secrets in text.

    Covers several common formats:
      - OpenAI-style:    sk-<alphanum 20+>
      - Anthropic-style: sk-ant-<alphanum/dash/underscore 80+>
      - Generic prefix:  (sk|pk|api|secret|token|key)-<alphanum 16+>
      - Bearer tokens:   Bearer <alphanum/dash/underscore/dot 16+>
      - Hex secrets:     [0-9a-f]{32,}  (MD5/SHA-length hex strings)

    All patterns carry a high base score (0.8–0.9) because the prefixes
    are strong signals on their own without needing context words.
    """

    PATTERNS = [
        # Anthropic — must come before generic sk- pattern (it's more specific)
        Pattern(
            name="anthropic_api_key",
            regex=r"\bsk-ant-[A-Za-z0-9\-_]{80,}\b",
            score=0.95,
        ),
        # OpenAI-style: sk-proj-... or plain sk-...
        Pattern(
            name="openai_api_key",
            regex=r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}\b",
            score=0.9,
        ),
        # Generic prefixed secrets: pk-, api-, token-, secret-, key-
        Pattern(
            name="generic_api_key",
            regex=r"\b(?:pk|api|token|secret|key)[-_][A-Za-z0-9\-_]{16,}\b",
            score=0.8,
        ),
        # Bearer token in Authorization header or prose
        Pattern(
            name="bearer_token",
            regex=r"\bBearer\s+[A-Za-z0-9\-_.~+/]{16,}={0,2}\b",
            score=0.85,
        ),
        # Hex-encoded secrets (MD5=32, SHA1=40, SHA256=64 chars)
        Pattern(
            name="hex_secret",
            regex=r"\b[0-9a-fA-F]{32,64}\b",
            score=0.4,  # low alone; needs context
        ),
    ]

    CONTEXT = [
        "api key", "api_key", "apikey", "secret", "token", "credential",
        "authorization", "auth", "authenticate", "access key", "private key",
        "bearer", "password", "passwd",
    ]

    def __init__(self):
        super().__init__(
            supported_entity="API_KEY",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="en",
        )
