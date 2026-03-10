"""
Data-driven tests using the sample prompts fixture.
Each sample is run through the full anonymize → deanonymize cycle.
"""

import pytest
from src.privacy_wrapper.anonymizer import Anonymizer
from tests.fixtures.sample_prompts import SAMPLES


@pytest.fixture(scope="module")
def anon():
    return Anonymizer()


clean_samples = [s for s in SAMPLES if s.get("expected_clean")]
pii_samples = [s for s in SAMPLES if s["sensitive"]]


class TestSampleLeakage:
    """Verify that known sensitive values never appear in anonymized output."""

    @pytest.mark.parametrize("sample", pii_samples, ids=[s["id"] for s in pii_samples])
    def test_sensitive_values_removed(self, anon, sample):
        result = anon.anonymize(sample["input"])
        for value in sample["sensitive"]:
            assert value not in result.anonymized_text, (
                f"[{sample['id']}] '{value}' leaked into anonymized output:\n"
                f"  {result.anonymized_text}"
            )


class TestSampleRoundtrip:
    """Verify that deanonymization fully restores the original text."""

    @pytest.mark.parametrize("sample", pii_samples, ids=[s["id"] for s in pii_samples])
    def test_roundtrip_restores_original(self, anon, sample):
        result = anon.anonymize(sample["input"])
        restored = anon.deanonymize(result.anonymized_text, result.mapping)
        assert restored == sample["input"], (
            f"[{sample['id']}] Roundtrip mismatch.\n"
            f"  Expected : {sample['input']}\n"
            f"  Got      : {restored}"
        )


class TestCleanPassthrough:
    """Verify that text without PII is returned unchanged with an empty mapping."""

    @pytest.mark.parametrize("sample", clean_samples, ids=[s["id"] for s in clean_samples])
    def test_clean_text_unchanged(self, anon, sample):
        result = anon.anonymize(sample["input"])
        assert result.anonymized_text == sample["input"], (
            f"[{sample['id']}] Clean text was unexpectedly modified:\n"
            f"  {result.anonymized_text}"
        )
        assert result.mapping == {}, (
            f"[{sample['id']}] Expected empty mapping for clean text, got: {result.mapping}"
        )
