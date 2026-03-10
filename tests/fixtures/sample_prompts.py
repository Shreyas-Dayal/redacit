"""
Sample prompts for testing the anonymization pipeline.

Each entry contains:
  - id:               unique label
  - input:            raw text with sensitive data
  - sensitive:        substrings that must NOT appear in the anonymized output
  - expected_clean:   True if no PII is expected (text should pass through unchanged)
"""

SAMPLES = [
    # --- Person + email ---
    {
        "id": "person_email_basic",
        "input": "Please send the invoice to Sarah Connor at sarah.connor@cyberdyne.com.",
        "sensitive": ["Sarah Connor", "sarah.connor@cyberdyne.com"],
    },

    # --- Multiple people + org ---
    {
        "id": "multi_person_org",
        "input": (
            "The meeting between David Park (Apex Ventures) and "
            "Linda Moore (Orion Labs) is confirmed for Thursday."
        ),
        "sensitive": ["David Park", "Linda Moore"],
    },

    # --- Credit card ---
    {
        "id": "credit_card",
        "input": "Charge the $4,200 balance to card number 4532-0151-1283-0366.",
        "sensitive": ["4532-0151-1283-0366"],
    },

    # --- SSN ---
    {
        "id": "ssn",
        "input": "The applicant's Social Security Number is 346-12-5678.",
        "sensitive": ["346-12-5678"],
    },

    # --- Phone number ---
    {
        "id": "phone_number",
        "input": "Call our support line at +1 (415) 555-0192 between 9am and 5pm.",
        "sensitive": ["+1 (415) 555-0192"],
    },

    # --- IP address ---
    {
        "id": "ip_address",
        "input": "The production database is reachable at 203.0.113.42 on port 5432.",
        "sensitive": ["203.0.113.42"],
    },

    # --- Mixed: name + email + phone ---
    # Note: US numbers are reliably detected. Non-US numbers (e.g. +44 UK mobile)
    # may fall below Presidio's confidence threshold without a country-specific
    # recognizer — flagged as a known gap for Phase 2.
    {
        "id": "mixed_contact_block",
        "input": (
            "Primary contact: James Whitfield\n"
            "Email: j.whitfield@globalfinance.io\n"
            "Mobile: +1 (415) 555-0187"
        ),
        "sensitive": ["James Whitfield", "j.whitfield@globalfinance.io", "+1 (415) 555-0187"],
    },

    # --- Healthcare / PHI flavour ---
    {
        "id": "healthcare_phi",
        "input": (
            "Patient: Maria Santos, DOB 03/14/1979, SSN 521-74-9038. "
            "Prescribed metformin 500mg twice daily."
        ),
        "sensitive": ["Maria Santos", "521-74-9038"],
    },

    # --- Legal / contract context ---
    {
        "id": "legal_contract",
        "input": (
            "This agreement is entered into by Robert Langdon (Passport: 938475610) "
            "and Acme Holdings Ltd, effective 1 January 2025."
        ),
        "sensitive": ["Robert Langdon", "938475610"],
    },

    # --- Internal credentials / secrets ---
    # Presidio has no built-in recognizer for API key patterns (sk-*, pk-*, etc.).
    # This sample is kept to document the gap; detection requires a custom
    # PatternRecognizer — planned for Phase 2.
    {
        "id": "api_key_leak",
        "input": (
            "Use the staging key sk-staging-xK92mLpQr7vNtYeZ3481 to authenticate. "
            "Do not share this outside the team."
        ),
        "sensitive": [],  # known gap: no built-in API key recognizer
        "expected_clean": True,
    },

    # --- No PII — should pass through completely unchanged ---
    {
        "id": "no_pii_science",
        "input": "Explain the difference between supervised and unsupervised learning.",
        "sensitive": [],
        "expected_clean": True,
    },
    {
        "id": "no_pii_code_question",
        "input": "What does the Python `yield` keyword do?",
        "sensitive": [],
        "expected_clean": True,
    },
]
