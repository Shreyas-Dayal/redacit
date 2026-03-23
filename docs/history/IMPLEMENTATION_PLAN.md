# Privacy Layer — Detailed Implementation Plan

## Overview

Build a local privacy proxy that sits between your application and any cloud LLM. It anonymizes sensitive data before it leaves your machine and de-anonymizes responses before they reach your app.

**Target stack:** Python · LiteLLM · Microsoft Presidio · Anonymizer SLM (Qwen3 1.7B via Ollama)

---

## Project Structure

```
wrapper-llm/
├── proxy/
│   ├── main.py                  # LiteLLM proxy entrypoint
│   ├── config.yaml              # LiteLLM proxy config (models, guardrails)
│   ├── anonymizer/
│   │   ├── __init__.py
│   │   ├── presidio_layer.py    # Presidio analyzer + anonymizer wrapper
│   │   ├── slm_layer.py         # Anonymizer SLM (Ollama) wrapper
│   │   ├── pipeline.py          # Orchestrates presidio → SLM pipeline
│   │   ├── deanonymizer.py      # Response de-anonymization
│   │   └── recognizers/
│   │       ├── __init__.py
│   │       └── custom.py        # Domain-specific custom recognizers
├── tests/
│   ├── unit/
│   │   ├── test_presidio_layer.py
│   │   ├── test_slm_layer.py
│   │   ├── test_pipeline.py
│   │   └── test_deanonymizer.py
│   ├── integration/
│   │   ├── test_proxy_end_to_end.py
│   │   └── test_proxy_with_mock_llm.py
│   └── fixtures/
│       ├── sample_prompts.py    # Test prompts with known PII
│       └── expected_outputs.py  # Expected anonymized versions
├── docker-compose.yml           # Presidio analyzer + anonymizer services
├── requirements.txt
└── .env.example
```

---

## Phase 1: Infrastructure Setup

### 1.1 Dependencies

**`requirements.txt`**
```
litellm[proxy]>=1.40.0
presidio-analyzer>=2.2.354
presidio-anonymizer>=2.2.354
spacy>=3.7.0
faker>=24.0.0
python-dotenv>=1.0.0
httpx>=0.27.0
fastapi>=0.111.0
uvicorn>=0.29.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
responses>=0.25.0
ollama>=0.2.0
```

Also download the spaCy English model (required by Presidio):
```bash
pip install -r requirements.txt
python -m spacy download en_core_web_lg
```

---

### 1.2 Presidio via Docker Compose

Presidio's Analyzer and Anonymizer run as separate HTTP services. This keeps them isolated and independently scalable.

**`docker-compose.yml`**
```yaml
version: "3.9"

services:
  presidio-analyzer:
    image: mcr.microsoft.com/presidio-analyzer:latest
    ports:
      - "5002:3000"
    environment:
      - PRESIDIO_ANALYZER_NLPENGINE=spacy
    restart: unless-stopped

  presidio-anonymizer:
    image: mcr.microsoft.com/presidio-anonymizer:latest
    ports:
      - "5001:3000"
    restart: unless-stopped
```

Start services:
```bash
docker-compose up -d
```

Verify:
```bash
curl http://localhost:5002/health  # → {"status":"ok"}
curl http://localhost:5001/health  # → {"status":"ok"}
```

---

### 1.3 Environment Variables

**`.env.example`**
```
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

PRESIDIO_ANALYZER_URL=http://localhost:5002
PRESIDIO_ANONYMIZER_URL=http://localhost:5001

SLM_MODEL=anonymizer-1.7b          # Ollama model name
SLM_ENABLED=true                    # Toggle SLM layer on/off
SLM_TIMEOUT_SECONDS=5               # Max wait before falling back

LITELLM_PROXY_PORT=8000
LITELLM_MASTER_KEY=sk-proxy-local-dev
```

---

## Phase 2: Presidio Layer

### 2.1 Core Presidio Wrapper

**`proxy/anonymizer/presidio_layer.py`**
```python
import os
import httpx
from dataclasses import dataclass, field
from typing import Optional

ANALYZER_URL = os.getenv("PRESIDIO_ANALYZER_URL", "http://localhost:5002")
ANONYMIZER_URL = os.getenv("PRESIDIO_ANONYMIZER_URL", "http://localhost:5001")

# All entity types Presidio will look for
DEFAULT_ENTITIES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD",
    "US_SSN", "US_PASSPORT", "US_DRIVER_LICENSE", "IBAN_CODE",
    "IP_ADDRESS", "URL", "LOCATION", "ORGANIZATION",
    "DATE_TIME", "NRP", "MEDICAL_LICENSE",
]

@dataclass
class AnonymizationResult:
    anonymized_text: str
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder → original


class PresidioLayer:
    def __init__(
        self,
        entities: list[str] = DEFAULT_ENTITIES,
        score_threshold: float = 0.4,
        language: str = "en",
    ):
        self.entities = entities
        self.score_threshold = score_threshold
        self.language = language
        self._client = httpx.Client(timeout=10.0)

    def analyze(self, text: str) -> list[dict]:
        """Call Presidio Analyzer; returns list of recognized entity spans."""
        response = self._client.post(
            f"{ANALYZER_URL}/analyze",
            json={
                "text": text,
                "language": self.language,
                "entities": self.entities,
                "score_threshold": self.score_threshold,
            },
        )
        response.raise_for_status()
        return response.json()

    def anonymize(self, text: str, analyzer_results: list[dict]) -> AnonymizationResult:
        """
        Call Presidio Anonymizer with REPLACE operator.
        Returns anonymized text and a mapping of placeholder → original value.
        """
        if not analyzer_results:
            return AnonymizationResult(anonymized_text=text)

        response = self._client.post(
            f"{ANONYMIZER_URL}/anonymize",
            json={
                "text": text,
                "analyzer_results": analyzer_results,
                "anonymizers": {
                    # Use REPLACE with a tagged placeholder for each entity type
                    entity: {
                        "type": "replace",
                        "new_value": f"<{entity}_{i}>",
                    }
                    for i, entity in enumerate(self.entities)
                },
            },
        )
        response.raise_for_status()
        data = response.json()

        # Build reverse mapping: placeholder → original
        mapping = {}
        for item in data.get("items", []):
            mapping[item["text"]] = text[item["start"]:item["end"]]

        return AnonymizationResult(
            anonymized_text=data["text"],
            mapping=mapping,
        )

    def run(self, text: str) -> AnonymizationResult:
        """Full analyze → anonymize pipeline."""
        hits = self.analyze(text)
        return self.anonymize(text, hits)

    def close(self):
        self._client.close()
```

---

### 2.2 Custom Recognizers for Proprietary Terms

Add domain-specific recognizers (e.g., internal project names, employee IDs, product codes).

**`proxy/anonymizer/recognizers/custom.py`**
```python
from presidio_analyzer import PatternRecognizer, Pattern

def build_custom_recognizers() -> list:
    """
    Returns a list of custom Presidio recognizers for domain-specific PII.
    Add your own patterns here.
    """
    recognizers = []

    # Example: Internal employee ID format EMP-XXXXXXXX
    employee_id_recognizer = PatternRecognizer(
        supported_entity="EMPLOYEE_ID",
        patterns=[
            Pattern(
                name="employee_id_pattern",
                regex=r"\bEMP-[A-Z0-9]{6,10}\b",
                score=0.9,
            )
        ],
    )
    recognizers.append(employee_id_recognizer)

    # Example: Internal project codes like PRJ-2024-ALPHA
    project_code_recognizer = PatternRecognizer(
        supported_entity="PROJECT_CODE",
        patterns=[
            Pattern(
                name="project_code_pattern",
                regex=r"\bPRJ-\d{4}-[A-Z]+\b",
                score=0.9,
            )
        ],
    )
    recognizers.append(project_code_recognizer)

    # Example: Internal API keys or secrets (generic high-entropy strings)
    secret_recognizer = PatternRecognizer(
        supported_entity="INTERNAL_SECRET",
        patterns=[
            Pattern(
                name="secret_pattern",
                regex=r"\b(sk|pk|api|secret|token)[-_][A-Za-z0-9]{20,}\b",
                score=0.85,
            )
        ],
    )
    recognizers.append(secret_recognizer)

    return recognizers
```

To register these with Presidio's local Python SDK (used in testing, not the Docker API):
```python
from presidio_analyzer import AnalyzerEngine
from proxy.anonymizer.recognizers.custom import build_custom_recognizers

analyzer = AnalyzerEngine()
for recognizer in build_custom_recognizers():
    analyzer.registry.add_recognizer(recognizer)
```

> **Note:** When using the Presidio Docker API, custom recognizers must be packaged into a custom Docker image or added via the REST `/recognizers` endpoint.

---

## Phase 3: Anonymizer SLM Layer

The SLM layer runs a lightweight local model (Qwen3 1.7B via Ollama) to catch contextual PII that Presidio's rules miss — e.g., subtle name references, implicit identifiers, or nuanced context.

### 3.1 Pull the SLM via Ollama

```bash
# Install Ollama: https://ollama.com
ollama pull hf.co/eternisai/Anonymizer-1.7B-GGUF   # or use the 0.6B for speed
```

### 3.2 SLM Wrapper

**`proxy/anonymizer/slm_layer.py`**
```python
import os
import json
import ollama
from proxy.anonymizer.presidio_layer import AnonymizationResult

SLM_MODEL = os.getenv("SLM_MODEL", "anonymizer-1.7b")
SLM_ENABLED = os.getenv("SLM_ENABLED", "true").lower() == "true"
SLM_TIMEOUT = int(os.getenv("SLM_TIMEOUT_SECONDS", "5"))

SYSTEM_PROMPT = """
You are a privacy filter. Your job is to identify and replace any remaining
personally identifiable information (PII) or sensitive data in the text that
may have been missed by automated tools.

Rules:
- Replace private individual names with similar culturally appropriate names
- Replace company names with fictional alternatives of similar industry
- Replace specific locations with generic equivalents
- Do NOT replace public figures, well-known organizations, or historical facts
- Do NOT change the meaning or intent of the text
- Return ONLY the sanitized text, no explanation

If no changes are needed, return the text unchanged.
"""


class SLMLayer:
    def __init__(self, model: str = SLM_MODEL):
        self.model = model
        self.enabled = SLM_ENABLED

    def refine(self, presidio_result: AnonymizationResult) -> AnonymizationResult:
        """Pass Presidio-anonymized text through SLM for contextual refinement."""
        if not self.enabled:
            return presidio_result

        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": presidio_result.anonymized_text},
                ],
                options={"temperature": 0},  # Deterministic output
            )
            refined_text = response["message"]["content"].strip()

            return AnonymizationResult(
                anonymized_text=refined_text,
                mapping=presidio_result.mapping,  # Preserve original mapping
            )

        except Exception as e:
            # Fail open: if SLM is unavailable, return Presidio result as-is
            print(f"[SLM] Warning: SLM layer failed ({e}), using Presidio output.")
            return presidio_result
```

---

## Phase 4: Anonymization Pipeline

Orchestrates Presidio → SLM in sequence.

**`proxy/anonymizer/pipeline.py`**
```python
from proxy.anonymizer.presidio_layer import PresidioLayer, AnonymizationResult
from proxy.anonymizer.slm_layer import SLMLayer


class AnonymizationPipeline:
    def __init__(self):
        self.presidio = PresidioLayer()
        self.slm = SLMLayer()

    def anonymize(self, text: str) -> AnonymizationResult:
        # Step 1: Presidio (regex + NER)
        presidio_result = self.presidio.run(text)

        # Step 2: SLM refinement (contextual)
        final_result = self.slm.refine(presidio_result)

        return final_result

    def deanonymize(self, text: str, mapping: dict[str, str]) -> str:
        """Replace all placeholders in LLM response with original values."""
        result = text
        for placeholder, original in mapping.items():
            result = result.replace(placeholder, original)
        return result
```

---

## Phase 5: LiteLLM Proxy Integration

LiteLLM acts as the OpenAI-compatible proxy. We hook into it via a custom callback.

### 5.1 LiteLLM Config

**`proxy/config.yaml`**
```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: gpt-4o
      api_key: os.environ/OPENAI_API_KEY

  - model_name: claude-sonnet
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

litellm_settings:
  callbacks: ["proxy.main.PrivacyCallback"]

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  port: 8000
```

### 5.2 Custom Callback

**`proxy/main.py`**
```python
import litellm
from litellm.integrations.custom_logger import CustomLogger
from proxy.anonymizer.pipeline import AnonymizationPipeline

pipeline = AnonymizationPipeline()

# Per-request storage for mappings (keyed by request ID)
_request_mappings: dict[str, dict] = {}


class PrivacyCallback(CustomLogger):

    def log_pre_api_call(self, model, messages, kwargs, **extra):
        """Intercept and anonymize messages before they leave the proxy."""
        request_id = kwargs.get("litellm_call_id", "unknown")
        combined_mapping = {}

        for message in messages:
            if isinstance(message.get("content"), str):
                result = pipeline.anonymize(message["content"])
                message["content"] = result.anonymized_text
                combined_mapping.update(result.mapping)

        _request_mappings[request_id] = combined_mapping
        print(f"[Privacy] Anonymized request {request_id}. "
              f"Replacements made: {len(combined_mapping)}")

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        """De-anonymize the LLM response before it returns to the caller."""
        request_id = kwargs.get("litellm_call_id", "unknown")
        mapping = _request_mappings.pop(request_id, {})

        if not mapping:
            return

        for choice in response_obj.choices:
            if hasattr(choice, "message") and choice.message.content:
                choice.message.content = pipeline.deanonymize(
                    choice.message.content, mapping
                )

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """Clean up mapping on failure."""
        request_id = kwargs.get("litellm_call_id", "unknown")
        _request_mappings.pop(request_id, None)


# Register callback
litellm.callbacks = [PrivacyCallback()]
```

### 5.3 Start the Proxy

```bash
litellm --config proxy/config.yaml
```

The proxy is now available at `http://localhost:8000` and is fully OpenAI API-compatible. Point any existing OpenAI SDK client at it:

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-proxy-local-dev",   # LITELLM_MASTER_KEY
    base_url="http://localhost:8000",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Summarize the contract for John Smith (john@acme.com)"}],
)
print(response.choices[0].message.content)
# John Smith / john@acme.com are anonymized before hitting OpenAI,
# then restored in the response automatically.
```

---

## Phase 6: Testing

### 6.1 Test Fixtures

**`tests/fixtures/sample_prompts.py`**
```python
PROMPTS_WITH_PII = [
    {
        "id": "basic_person_email",
        "input": "Send the report to John Smith at john.smith@acme.com by Friday.",
        "expected_entities": ["PERSON", "EMAIL_ADDRESS", "DATE_TIME"],
    },
    {
        "id": "financial",
        "input": "Charge the card 4111-1111-1111-1111 for the invoice.",
        "expected_entities": ["CREDIT_CARD"],
    },
    {
        "id": "ssn",
        "input": "Employee SSN is 123-45-6789, DOB 01/15/1985.",
        "expected_entities": ["US_SSN", "DATE_TIME"],
    },
    {
        "id": "multi_entity",
        "input": (
            "Alice Johnson (EMP-ABC123) from the London office called "
            "about project PRJ-2024-ALPHA. Her number is +1-800-555-0199."
        ),
        "expected_entities": ["PERSON", "EMPLOYEE_ID", "LOCATION", "PROJECT_CODE", "PHONE_NUMBER"],
    },
    {
        "id": "no_pii",
        "input": "What is the capital of France?",
        "expected_entities": [],
    },
]
```

---

### 6.2 Unit Tests — Presidio Layer

**`tests/unit/test_presidio_layer.py`**
```python
import pytest
from unittest.mock import patch, MagicMock
from proxy.anonymizer.presidio_layer import PresidioLayer, AnonymizationResult
from tests.fixtures.sample_prompts import PROMPTS_WITH_PII


@pytest.fixture
def layer():
    return PresidioLayer()


class TestPresidioLayer:

    def test_analyze_detects_email(self, layer):
        text = "Contact me at alice@example.com"
        with patch.object(layer._client, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: [{"entity_type": "EMAIL_ADDRESS", "start": 14, "end": 31, "score": 0.85}],
            )
            results = layer.analyze(text)
        assert any(r["entity_type"] == "EMAIL_ADDRESS" for r in results)

    def test_anonymize_replaces_email(self, layer):
        text = "Contact me at alice@example.com"
        analyzer_results = [{"entity_type": "EMAIL_ADDRESS", "start": 14, "end": 31, "score": 0.85}]

        with patch.object(layer._client, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "text": "Contact me at <EMAIL_ADDRESS_0>",
                    "items": [{"text": "<EMAIL_ADDRESS_0>", "start": 14, "end": 31}],
                },
            )
            result = layer.anonymize(text, analyzer_results)

        assert "alice@example.com" not in result.anonymized_text
        assert "<EMAIL_ADDRESS_0>" in result.anonymized_text
        assert result.mapping["<EMAIL_ADDRESS_0>"] == "alice@example.com"

    def test_run_returns_anonymization_result(self, layer):
        text = "No PII here"
        with patch.object(layer, "analyze", return_value=[]):
            with patch.object(layer, "anonymize", return_value=AnonymizationResult(anonymized_text=text)):
                result = layer.run(text)
        assert isinstance(result, AnonymizationResult)
        assert result.anonymized_text == text

    @pytest.mark.parametrize("prompt", PROMPTS_WITH_PII)
    def test_expected_entities_detected(self, layer, prompt):
        """Smoke test: verify each fixture prompt detects at least the expected entities."""
        if not prompt["expected_entities"]:
            pytest.skip("No PII expected")

        with patch.object(layer._client, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: [
                    {"entity_type": e, "start": 0, "end": 5, "score": 0.9}
                    for e in prompt["expected_entities"]
                ],
            )
            results = layer.analyze(prompt["input"])

        detected = {r["entity_type"] for r in results}
        for expected in prompt["expected_entities"]:
            assert expected in detected, f"Expected {expected} not detected in: {prompt['input']}"
```

---

### 6.3 Unit Tests — SLM Layer

**`tests/unit/test_slm_layer.py`**
```python
import pytest
from unittest.mock import patch
from proxy.anonymizer.presidio_layer import AnonymizationResult
from proxy.anonymizer.slm_layer import SLMLayer


@pytest.fixture
def layer():
    return SLMLayer()


class TestSLMLayer:

    def test_refine_returns_anonymization_result(self, layer):
        input_result = AnonymizationResult(
            anonymized_text="Hello <PERSON_0>",
            mapping={"<PERSON_0>": "John"},
        )
        with patch("ollama.chat") as mock_chat:
            mock_chat.return_value = {"message": {"content": "Hello <PERSON_0>"}}
            output = layer.refine(input_result)
        assert isinstance(output, AnonymizationResult)

    def test_refine_preserves_mapping(self, layer):
        input_result = AnonymizationResult(
            anonymized_text="Call <PERSON_0> at <EMAIL_ADDRESS_0>",
            mapping={"<PERSON_0>": "Alice", "<EMAIL_ADDRESS_0>": "alice@corp.com"},
        )
        with patch("ollama.chat") as mock_chat:
            mock_chat.return_value = {"message": {"content": "Call <PERSON_0> at <EMAIL_ADDRESS_0>"}}
            output = layer.refine(input_result)
        assert output.mapping == input_result.mapping

    def test_refine_fails_open_on_error(self, layer):
        """If Ollama is unavailable, SLM layer should return Presidio result unchanged."""
        input_result = AnonymizationResult(
            anonymized_text="Safe text",
            mapping={},
        )
        with patch("ollama.chat", side_effect=Exception("connection refused")):
            output = layer.refine(input_result)
        assert output.anonymized_text == "Safe text"

    def test_refine_skipped_when_disabled(self):
        layer = SLMLayer(model="any-model")
        layer.enabled = False
        input_result = AnonymizationResult(anonymized_text="text", mapping={})
        with patch("ollama.chat") as mock_chat:
            output = layer.refine(input_result)
            mock_chat.assert_not_called()
        assert output == input_result
```

---

### 6.4 Unit Tests — Pipeline & De-anonymizer

**`tests/unit/test_pipeline.py`**
```python
import pytest
from unittest.mock import MagicMock, patch
from proxy.anonymizer.pipeline import AnonymizationPipeline
from proxy.anonymizer.presidio_layer import AnonymizationResult


@pytest.fixture
def pipeline():
    p = AnonymizationPipeline()
    p.presidio = MagicMock()
    p.slm = MagicMock()
    return p


class TestAnonymizationPipeline:

    def test_anonymize_calls_presidio_then_slm(self, pipeline):
        presidio_result = AnonymizationResult(
            anonymized_text="Hello <PERSON_0>", mapping={"<PERSON_0>": "Bob"}
        )
        slm_result = AnonymizationResult(
            anonymized_text="Hello <PERSON_0>", mapping={"<PERSON_0>": "Bob"}
        )
        pipeline.presidio.run.return_value = presidio_result
        pipeline.slm.refine.return_value = slm_result

        result = pipeline.anonymize("Hello Bob")

        pipeline.presidio.run.assert_called_once_with("Hello Bob")
        pipeline.slm.refine.assert_called_once_with(presidio_result)
        assert result == slm_result

    def test_deanonymize_restores_original_values(self, pipeline):
        mapping = {"<PERSON_0>": "Alice", "<EMAIL_ADDRESS_0>": "alice@corp.com"}
        text = "Contact <PERSON_0> at <EMAIL_ADDRESS_0>"
        result = pipeline.deanonymize(text, mapping)
        assert result == "Contact Alice at alice@corp.com"

    def test_deanonymize_noop_with_empty_mapping(self, pipeline):
        text = "No placeholders here"
        result = pipeline.deanonymize(text, {})
        assert result == text

    def test_deanonymize_partial_match(self, pipeline):
        mapping = {"<PERSON_0>": "Bob"}
        text = "Hello <PERSON_0> and <PERSON_1>"
        result = pipeline.deanonymize(text, mapping)
        assert "Bob" in result
        assert "<PERSON_1>" in result  # Unmatched placeholder left intact
```

---

### 6.5 Integration Tests — End to End with Mock LLM

**`tests/integration/test_proxy_with_mock_llm.py`**
```python
"""
Integration test: spins up the anonymization pipeline and sends a request
through LiteLLM with a mocked LLM backend to verify full anonymize →
forward → deanonymize flow.
"""
import pytest
import responses as responses_lib
from proxy.anonymizer.pipeline import AnonymizationPipeline


@pytest.fixture
def pipeline():
    return AnonymizationPipeline()


class TestEndToEndAnonymization:

    def test_email_is_anonymized_before_forwarding(self, pipeline):
        text = "Please email alice@company.com the invoice."
        result = pipeline.anonymize(text)
        assert "alice@company.com" not in result.anonymized_text
        assert len(result.mapping) >= 1

    def test_ssn_is_anonymized(self, pipeline):
        text = "The applicant's SSN is 123-45-6789."
        result = pipeline.anonymize(text)
        assert "123-45-6789" not in result.anonymized_text

    def test_clean_text_passes_through_unchanged(self, pipeline):
        text = "What is the boiling point of water?"
        result = pipeline.anonymize(text)
        assert result.anonymized_text == text
        assert result.mapping == {}

    def test_deanonymize_restores_after_llm_response(self, pipeline):
        original = "Send the invoice to john@acme.com"
        anonymized = pipeline.anonymize(original)

        # Simulate LLM echoing back the placeholder
        fake_llm_response = f"Invoice sent to {list(anonymized.mapping.keys())[0]}"
        restored = pipeline.deanonymize(fake_llm_response, anonymized.mapping)

        assert "john@acme.com" in restored

    def test_multiple_entities_all_restored(self, pipeline):
        original = "Alice Johnson, SSN 987-65-4321, email alice@corp.com"
        anonymized = pipeline.anonymize(original)

        # Simulate LLM response containing all placeholders
        fake_response = anonymized.anonymized_text
        restored = pipeline.deanonymize(fake_response, anonymized.mapping)

        assert "Alice Johnson" in restored or "alice@corp.com" in restored or "987-65-4321" in restored
```

---

### 6.6 Running Tests

```bash
# All tests
pytest tests/ -v

# Unit tests only (fast, no external services needed)
pytest tests/unit/ -v

# Integration tests (requires Docker Compose + Presidio running)
pytest tests/integration/ -v

# With coverage report
pytest tests/ --cov=proxy --cov-report=term-missing
```

---

## Phase 7: Validation & Observability

### 7.1 Anonymization Audit Log

Log what was detected and replaced (without logging the original values) for debugging:

```python
# In pipeline.py anonymize()
print(f"[Audit] Entities replaced: {list(result.mapping.keys())}")
# Output: [Audit] Entities replaced: ['<PERSON_0>', '<EMAIL_ADDRESS_0>']
# Original values are NOT logged
```

### 7.2 Leakage Detection Test

Verify no PII leaks through by scanning the anonymized output:

```python
def assert_no_leakage(original_pii: list[str], anonymized_text: str):
    for item in original_pii:
        assert item not in anonymized_text, f"LEAKAGE DETECTED: '{item}' found in output"

# Example usage in tests
assert_no_leakage(
    ["alice@company.com", "123-45-6789"],
    result.anonymized_text
)
```

### 7.3 Manual Smoke Test Script

**`tests/smoke_test.py`**
```python
"""Run this manually to test the full stack (Docker + Ollama must be running)."""
from proxy.anonymizer.pipeline import AnonymizationPipeline

pipeline = AnonymizationPipeline()

test_cases = [
    "Schedule a call with Bob Martinez (bob@bigcorp.com) about the Q3 numbers.",
    "My SSN is 456-78-9012 and card is 4111-1111-1111-1111.",
    "The server IP is 192.168.1.105 — please don't share this.",
    "What is photosynthesis?",  # No PII — should pass through unchanged
]

for text in test_cases:
    result = pipeline.anonymize(text)
    print(f"\nOriginal : {text}")
    print(f"Anonymized: {result.anonymized_text}")
    print(f"Mappings  : {len(result.mapping)} replacements")
    restored = pipeline.deanonymize(result.anonymized_text, result.mapping)
    print(f"Restored  : {restored}")
    assert restored == text or not result.mapping, "De-anonymization mismatch!"
```

Run with:
```bash
python tests/smoke_test.py
```

---

## Startup Checklist

```
[ ] Docker Desktop running
[ ] docker-compose up -d  (Presidio analyzer :5002, anonymizer :5001)
[ ] ollama pull hf.co/eternisai/Anonymizer-1.7B-GGUF
[ ] ollama serve          (Ollama running on :11434)
[ ] cp .env.example .env  (fill in API keys)
[ ] pip install -r requirements.txt
[ ] python -m spacy download en_core_web_lg
[ ] pytest tests/unit/ -v             (no infra needed)
[ ] python tests/smoke_test.py        (full stack)
[ ] litellm --config proxy/config.yaml
```

---

## Limitations & Mitigations

| Limitation | Mitigation |
|------------|------------|
| Presidio misses contextual/implicit PII | SLM layer as second pass |
| SLM adds 500ms–2s latency | Run async; use 0.6B for speed-sensitive paths |
| De-anonymization fails if LLM paraphrases placeholder | Use tagged placeholders (e.g., `<PERSON_abc123>`) that LLMs are unlikely to rephrase |
| Custom recognizers need maintenance | Write tests for each custom pattern |
| SLM may over-anonymize (remove non-PII) | Set `temperature=0`; add examples to system prompt |
| Mapping stored in-memory only | Sufficient for request scope; add Redis for distributed deployments |
