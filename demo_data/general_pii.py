TITLE = "General PII"

SAMPLES = [
    "Schedule a call with John Smith (john.smith@acme.com) about the Q3 financials.",
    "The applicant's SSN is 346-12-5678 and card number is 4111-1111-1111-1111.",
    "Server at 192.168.1.105 went down — contact bob@internal.org immediately.",
    (
        "Primary contact: James Whitfield\n"
        "Email: j.whitfield@globalfinance.io\n"
        "Mobile: +1 (415) 555-0187"
    ),
    (
        "Patient: Maria Santos, DOB 03/14/1979, SSN 521-74-9038. "
        "Prescribed metformin 500mg twice daily."
    ),
    (
        "This agreement is entered into by Robert Langdon (Passport: 938475610) "
        "and Acme Holdings Ltd, effective 1 January 2025."
    ),
    "What is the capital of France?",  # no PII — should pass through unchanged
]
