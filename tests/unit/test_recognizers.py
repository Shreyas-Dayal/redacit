"""
Unit tests for custom recognizers.

Each recognizer is tested directly (no full Anonymizer pipeline) so failures
pinpoint exactly which pattern or context word is responsible.
"""

import pytest
from presidio_analyzer import AnalyzerEngine

from privacy_wrapper.recognizers import (
    ApiKeyRecognizer,
    EinRecognizer,
    UsBankAccountRecognizer,
    UsRoutingNumberRecognizer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _engine_with(*recognizers):
    """Return an AnalyzerEngine that only has the supplied recognizers."""
    engine = AnalyzerEngine(registry=[])  # empty registry
    for r in recognizers:
        engine.registry.add_recognizer(r)
    return engine


def _hits(engine, text, entity):
    return engine.analyze(text=text, language="en", entities=[entity], score_threshold=0.0)


# ---------------------------------------------------------------------------
# US Bank Account
# ---------------------------------------------------------------------------

class TestUsBankAccountRecognizer:
    @pytest.fixture(scope="class")
    def engine(self):
        return _engine_with(UsBankAccountRecognizer())

    def test_detected_with_context(self, engine):
        hits = _hits(engine, "Account number: 7823901645", "US_BANK_ACCOUNT")
        assert any(h.entity_type == "US_BANK_ACCOUNT" for h in hits)

    def test_detected_with_acct_abbreviation(self, engine):
        hits = _hits(engine, "Acct: 123456789012", "US_BANK_ACCOUNT")
        assert any(h.entity_type == "US_BANK_ACCOUNT" for h in hits)

    def test_detected_with_checking_context(self, engine):
        hits = _hits(engine, "Please deposit to my checking account 98765432100", "US_BANK_ACCOUNT")
        assert any(h.entity_type == "US_BANK_ACCOUNT" for h in hits)

    def test_not_detected_without_context(self, engine):
        # Bare 10-digit number with no context words should score below threshold
        hits = engine.analyze(text="Call 1234567890", language="en",
                              entities=["US_BANK_ACCOUNT"], score_threshold=0.4)
        assert not hits

    def test_too_short_not_detected(self, engine):
        hits = _hits(engine, "Account: 123", "US_BANK_ACCOUNT")
        assert not any(h.entity_type == "US_BANK_ACCOUNT" for h in hits)

    def test_too_long_not_detected(self, engine):
        hits = _hits(engine, "Account: 123456789012345678", "US_BANK_ACCOUNT")
        assert not any(h.entity_type == "US_BANK_ACCOUNT" for h in hits)

    def test_correct_span_extracted(self, engine):
        text = "Account number: 7823901645 on file"
        hits = _hits(engine, text, "US_BANK_ACCOUNT")
        bank_hits = [h for h in hits if h.entity_type == "US_BANK_ACCOUNT"]
        assert any(text[h.start:h.end] == "7823901645" for h in bank_hits)


# ---------------------------------------------------------------------------
# US Routing Number
# ---------------------------------------------------------------------------

class TestUsRoutingNumberRecognizer:
    @pytest.fixture(scope="class")
    def engine(self):
        return _engine_with(UsRoutingNumberRecognizer())

    def test_detected_with_context(self, engine):
        hits = _hits(engine, "Routing number: 021000021", "US_ROUTING_NUMBER")
        assert any(h.entity_type == "US_ROUTING_NUMBER" for h in hits)

    def test_detected_with_aba_context(self, engine):
        hits = _hits(engine, "ABA: 026009593", "US_ROUTING_NUMBER")
        assert any(h.entity_type == "US_ROUTING_NUMBER" for h in hits)

    def test_detected_with_transit_context(self, engine):
        hits = _hits(engine, "Transit number 011000138", "US_ROUTING_NUMBER")
        assert any(h.entity_type == "US_ROUTING_NUMBER" for h in hits)

    def test_invalid_first_digits_not_detected(self, engine):
        # First digits 99 are not a valid Federal Reserve district
        hits = _hits(engine, "Routing: 990000000", "US_ROUTING_NUMBER")
        assert not any(h.entity_type == "US_ROUTING_NUMBER" for h in hits)

    def test_correct_span_extracted(self, engine):
        text = "Routing no: 021000021 please"
        hits = _hits(engine, text, "US_ROUTING_NUMBER")
        routing_hits = [h for h in hits if h.entity_type == "US_ROUTING_NUMBER"]
        assert any(text[h.start:h.end] == "021000021" for h in routing_hits)


# ---------------------------------------------------------------------------
# EIN
# ---------------------------------------------------------------------------

class TestEinRecognizer:
    @pytest.fixture(scope="class")
    def engine(self):
        return _engine_with(EinRecognizer())

    def test_detected_with_ein_label(self, engine):
        hits = _hits(engine, "EIN: 12-3456789", "EIN")
        assert any(h.entity_type == "EIN" for h in hits)

    def test_detected_with_employer_context(self, engine):
        hits = _hits(engine, "Employer Identification Number: 98-7654321", "EIN")
        assert any(h.entity_type == "EIN" for h in hits)

    def test_detected_with_fein_label(self, engine):
        hits = _hits(engine, "FEIN 45-6789012", "EIN")
        assert any(h.entity_type == "EIN" for h in hits)

    def test_detected_with_federal_tax_context(self, engine):
        hits = _hits(engine, "Federal tax ID: 36-4567890", "EIN")
        assert any(h.entity_type == "EIN" for h in hits)

    def test_ssn_format_not_matched(self, engine):
        # SSN is XXX-XX-XXXX — different from EIN XX-XXXXXXX
        hits = _hits(engine, "EIN 346-12-5678", "EIN")
        assert not any(h.entity_type == "EIN" for h in hits)

    def test_correct_span_extracted(self, engine):
        text = "Employer EIN: 12-3456789 on record"
        hits = _hits(engine, text, "EIN")
        ein_hits = [h for h in hits if h.entity_type == "EIN"]
        assert any(text[h.start:h.end] == "12-3456789" for h in ein_hits)


# ---------------------------------------------------------------------------
# API Key
# ---------------------------------------------------------------------------

class TestApiKeyRecognizer:
    @pytest.fixture(scope="class")
    def engine(self):
        return _engine_with(ApiKeyRecognizer())

    def test_openai_key_detected(self, engine):
        hits = _hits(engine, "Use key sk-xK92mLpQr7vNtYeZ3481abc to call the API", "API_KEY")
        assert any(h.entity_type == "API_KEY" for h in hits)

    def test_openai_proj_key_detected(self, engine):
        hits = _hits(engine, "Key: sk-proj-AbCdEfGhIjKlMnOpQrStUvWx1234", "API_KEY")
        assert any(h.entity_type == "API_KEY" for h in hits)

    def test_generic_pk_key_detected(self, engine):
        hits = _hits(engine, "Public key: pk-live-xK92mLpQr7vNtYeZ", "API_KEY")
        assert any(h.entity_type == "API_KEY" for h in hits)

    def test_generic_token_detected(self, engine):
        hits = _hits(engine, "token-xK92mLpQr7vNtYeZ3481abcdef", "API_KEY")
        assert any(h.entity_type == "API_KEY" for h in hits)

    def test_bearer_token_detected(self, engine):
        hits = _hits(engine, "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "API_KEY")
        assert any(h.entity_type == "API_KEY" for h in hits)

    def test_hex_secret_with_context(self, engine):
        hits = _hits(engine, "secret: d41d8cd98f00b204e9800998ecf8427e", "API_KEY")
        assert any(h.entity_type == "API_KEY" for h in hits)

    def test_short_string_not_detected(self, engine):
        hits = _hits(engine, "sk-short", "API_KEY")
        assert not any(h.entity_type == "API_KEY" for h in hits)

    def test_correct_span_extracted(self, engine):
        key = "sk-xK92mLpQr7vNtYeZ3481abc"
        text = f"Use key {key} to call the API"
        hits = _hits(engine, text, "API_KEY")
        api_hits = [h for h in hits if h.entity_type == "API_KEY"]
        assert any(text[h.start:h.end] == key for h in api_hits)
