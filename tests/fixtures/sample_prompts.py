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

    # --- API key ---
    {
        "id": "api_key_openai",
        "input": (
            "Use the staging key sk-xK92mLpQr7vNtYeZ3481abcdef to authenticate. "
            "Do not share this outside the team."
        ),
        "sensitive": ["sk-xK92mLpQr7vNtYeZ3481abcdef"],
    },

    # --- Bearer token ---
    {
        "id": "api_key_bearer",
        "input": "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "sensitive": ["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"],
    },

    # --- Bank account ---
    {
        "id": "bank_account",
        "input": "Please deposit funds to account number 7823901645 at First National.",
        "sensitive": ["7823901645"],
    },

    # --- Routing number ---
    {
        "id": "routing_number",
        "input": "Wire transfer routing number: 021000021",
        "sensitive": ["021000021"],
    },

    # --- EIN ---
    {
        "id": "ein",
        "input": "Employer Identification Number: 12-3456789",
        "sensitive": ["12-3456789"],
    },

    # -------------------------------------------------------------------------
    # Financial & structured content
    # -------------------------------------------------------------------------

    # --- Wire transfer instruction ---
    {
        "id": "wire_transfer",
        "input": (
            "Please initiate a wire transfer of $128,450.00 to:\n"
            "Beneficiary: Eleanor Voss\n"
            "Bank: First National Bank\n"
            "Account: 7823901645\n"
            "Routing: 021000021\n"
            "Reference: INV-2024-00892"
        ),
        # Account detected as US_BANK_ACCOUNT, Routing as US_ROUTING_NUMBER
        "sensitive": ["Eleanor Voss", "7823901645", "021000021"],
    },

    # --- IBAN / international payment ---
    {
        "id": "iban_payment",
        "input": (
            "Transfer EUR 42,000 to IBAN GB29NWBK60161331926819 "
            "held by Marcus Heller at Barclays London. "
            "BIC: NWBKGB2L."
        ),
        "sensitive": ["GB29NWBK60161331926819", "Marcus Heller"],
    },

    # --- Loan application (key-value block) ---
    {
        "id": "loan_application",
        "input": (
            "Applicant Name : Christine Okoro\n"
            "SSN            : 489-52-1736\n"
            "Annual Income  : $97,500\n"
            "Loan Amount    : $350,000\n"
            "Property Addr  : 412 Elmwood Drive, Austin, TX 78701\n"
            "Credit Score   : 748"
        ),
        "sensitive": ["Christine Okoro", "489-52-1736"],
    },

    # --- Invoice (tabular prose) ---
    {
        "id": "invoice",
        "input": (
            "INVOICE #INV-20240315\n"
            "Bill To : Thomas Reyes, treyes@reycorp.com\n"
            "Item    : Software licence (annual)   $12,000.00\n"
            "Item    : Support retainer (Q1)       $3,500.00\n"
            "Total   : $15,500.00\n"
            "Due     : 2024-04-15\n"
            "Card on file: 5555-5555-5555-4444"
        ),
        "sensitive": ["Thomas Reyes", "treyes@reycorp.com", "5555-5555-5555-4444"],
    },

    # --- Trading / brokerage note ---
    {
        "id": "brokerage_note",
        "input": (
            "Account holder: Patricia Lim (pat.lim@investco.com)\n"
            "Account no.   : 98-34521-7\n"
            "Trade date    : 2024-03-08\n"
            "Order         : BUY 500 shares AAPL @ $171.20\n"
            "Settlement    : T+2 via DTC participant 0352"
        ),
        "sensitive": ["Patricia Lim", "pat.lim@investco.com"],
    },

    # --- Tax record ---
    {
        "id": "tax_record",
        "input": (
            "Taxpayer: Gerald Hutchins\n"
            "TIN     : 346-88-2201\n"
            "Tax Year: 2023\n"
            "W-2 Wages            : $134,200\n"
            "Federal Tax Withheld : $28,600\n"
            "Employer EIN         : 12-3456789"
        ),
        # TIN detected as US_SSN, EIN now detected by custom EinRecognizer
        "sensitive": ["Gerald Hutchins", "346-88-2201", "12-3456789"],
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
