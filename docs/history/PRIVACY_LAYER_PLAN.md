# Privacy Layer for LLM — Research & Implementation Plan

## Goal

Build a middleware layer that intercepts data before it reaches a cloud LLM, anonymizes/encrypts PII and proprietary data, forwards the sanitized version to the LLM, then optionally re-hydrates the response with the original values.

---

## Key Concepts

### NER (Named Entity Recognition)
A classical NLP technique that identifies and classifies named entities in text:
- **Person names** — "John Smith"
- **Organizations** — "Apple", "Goldman Sachs"
- **Locations** — "New York"
- **Dates/Times** — "January 5th"
- **Custom entities** — domain-specific terms

Used alongside regex: regex handles **structured PII** (emails, SSNs, phone numbers), NER handles **unstructured PII** (names, companies, places). Tools like Presidio allow adding custom recognizers for domain-specific sensitive terms.

---

## Approaches

### Approach 1: Regex + NER-based Anonymization
**Best for:** Fast, simple, structured PII detection
**Pattern:** Replace structured PII via regex; named entities via NER models.

| Tool | Notes |
|------|-------|
| [Microsoft Presidio](https://microsoft.github.io/presidio/) | Gold standard. Analyzer + Anonymizer components, Docker-deployable, custom recognizers, supports structured data and images. |
| [LangChain PresidioAnonymizer / PresidioReversibleAnonymizer](https://python.langchain.com/docs/guides/privacy/presidio_data_anonymization/) | Direct LangChain integration. Reversible variant maintains a mapping for de-anonymization. |
| [LangSmith `create_anonymizer()`](https://reference.langchain.com/python/langsmith/anonymizer) | Lighter-weight, built into LangSmith SDK (v0.1.81+). Uses a local LLM for intelligent PII detection. Adds ~100–500ms latency per trace. |
| [thoughtworks/pii-anonymizer](https://github.com/thoughtworks/pii-anonymizer) | Open source, production-grade. |

---

### Approach 2: Proxy Gateway with Built-in Guardrails
**Best for:** Production deployments, team-wide enforcement, per-key/per-request control
**Pattern:** Route all LLM calls through a local proxy that applies anonymization as a guardrail before forwarding to the cloud provider.

**Architecture:**
```
App → LiteLLM Proxy (Presidio guardrail) → LLM Provider (OpenAI / Anthropic / etc.)
```

| Tool | Notes |
|------|-------|
| [LiteLLM Proxy + Presidio](https://docs.litellm.ai/docs/proxy/guardrails/pii_masking_v2) | Most complete solution. Presidio runs as Docker sidecars (Analyzer on :5002, Anonymizer on :5001). Supports `pre_call`, `post_call`, `logging_only` modes. Per-key and per-request toggles. Output parsing to de-anonymize responses. |
| [LiteLLM Presidio Tutorial](https://docs.litellm.ai/docs/tutorials/presidio_pii_masking) | Step-by-step setup guide. |
| [Presidio's LiteLLM docs](https://microsoft.github.io/presidio/samples/docker/litellm/) | Microsoft's own integration guide. |
| [TIAMAT Privacy Proxy](https://dev.to/tiamatenity/i-built-a-privacy-proxy-for-llms-strip-pii-before-it-hits-openai-or-anthropic-2ji2) | DIY Flask + Nginx + regex proxy. Zero-logging philosophy. Good reference for a custom build. |
| [anonLLM](https://github.com/fsndzomga/anonLLM) | Lightweight Python package; wraps LLM API calls with reversible anonymization for names, emails, phone numbers. |
| [A5-PII-Anonymizer](https://github.com/AgenticA5/A5-PII-Anonymizer) | Desktop app with built-in local LLM for removing PII from documents. |
| [Azure LLM Anonymizer Sample](https://github.com/Azure-Samples/llm-anonymizer) | Azure-focused reference implementation. |

---

### Approach 3: Small Language Model (SLM) for On-Device Anonymization
**Best for:** Intelligent, context-aware anonymization that regex/NER miss
**Pattern:** Run a tiny local model specifically fine-tuned for PII detection and replacement.

| Tool | Notes |
|------|-------|
| [Anonymizer SLM Series](https://huggingface.co/blog/pratyushrt/anonymizerslm) | Qwen3-based models (0.6B / 1.7B / 4B) fine-tuned for surgical PII replacement. |
| [eternisai/Anonymizer-0.6B](https://huggingface.co/eternisai/Anonymizer-0.6B) | Smallest variant, fastest on consumer hardware. |

**Replacement rules:**
- Names → culturally similar alternatives
- Companies → fictional entities of same industry/size
- Locations → synthetic equivalents
- Dates/Times → consistently shifted values
- Financial amounts → adjusted 0.8–1.25×
- Identifiers → format-valid randomization

**Performance:**
| Model | Score | Latency |
|-------|-------|---------|
| Qwen3 4B | 9.55/10 | <2s |
| Qwen3 1.7B | 9.20/10 | <1s |
| Qwen3 0.6B | 5.96/10 | Fastest |

**Key advantage over regex/NER:** Understands context — doesn't redact public figures, historical dates, or common knowledge. Makes targeted surgical replacements rather than blunt redaction.

Training pipeline: SFT → DPO → GRPO (with GPT-4.1 as judge).

---

### Approach 4: Encryption / Confidential Computing
**Best for:** Maximum privacy guarantee; when even anonymized data can't leave the machine
**Tradeoff:** Most complex to implement; some options still experimental.

| Tool | Notes |
|------|-------|
| [FHE for LLMs — Zama / HuggingFace](https://huggingface.co/blog/encrypted-llm) | Run inference on fully encrypted data. Server never sees plaintext. Still experimental/slow. |
| [Confidential Computing with TEEs — Red Hat](https://next.redhat.com/2025/10/23/enhancing-ai-inference-security-with-confidential-computing-a-path-to-private-data-inference-with-proprietary-llms/) | Run LLMs inside hardware enclaves (e.g., NVIDIA H100). Attestation proves enclave is genuine. |
| [Edgeless Systems "Encrypted LocalAI"](https://www.edgeless.systems/resource-library/local-ai) | Tutorial for deploying LocalAI confidentially inside a TEE. |
| [Stanford Hazy Research — TEE Protocol](https://hazyresearch.stanford.edu/blog/2025-05-12-security) | Describes ephemeral key exchange + attestation for private cloud inference. |

---

### Approach 5: Run LLM Locally (Avoid Cloud Entirely)
**Best for:** Highest-sensitivity data where no cloud exposure is acceptable.

| Tool | Notes |
|------|-------|
| [Ollama](https://www.freecodecamp.org/news/protect-sensitive-data-with-local-llms/) | Easy local model runner (Llama, Mistral, etc.). |
| LM Studio | GUI-based local LLM runner. |
| vLLM | High-performance local inference server. |

---

## Recommended Architecture

```
Your App
   ↓
Local Privacy Proxy (LiteLLM or custom Flask)
   ├── Step 1: Presidio Analyzer → detect PII + proprietary terms
   ├── Step 2: Presidio Anonymizer → replace with consistent placeholders
   │             + custom recognizers for domain-specific terms
   ├── Step 3: Anonymizer SLM (0.6B/1.7B) → catch contextual PII Presidio misses
   ↓
Cloud LLM (OpenAI / Anthropic / etc.) — receives only sanitized prompt
   ↓
De-anonymize response using stored placeholder→original mapping
   ↓
Your App — receives full response with original values restored
```

### Why this combination:
- **LiteLLM** provides the proxy scaffolding with minimal code
- **Presidio** handles structured PII (fast, reliable, regex + NER)
- **Custom recognizers** in Presidio handle proprietary domain terms
- **Anonymizer SLM** handles nuanced/contextual cases that rule-based systems miss
- **Reversible anonymization** (mapping stored in-memory per request) allows response de-anonymization

---

## Implementation Phases

1. **Phase 1:** Set up LiteLLM proxy locally, configure Presidio Docker sidecars
2. **Phase 2:** Add custom Presidio recognizers for proprietary/domain-specific terms
3. **Phase 3:** Integrate Anonymizer SLM (1.7B) for contextual coverage
4. **Phase 4:** Implement response de-anonymization (output parsing)
5. **Phase 5:** Evaluate whether FHE/TEE is needed for highest-sensitivity data

---

## References

- [Microsoft Presidio](https://microsoft.github.io/presidio/)
- [LangChain PII Anonymization with Presidio](https://python.langchain.com/docs/guides/privacy/presidio_data_anonymization/)
- [LangSmith Anonymizer](https://reference.langchain.com/python/langsmith/anonymizer)
- [LiteLLM PII/PHI Masking](https://docs.litellm.ai/docs/proxy/guardrails/pii_masking_v2)
- [LiteLLM Presidio Tutorial](https://docs.litellm.ai/docs/tutorials/presidio_pii_masking)
- [Presidio + LiteLLM (Microsoft)](https://microsoft.github.io/presidio/samples/docker/litellm/)
- [Anonymizer SLM Series](https://huggingface.co/blog/pratyushrt/anonymizerslm)
- [anonLLM GitHub](https://github.com/fsndzomga/anonLLM)
- [TIAMAT Privacy Proxy](https://dev.to/tiamatenity/i-built-a-privacy-proxy-for-llms-strip-pii-before-it-hits-openai-or-anthropic-2ji2)
- [Radicalbit: LLM Data Privacy at Gateway Level](https://radicalbit.ai/resources/blog/llm-data-privacy/)
- [FHE for Encrypted LLMs](https://huggingface.co/blog/encrypted-llm)
- [Confidential Computing for LLM Inference](https://next.redhat.com/2025/10/23/enhancing-ai-inference-security-with-confidential-computing-a-path-to-private-data-inference-with-proprietary-llms/)
- [Stanford Hazy Research — TEE Security](https://hazyresearch.stanford.edu/blog/2025-05-12-security)
- [LLM-Anonymizer for Medical Docs (NEJM AI)](https://ai.nejm.org/doi/full/10.1056/AIdbp2400537)
- [Protect Sensitive Data with Local LLMs](https://www.freecodecamp.org/news/protect-sensitive-data-with-local-llms/)
