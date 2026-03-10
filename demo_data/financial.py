TITLE = "Financial & Structured"

SAMPLES = [
    # Wire transfer instruction
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

    # Loan application (key-value block)
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

    # Brokerage / trading note
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
]
