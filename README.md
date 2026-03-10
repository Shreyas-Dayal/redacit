# wrapper-llm

A local privacy layer that anonymizes sensitive data before it reaches a cloud LLM, then restores the original values in the response. No data leaves your machine as-is.

---

## How it works

```
Your prompt
    ↓
Anonymizer  →  detects PII spans (Presidio, in-process)
            →  replaces each span with a tagged placeholder  e.g. <PERSON_0>
            →  records a placeholder → original mapping
    ↓
Cloud LLM  (sees only anonymized text)
    ↓
Deanonymizer  →  replaces placeholders in the response with original values
    ↓
Your app  (receives the reply with real names/emails/etc. restored)
```

Everything runs locally. No Docker required.

---

## Detected entity types (default)

| Entity | Example |
|---|---|
| `PERSON` | John Smith |
| `EMAIL_ADDRESS` | john@acme.com |
| `PHONE_NUMBER` | +1 (415) 555-0192 |
| `CREDIT_CARD` | 4532-0151-1283-0366 |
| `US_SSN` | 346-12-5678 |
| `IP_ADDRESS` | 203.0.113.42 |
| `LOCATION` | Austin, TX |
| `ORGANIZATION` | Acme Holdings |
| `DATE_TIME` | 2024-04-15 |
| `IBAN_CODE` | GB29NWBK60161331926819 |
| `URL` | acme.com |
| `US_PASSPORT` | 938475610 |
| `US_DRIVER_LICENSE` | — |

---

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# Install dependencies
uv sync

# Download the spaCy language model (one-time)
uv run python -m spacy download en_core_web_lg
```

Copy `.env.example` to `.env` and add your API key if you want to test live LLM calls:

```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY=sk-...
```

---

## Usage

### Core API (no API key needed)

```python
from src.privacy_wrapper.anonymizer import Anonymizer

anon = Anonymizer()

result = anon.anonymize("Send the report to Alice Jones at alice@corp.com")
print(result.anonymized_text)
# → Send the report to <PERSON_0> at <EMAIL_ADDRESS_0>
print(result.mapping)
# → {'<PERSON_0>': 'Alice Jones', '<EMAIL_ADDRESS_0>': 'alice@corp.com'}

# Restore original values from an LLM response
restored = anon.deanonymize(result.anonymized_text, result.mapping)
# → Send the report to Alice Jones at alice@corp.com
```

### With a live LLM (requires `OPENAI_API_KEY`)

```python
from src.privacy_wrapper.client import PrivacyClient

client = PrivacyClient()
reply = client.chat("Summarise the contract for John Smith at john@acme.com")
# Anonymized before sending, restored in the reply automatically
```

### Selective anonymization

Restrict which entity types are detected for a single call:

```python
# Only redact names and emails — ignore dates, locations, etc.
result = anon.anonymize(text, entities=["PERSON", "EMAIL_ADDRESS"])
```

---

## Demo

Run all demo datasets:

```bash
uv run python demo.py
```

Run a specific dataset by name:

```bash
uv run python demo.py general_pii
uv run python demo.py financial
uv run python demo.py financial_transactions   # CSV with selective config
```

### Adding a new demo dataset

**Plain text samples** — create a `.py` file in `demo_data/`:

```python
# demo_data/my_dataset.py
TITLE = "My Dataset"

SAMPLES = [
    "Text with sensitive data here.",
    "Another sample with John Doe and john@example.com.",
]
```

**CSV data** — drop a `.csv` file in `demo_data/`. Optionally add a `.json` sidecar with the same stem to control which columns and entity types are anonymized:

```json
{
  "title": "My Transactions",
  "fields": {
    "name":        { "entities": ["PERSON"] },
    "email":       { "entities": ["EMAIL_ADDRESS"] },
    "amount":      { "skip": true },
    "date":        { "skip": true }
  }
}
```

| Field option | Effect |
|---|---|
| `"entities": [...]` | Only those PII types detected for this column |
| `"skip": true` | Column passed through unchanged |
| *(no entry)* | Full default entity list applied |

`demo.py` discovers all `.py` and `.csv` files in `demo_data/` automatically — no changes to `demo.py` needed.

---

## Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Unit tests only (no external services needed)
uv run pytest tests/unit/ -v

# Data-driven sample tests
uv run pytest tests/test_samples.py -v
```

---

## Project structure

```
wrapper-llm/
├── src/
│   └── privacy_wrapper/
│       ├── anonymizer.py       # Core — Presidio-based PII detection and replacement
│       └── client.py           # OpenAI wrapper with anonymize/deanonymize lifecycle
├── demo_data/
│   ├── general_pii.py          # General PII samples (names, emails, SSNs, cards)
│   ├── financial.py            # Financial prose samples (invoices, wire transfers)
│   ├── financial_transactions.csv   # Structured CSV transactions
│   └── financial_transactions.json  # Per-column anonymization config for the CSV
├── tests/
│   ├── fixtures/
│   │   └── sample_prompts.py   # Shared test data with known sensitive values
│   ├── test_anonymizer.py      # Unit tests for Anonymizer
│   └── test_samples.py         # Data-driven leakage, roundtrip, and passthrough tests
├── demo.py                     # Demo runner (supports .py and .csv datasets)
├── pyproject.toml
└── .env.example
```

---

## Known limitations

| Limitation | Detail |
|---|---|
| Non-US phone numbers | UK/EU mobile numbers may fall below the default confidence threshold without a country-specific recognizer |
| API keys / secrets | No built-in recognizer for patterns like `sk-*`, `pk-*` — planned as a custom recognizer |
| Numeric pattern collisions | Bank account and routing numbers are matched as `PHONE_NUMBER`; EINs may match as `DATE_TIME`. Values are still redacted and restored correctly |
| Credit card Luhn validation | Card numbers must pass checksum validation to be detected — synthetic/invalid numbers will not be caught |
| LLM response paraphrasing | If the LLM rephrases a placeholder (e.g. expands `<PERSON_0>` to `Person Zero`), deanonymization will not restore it |

---

## Research & planning

- [`PRIVACY_LAYER_PLAN.md`](PRIVACY_LAYER_PLAN.md) — research notes covering five approaches to LLM data privacy (Presidio, proxy gateways, SLMs, FHE, local models)
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — full phased implementation plan including LiteLLM proxy integration and SLM layer
