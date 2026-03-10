"""
Quick demo — runs without an API key to show anonymization in action.
To test with a real LLM call, set OPENAI_API_KEY in .env and use PrivacyClient.
"""

from src.privacy_wrapper.anonymizer import Anonymizer

anon = Anonymizer()

samples = [
    "Schedule a call with John Smith (john.smith@acme.com) about the Q3 financials.",
    "The applicant's SSN is 123-45-6789 and card number is 4111-1111-1111-1111.",
    "Server at 192.168.1.105 went down — contact bob@internal.org immediately.",
    "What is the capital of France?",  # No PII — should pass through unchanged
]

for text in samples:
    result = anon.anonymize(text)
    print(f"Original  : {text}")
    print(f"Anonymized: {result.anonymized_text}")
    print(f"Mapping   : {result.mapping}")
    restored = anon.deanonymize(result.anonymized_text, result.mapping)
    print(f"Restored  : {restored}")
    assert restored == text, "Roundtrip failed!"
    print()
