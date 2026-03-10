"""
Quick demo — runs without an API key to show anonymization in action.
To test with a real LLM call, set OPENAI_API_KEY in .env and use PrivacyClient.
"""

from src.privacy_wrapper.anonymizer import Anonymizer

anon = Anonymizer()

SECTIONS = {
    "General PII": [
        "Schedule a call with John Smith (john.smith@acme.com) about the Q3 financials.",
        "The applicant's SSN is 346-12-5678 and card number is 4111-1111-1111-1111.",
        "Server at 192.168.1.105 went down — contact bob@internal.org immediately.",
        "What is the capital of France?",  # no PII — passes through unchanged
    ],

    "Financial & Structured": [
        # Wire transfer
        (
            "Please initiate a wire transfer of $128,450.00 to:\n"
            "Beneficiary: Eleanor Voss\n"
            "Bank: First National Bank\n"
            "Account: 7823901645\n"
            "Routing: 021000021\n"
            "Reference: INV-2024-00892"
        ),
        # IBAN / international payment
        (
            "Transfer EUR 42,000 to IBAN GB29NWBK60161331926819 "
            "held by Marcus Heller at Barclays London. BIC: NWBKGB2L."
        ),
        # Loan application block
        (
            "Applicant Name : Christine Okoro\n"
            "SSN            : 489-52-1736\n"
            "Annual Income  : $97,500\n"
            "Loan Amount    : $350,000\n"
            "Property Addr  : 412 Elmwood Drive, Austin, TX 78701\n"
            "Credit Score   : 748"
        ),
        # Invoice
        (
            "INVOICE #INV-20240315\n"
            "Bill To : Thomas Reyes, treyes@reycorp.com\n"
            "Item    : Software licence (annual)   $12,000.00\n"
            "Item    : Support retainer (Q1)       $3,500.00\n"
            "Total   : $15,500.00\n"
            "Due     : 2024-04-15\n"
            "Card on file: 5555-5555-5555-4444"
        ),
        # Brokerage note
        (
            "Account holder: Patricia Lim (pat.lim@investco.com)\n"
            "Account no.   : 98-34521-7\n"
            "Trade date    : 2024-03-08\n"
            "Order         : BUY 500 shares AAPL @ $171.20\n"
            "Settlement    : T+2 via DTC participant 0352"
        ),
        # Tax record
        (
            "Taxpayer: Gerald Hutchins\n"
            "TIN     : 346-88-2201\n"
            "Tax Year: 2023\n"
            "W-2 Wages            : $134,200\n"
            "Federal Tax Withheld : $28,600\n"
            "Employer EIN         : 12-3456789"
        ),
    ],
}


def run_section(title: str, samples: list[str]) -> None:
    width = 72
    print("=" * width)
    print(f"  {title}")
    print("=" * width)

    for text in samples:
        result = anon.anonymize(text)
        restored = anon.deanonymize(result.anonymized_text, result.mapping)

        print(f"\nOriginal:\n{text}")
        print(f"\nAnonymized:\n{result.anonymized_text}")
        print(f"\nMapping: {result.mapping}")
        print(f"\nRestored:\n{restored}")

        assert restored == text, f"Roundtrip failed for:\n{text}"
        print("-" * width)


for section_title, section_samples in SECTIONS.items():
    run_section(section_title, section_samples)
    print()
