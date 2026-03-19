import pytest
from privacy_wrapper.anonymizer import Anonymizer, AnonymizationResult


@pytest.fixture(scope="module")
def anon():
    # One shared instance — AnalyzerEngine is expensive to initialise
    return Anonymizer()


class TestAnonymize:

    def test_returns_anonymization_result(self, anon):
        result = anon.anonymize("Hello world")
        assert isinstance(result, AnonymizationResult)

    def test_no_pii_passes_through_unchanged(self, anon):
        text = "What is the boiling point of water?"
        result = anon.anonymize(text)
        assert result.anonymized_text == text
        assert result.mapping == {}

    def test_email_is_removed(self, anon):
        result = anon.anonymize("Send it to alice@example.com please.")
        assert "alice@example.com" not in result.anonymized_text
        assert len(result.mapping) >= 1

    def test_person_name_is_removed(self, anon):
        result = anon.anonymize("Schedule a call with John Smith tomorrow.")
        assert "John Smith" not in result.anonymized_text

    def test_ssn_is_removed(self, anon):
        # 123-45-6789 maps to digits 123456789 — Presidio's built-in deny list
        # treats it as a sample SSN and invalidates it. Use a realistic number.
        result = anon.anonymize("The SSN is 346-12-5678.")
        assert "346-12-5678" not in result.anonymized_text

    def test_credit_card_is_removed(self, anon):
        result = anon.anonymize("Charge card 4111-1111-1111-1111.")
        assert "4111-1111-1111-1111" not in result.anonymized_text

    def test_multiple_entities_all_replaced(self, anon):
        text = "Alice (alice@corp.com) called about card 4111-1111-1111-1111."
        result = anon.anonymize(text)
        assert "alice@corp.com" not in result.anonymized_text
        assert "4111-1111-1111-1111" not in result.anonymized_text

    def test_mapping_keys_are_placeholders(self, anon):
        result = anon.anonymize("Contact bob@test.com")
        for key in result.mapping:
            assert key.startswith("<") and key.endswith(">")

    def test_mapping_values_are_original_text(self, anon):
        result = anon.anonymize("Contact bob@test.com")
        assert "bob@test.com" in result.mapping.values()


class TestDeanonymize:

    def test_restores_original_value(self, anon):
        mapping = {"<EMAIL_ADDRESS_0>": "alice@corp.com"}
        text = "Confirmed: <EMAIL_ADDRESS_0> is registered."
        restored = anon.deanonymize(text, mapping)
        assert restored == "Confirmed: alice@corp.com is registered."

    def test_empty_mapping_is_noop(self, anon):
        text = "Nothing to restore here."
        assert anon.deanonymize(text, {}) == text

    def test_multiple_placeholders_restored(self, anon):
        mapping = {
            "<PERSON_0>": "Alice",
            "<EMAIL_ADDRESS_0>": "alice@corp.com",
        }
        text = "Sent to <PERSON_0> at <EMAIL_ADDRESS_0>."
        restored = anon.deanonymize(text, mapping)
        assert restored == "Sent to Alice at alice@corp.com."

    def test_unmatched_placeholder_left_intact(self, anon):
        mapping = {"<PERSON_0>": "Bob"}
        text = "Hello <PERSON_0> and <PERSON_1>"
        restored = anon.deanonymize(text, mapping)
        assert "Bob" in restored
        assert "<PERSON_1>" in restored


class TestRoundtrip:

    def test_full_roundtrip(self, anon):
        """Anonymize → simulate LLM echoing placeholder → deanonymize → original restored."""
        original = "Please email john.doe@company.com the report."
        result = anon.anonymize(original)

        # Simulate an LLM response that contains the placeholder
        fake_llm_reply = f"I have sent the report to {list(result.mapping.keys())[0]}."
        restored = anon.deanonymize(fake_llm_reply, result.mapping)

        assert "john.doe@company.com" in restored

    def test_clean_text_roundtrip(self, anon):
        text = "What is machine learning?"
        result = anon.anonymize(text)
        restored = anon.deanonymize(result.anonymized_text, result.mapping)
        assert restored == text


class TestModelSelection:

    def test_auto_finds_installed_model(self):
        anon = Anonymizer(model="auto")
        result = anon.anonymize("Call John Smith please.")
        assert "John Smith" not in result.anonymized_text

    def test_explicit_model(self):
        anon = Anonymizer(model="en_core_web_lg")
        result = anon.anonymize("Call John Smith please.")
        assert "John Smith" not in result.anonymized_text

    def test_regex_only_mode(self):
        anon = Anonymizer(model=None)
        # Regex entities still work
        result = anon.anonymize("Email alice@example.com")
        assert "alice@example.com" not in result.anonymized_text
        # NER entities are not detected (no model)
        result2 = anon.anonymize("Call John Smith please.")
        assert result2.anonymized_text == "Call John Smith please."

    def test_regex_only_detects_structured_pii(self):
        anon = Anonymizer(model=None)
        text = "SSN 346-12-5678, card 4111-1111-1111-1111, email bob@test.com"
        result = anon.anonymize(text)
        assert "346-12-5678" not in result.anonymized_text
        assert "4111-1111-1111-1111" not in result.anonymized_text
        assert "bob@test.com" not in result.anonymized_text
