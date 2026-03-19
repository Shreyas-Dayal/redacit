# wrapper-llm

A local privacy layer that anonymizes sensitive data before it reaches a cloud LLM, then restores original values in the response. No data leaves your machine as-is. No Docker required.

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
Your app  (receives the reply with real names / emails / etc. restored)
```

---

## Detected entity types

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
| `US_BANK_ACCOUNT` | 7823901645 *(custom)* |
| `US_ROUTING_NUMBER` | 021000021 *(custom)* |
| `EIN` | 12-3456789 *(custom)* |
| `API_KEY` | sk-xK92mLp… *(custom)* |

---

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
pip install wrapper-llm                  # base install — regex-only PII detection
pip install "wrapper-llm[model-sm]"      # + person names, locations (11 MB)
pip install "wrapper-llm[model-md]"      # + word vectors for better accuracy (43 MB, recommended)
pip install "wrapper-llm[model-lg]"      # + max NER accuracy (560 MB)
```

Copy `.env.example` to `.env` and add your API key for live LLM calls:

```bash
cp .env.example .env
# set OPENAI_API_KEY=sk-...
```

---

## Model options

wrapper-llm auto-detects the best available spaCy model at startup. No configuration needed — it just uses whatever is installed.

| Install command | Model | Size | Detects |
|---|---|---|---|
| `pip install wrapper-llm` | none (regex-only) | 0 MB | emails, SSNs, credit cards, phones, IBANs, API keys, bank accounts, EINs, URLs, IPs |
| `pip install "wrapper-llm[model-sm]"` | en_core_web_sm | 11 MB | + person names, locations, organizations |
| `pip install "wrapper-llm[model-md]"` | en_core_web_md | 43 MB | + word vectors for better NER accuracy (recommended) |
| `pip install "wrapper-llm[model-lg]"` | en_core_web_lg | 560 MB | + marginally better accuracy over md |

For most use cases, `model-md` is the best balance of size and accuracy. Use `model-sm` for minimal footprint, or the base install for structured-PII-only use cases (financial data, API key scrubbing).

You can also select the model explicitly in code:

```python
from privacy_wrapper import Anonymizer

anon = Anonymizer()                          # auto-detect best available
anon = Anonymizer(model="en_core_web_sm")    # explicit small model
anon = Anonymizer(model=None)                # regex-only, no NLP model
```

---

## Usage

### 1. CLI — no code needed

```bash
wrapper-llm anonymize "Schedule a call with John Smith at john@acme.com"

# Anonymized:
# Schedule a call with <PERSON_0> at <EMAIL_ADDRESS_0>
#
# Mapping:
#   <PERSON_0>                       John Smith
#   <EMAIL_ADDRESS_0>                john@acme.com
```

Filter entity types or tune the confidence threshold:

```bash
wrapper-llm anonymize "John Smith, card 4111-1111-1111-1111" --entity PERSON
wrapper-llm anonymize "..." --threshold 0.6
```

Analyse an audit log:

```bash
wrapper-llm stats privacy_audit.jsonl --top 5
```

Start the REST API server (requires the `server` extra):

```bash
uv add 'wrapper-llm[server]'
wrapper-llm serve --host 0.0.0.0 --port 8000
```

---

### 2. Drop-in OpenAI replacement

The fastest path if you already have OpenAI code — change **one line**:

```python
# Before
from openai import OpenAI
client = OpenAI()

# After
from privacy_wrapper import PrivacyOpenAI
client = PrivacyOpenAI()

# Everything else stays identical
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Summarise Alice Jones's contract at alice@corp.com"}],
)
# Alice Jones and alice@corp.com are anonymized before the API call
# and restored in response.choices[0].message.content automatically
```

Tools, `response_format`, streaming, embeddings, and all other SDK call patterns work unchanged.

---

### 3. Simple chat client (OpenAI)

```python
from privacy_wrapper import OpenAIPrivacyClient

client = OpenAIPrivacyClient()    # reads OPENAI_API_KEY from env
reply  = client.chat("Draft a letter to John Smith at john@acme.com")
# PII stripped before the call, restored in the reply
```

Stream the response:

```python
for chunk in client.stream("Summarise the following contract: ..."):
    print(chunk, end="", flush=True)
```

### 3b. Unified client — any SDK

```python
from privacy_wrapper import PrivacyClient
from openai import OpenAI              # or anthropic.Anthropic, google.genai.Client

client = PrivacyClient(OpenAI())
reply  = client.query("Draft a letter to John Smith at john@acme.com")
# Works identically with any supported SDK
```

---

### 4. Low-level anonymizer (manage the LLM call yourself)

```python
from privacy_wrapper import anonymize, deanonymize

result   = anonymize("SSN: 346-12-5678, card: 4111-1111-1111-1111")
raw      = your_llm_call(result.anonymized_text)
restored = deanonymize(raw, result.mapping)
```

Restrict which entity types are detected for a single call:

```python
result = anonymize(text, entities=["PERSON", "EMAIL_ADDRESS"])
```

---

### 5. Multi-turn conversations

`PrivacySession` accumulates the placeholder-to-original mapping across turns so PII introduced in one message stays resolvable in later responses:

```python
from privacy_wrapper import OpenAIPrivacyClient, PrivacySession

session = PrivacySession()
client  = OpenAIPrivacyClient(session=session)

client.chat("My name is Alice Jones")       # <PERSON_0> → Alice Jones stored
client.chat("What did I just tell you?")    # placeholder resolved from session
session.clear()                             # start a new conversation
```

---

### 6. REST API

```bash
# Anonymize
curl -s -X POST http://localhost:8000/anonymize \
  -H "Content-Type: application/json" \
  -d '{"text": "Email alice@corp.com by Friday"}' | jq
# { "anonymized_text": "Email <EMAIL_ADDRESS_0> by Friday",
#   "mapping": {"<EMAIL_ADDRESS_0>": "alice@corp.com"} }

# Restore
curl -s -X POST http://localhost:8000/deanonymize \
  -H "Content-Type: application/json" \
  -d '{"text": "Email <EMAIL_ADDRESS_0> by Friday",
       "mapping": {"<EMAIL_ADDRESS_0>": "alice@corp.com"}}' | jq
# { "text": "Email alice@corp.com by Friday" }

# Chat proxy (requires OPENAI_API_KEY on the server)
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarise the contract for John Smith"}' | jq
```

Full OpenAPI docs available at `http://localhost:8000/docs` when the server is running.

---

### 7. Structured data — CSV and JSON files

```python
from privacy_wrapper import CsvAnonymizer, JsonAnonymizer

# CSV — one result per row
for row in CsvAnonymizer().anonymize_file("customers.csv"):
    print(row.anonymized)      # dict with PII replaced per column
    print(row.flat_mapping)    # combined placeholder map for this row

# JSON — one result per record
for rec in JsonAnonymizer().anonymize_file("records.json"):
    print(rec.anonymized)      # nested dict with PII replaced at leaf strings
```

Add a sidecar config file to control per-column or per-path rules:

```json
// customers.json  (placed alongside customers.csv)
{
  "fields": {
    "name":    { "entities": ["PERSON"] },
    "email":   { "entities": ["EMAIL_ADDRESS"] },
    "amount":  { "skip": true },
    "date":    { "skip": true }
  }
}
```

| Field option | Effect |
|---|---|
| `"entities": [...]` | Only those PII types detected for this field |
| `"skip": true` | Field passed through unchanged |
| `"score_threshold": N` | Per-field confidence threshold |
| *(no entry)* | Full default entity list at default threshold |

---

### 8. Audit logging

`AuditLogger` writes append-only JSONL. Raw text and mapping values are **never** stored — only metadata safe for compliance review:

```python
from privacy_wrapper import OpenAIPrivacyClient, AuditLogger

with AuditLogger("privacy_audit.jsonl") as log:
    client = OpenAIPrivacyClient(audit_logger=log)
    client.chat("Wire $50,000 to account 7823901645")

# Appended record:
# {
#   "ts": "2024-11-01T12:00:00+00:00",
#   "input_hash": "a3f9b2c1...",          ← SHA-256[:16] of the input
#   "entity_counts": {"US_BANK_ACCOUNT": 1},
#   "total_redacted": 1,
#   "provider": "openai",
#   "model": "gpt-4o-mini"
# }
```

Analyse a log file from the CLI:

```bash
wrapper-llm stats privacy_audit.jsonl

# Audit log : privacy_audit.jsonl
# Records   : 142
# Total PII : 389
#
# Top 5 entity types:
#   PERSON                         98
#   EMAIL_ADDRESS                  71
#   US_BANK_ACCOUNT                54
#   CREDIT_CARD                    41
#   PHONE_NUMBER                   38
```

---

## Demo

```bash
uv run python demo.py                        # run all demo datasets
uv run python demo.py general_pii            # plain text PII samples
uv run python demo.py financial              # financial prose samples
uv run python demo.py financial_transactions # CSV with per-column config
uv run python demo.py financial_records      # nested JSON with sidecar
```

### Adding a demo dataset

**Plain text** — add a `.py` file to `demo_data/`:

```python
# demo_data/my_dataset.py
TITLE = "My Dataset"
SAMPLES = [
    "Text with sensitive data here.",
    "Another sample with John Doe at john@example.com.",
]
```

**CSV** — drop a `.csv` into `demo_data/` and optionally a `.json` sidecar with the same stem. `demo.py` auto-discovers both.

---

## Tests

```bash
uv run pytest                        # full suite
uv run pytest tests/unit/            # recognizer unit tests only
uv run pytest tests/test_samples.py  # data-driven leakage and roundtrip tests
```

---

## Project structure

```
wrapper-llm/
├── src/privacy_wrapper/
│   ├── __init__.py             # public API — all exports live here
│   ├── anonymizer.py           # core PII detection and placeholder replacement
│   ├── _types.py               # FieldConfig, SidecarConfig, LLMClient protocol
│   ├── session.py              # PrivacySession — multi-turn mapping accumulator
│   ├── audit.py                # AuditLogger — append-only JSONL compliance log
│   ├── cli.py                  # wrapper-llm CLI (anonymize / serve / stats)
│   ├── server.py               # FastAPI server (optional — requires [server] extra)
│   ├── client/
│   │   ├── base.py             # BaseLLMClient — anonymize → call → deanonymize lifecycle
│   │   ├── privacy_client.py   # PrivacyClient — unified drop-in proxy for any SDK
│   │   ├── openai_client.py    # OpenAIPrivacyClient + PrivacyOpenAI
│   │   └── litellm_client.py   # LiteLLMPrivacyClient (optional — requires [litellm] extra)
│   ├── formats/
│   │   ├── csv.py              # CsvAnonymizer — row-by-row CSV processing
│   │   ├── json_format.py      # JsonAnonymizer — record-by-record JSON processing
│   │   └── _helpers.py         # flatten / unflatten / load_sidecar / anonymize_flat
│   └── recognizers/
│       ├── bank_account.py     # UsBankAccountRecognizer
│       ├── routing_number.py   # UsRoutingNumberRecognizer
│       ├── ein.py              # EinRecognizer
│       └── api_key.py          # ApiKeyRecognizer (sk-*, Bearer tokens, hex secrets)
├── demo_data/                  # sample datasets for demo.py
├── tests/
│   ├── fixtures/sample_prompts.py
│   ├── test_anonymizer.py
│   ├── test_samples.py
│   ├── test_cli.py
│   ├── test_server.py
│   └── unit/test_recognizers.py
├── demo.py
└── pyproject.toml
```

### Optional extras

| Extra | Installs | Enables |
|---|---|---|
| `wrapper-llm[server]` | fastapi, uvicorn | `wrapper-llm serve`, REST API |
| `wrapper-llm[litellm]` | litellm | `LiteLLMPrivacyClient` (Anthropic, Gemini, Ollama, …) |

---

## Known limitations

| Limitation | Detail |
|---|---|
| Non-US phone numbers | UK/EU mobile numbers may fall below the default confidence threshold without a country-specific recognizer |
| Numeric pattern collisions | Bank account and routing numbers can overlap with `PHONE_NUMBER` detections; overlap resolution keeps the higher-confidence span |
| Credit card Luhn validation | Card numbers must pass checksum validation — synthetic or invalid numbers are not caught |
| LLM response paraphrasing | If the LLM rewrites a placeholder (e.g. expands `<PERSON_0>` to `Person Zero`), deanonymization will not restore it |
| Streaming deanonymization | The streaming client buffers the full response before deanonymizing, since placeholders may span token boundaries |
