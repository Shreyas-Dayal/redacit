# Restructure Plan — wrapper-llm

> Generated 2026-03-15, based on exact current state of `refac/repo` branch.
> Cross-referenced against `feat/financial_specialisation` which is the next
> planned merge. Scope: structural changes only — no new feature implementations.

---

## Baseline Decisions

| Question | Decision | Reason |
|---|---|---|
| Starting branch | `refac/repo` | Clean, confirmed free of unintended changes |
| `feat/financial_specialisation` | Merged in Phase 0 | It's directly ahead; brings recognizers + JSON support that restructure builds on |
| Package name | `wrapper-llm` (unchanged) | User preference |
| `main.py` | Repurposed as CLI entry | Already a stub; becomes `uv run python main.py` equivalent |
| `demo.py` | Thin shim | Format logic moves into the package; demo.py just imports and calls |
| Test import paths | Fixed to `privacy_wrapper.*` | Cleaner, matches real-world SDK usage; done once and done |
| Feature scope | Structural only | Skeletons for CLI and server; no implementations |

---

## Guiding Principles

- **No-touch core** — `anonymizer.py` and all recognizers are correct. They are
  only modified where strictly required by structural changes (e.g. import paths).
- **Additive before destructive** — new files are created and verified before
  old ones are removed or replaced. Every phase is independently testable.
- **Nothing disappears** — every function and class that exists today is still
  reachable after the restructure, either in its new location or via a re-export.
- **Tests stay green** at every commit checkpoint.

---

## Current State (refac/repo)

```
wrapper-llm/
├── pyproject.toml                  no build-system, 4 runtime deps
├── main.py                         stub — prints "Hello from wrapper-llm!"
├── demo.py                         176 lines — runs .py and .csv demos
├── demo_data/
│   ├── general_pii.py
│   ├── financial.py
│   ├── financial_transactions.csv
│   └── financial_transactions.json (sidecar config for the CSV)
├── src/
│   └── privacy_wrapper/
│       ├── __init__.py             exports Anonymizer, PrivacyClient
│       ├── anonymizer.py           core detection engine
│       └── client.py               OpenAI wrapper — single file
└── tests/
    ├── fixtures/
    │   ├── __init__.py
    │   └── sample_prompts.py       18 sample dicts
    ├── test_anonymizer.py          15 unit tests
    └── test_samples.py             parametrised leakage + roundtrip tests
```

`feat/financial_specialisation` adds (5 commits ahead, fast-forward eligible):
- `src/privacy_wrapper/recognizers/` — 4 custom recognizers + `__init__.py`
- Updated `anonymizer.py` — registers custom recognizers, adds per-call `score_threshold`
- Updated `demo.py` — adds `run_json`, `_flatten`, `_unflatten`, `_load_sidecar`, `_anonymize_flat`
- New demo data — `financial_records.json`, `financial_records.config.json`
- Updated sidecar — `financial_transactions.json` uses custom entity types
- New tests — `tests/unit/__init__.py`, `tests/unit/test_recognizers.py` (25 tests)
- Updated fixtures — `sample_prompts.py` extended with new entity samples

---

## Target State

```
wrapper-llm/
├── pyproject.toml                  CHANGED — build-system, typer, optional extras, scripts
├── main.py                         CHANGED — calls privacy_wrapper.cli:app
├── demo.py                         CHANGED — thin shim, imports from package
├── demo_data/                      NO-TOUCH
│
├── src/
│   └── privacy_wrapper/
│       ├── __init__.py             CHANGED — clean public API + convenience functions
│       ├── anonymizer.py           NO-TOUCH (post-merge state from feat/financial_specialisation)
│       ├── _types.py               NEW — shared TypedDicts and LLMClient Protocol
│       ├── session.py              NEW — PrivacySession for multi-turn memory
│       ├── audit.py                NEW — AuditLogger (JSONL, metadata only)
│       ├── cli.py                  NEW — typer app skeleton (anonymize, serve, stats commands)
│       ├── server.py               NEW — FastAPI app skeleton (POST /anonymize, /deanonymize, /chat)
│       │
│       ├── client/                 NEW DIR (replaces client.py)
│       │   ├── __init__.py         re-exports all three clients
│       │   ├── base.py             BaseLLMClient — owns anonymize→call→deanonymize lifecycle
│       │   ├── openai_client.py    PrivacyClient (inherits base) + PrivacyOpenAI proxy
│       │   └── litellm_client.py   LiteLLMPrivacyClient (lazy litellm import)
│       │
│       ├── formats/                NEW DIR
│       │   ├── __init__.py         re-exports CsvAnonymizer, JsonAnonymizer
│       │   ├── _helpers.py         flatten, unflatten, load_sidecar, anonymize_flat (from demo.py)
│       │   ├── csv.py              CsvAnonymizer — iterator-based, yields CsvRowResult
│       │   └── json_format.py      JsonAnonymizer — iterator-based, yields JsonRecordResult
│       │
│       └── recognizers/            NO-TOUCH (post-merge state)
│           ├── __init__.py
│           ├── api_key.py
│           ├── bank_account.py
│           ├── ein.py
│           └── routing_number.py
│
└── tests/
    ├── fixtures/
    │   ├── __init__.py             NO-TOUCH
    │   └── sample_prompts.py       NO-TOUCH (post-merge state)
    ├── test_anonymizer.py          CHANGED — import path only (src.privacy_wrapper → privacy_wrapper)
    ├── test_samples.py             CHANGED — import path only
    ├── unit/
    │   ├── __init__.py             NO-TOUCH (post-merge)
    │   └── test_recognizers.py     NO-TOUCH (post-merge) + import path fix
    ├── unit/test_client.py         NEW — tests for PrivacyClient, PrivacyOpenAI (mocked)
    └── unit/test_formats.py        NEW — tests for CsvAnonymizer, JsonAnonymizer
```

---

## File-by-File Specification

### `src/privacy_wrapper/_types.py` — NEW

Shared type definitions. Prevents circular imports and gives a single source of
truth for TypedDicts used by both format handlers and the client layer.

```python
from typing import TypedDict, Protocol, Iterator, runtime_checkable

class FieldConfig(TypedDict, total=False):
    entities: list[str]        # entity types to detect for this field
    skip: bool                 # if True, skip anonymization
    score_threshold: float     # per-field confidence override

class SidecarConfig(TypedDict, total=False):
    title: str
    fields: dict[str, FieldConfig]

@runtime_checkable
class LLMClient(Protocol):
    def chat(self, prompt: str, system: str | None = None) -> str: ...
    def stream(self, prompt: str, system: str | None = None) -> Iterator[str]: ...
```

---

### `src/privacy_wrapper/session.py` — NEW

Stateless per-call behaviour is the default. A `PrivacySession` instance enables
consistent deanonymization across multiple turns.

```python
@dataclass
class PrivacySession:
    mapping: dict[str, str] = field(default_factory=dict)

    def update(self, new_mapping: dict[str, str]) -> None:
        """Merge; existing keys never overwritten."""
        for k, v in new_mapping.items():
            self.mapping.setdefault(k, v)

    def clear(self) -> None: ...
    def __len__(self) -> int: ...
```

---

### `src/privacy_wrapper/audit.py` — NEW

Append-only JSONL audit log. Never records original text or mapping values —
only metadata (input hash, entity counts, provider, model).

```python
class AuditLogger:
    def __init__(self, path: str | Path | IO[str]) -> None: ...

    def log(self, input_text, mapping, provider="unknown", model="unknown") -> None:
        # Writes: {"ts":..., "input_hash":..., "entity_counts":...,
        #          "total_redacted":..., "provider":..., "model":...}

    def close(self) -> None: ...
    def __enter__ / __exit__: ...   # context manager
```

---

### `src/privacy_wrapper/client/base.py` — NEW

All LLM provider subclasses implement only `_call()`. The base owns the full
anonymize → call → deanonymize cycle, session merging, and audit logging.

```python
class BaseLLMClient(ABC):
    def __init__(
        self,
        anonymizer: Anonymizer | None = None,
        session: PrivacySession | None = None,
        audit_logger: AuditLogger | None = None,
    ): ...

    def chat(self, prompt: str, system: str | None = None) -> str:
        # anonymize → merge session → audit → _call → deanonymize

    def stream(self, prompt: str, system: str | None = None) -> Iterator[str]:
        # buffers full response before deanonymizing (placeholders span tokens)
        # sliding-window optimisation is a future sprint item

    @abstractmethod
    def _call(self, prompt: str, system: str | None) -> str: ...

    def _stream_raw(self, prompt, system) -> Iterator[str]:
        yield self._call(prompt, system)  # default: non-streaming fallback

    def _provider_name(self) -> str: return "unknown"
    def _model_name(self) -> str: return "unknown"
```

---

### `src/privacy_wrapper/client/openai_client.py` — NEW

**PrivacyClient** — identical public surface to the current `client.py`, now
inherits `BaseLLMClient`. Existing code calling `PrivacyClient` is unchanged.

```python
class PrivacyClient(BaseLLMClient):
    def __init__(self, api_key=None, model="gpt-4o-mini",
                 anonymizer=None, session=None, audit_logger=None): ...
    def _call(self, prompt, system) -> str: ...
    def _stream_raw(self, prompt, system) -> Iterator[str]: ...
    def _provider_name(self) -> str: return "openai"
    def _model_name(self) -> str: return self.model
```

**PrivacyOpenAI** — transparent proxy for `openai.OpenAI`. Change one line in
existing code; everything else (tools, response_format, streaming, embeddings)
is identical. Implemented via delegation, not subclassing, for forward-compat
with OpenAI SDK version changes.

```python
class PrivacyOpenAI:
    def __init__(self, *args, anonymizer=None, **kwargs):
        self._inner = OpenAI(*args, **kwargs)
        self.chat = _PrivacyChat(self._inner.chat, anonymizer or Anonymizer())

    def __getattr__(self, name):
        return getattr(self._inner, name)  # audio, beta, embeddings, files, …
```

---

### `src/privacy_wrapper/client/litellm_client.py` — NEW (skeleton)

Routes to any provider via LiteLLM. `litellm` is a lazy import — the package
remains importable without it installed.

```python
class LiteLLMPrivacyClient(BaseLLMClient):
    def __init__(self, model: str, anonymizer=None,
                 session=None, audit_logger=None, **litellm_kwargs): ...
    def _call(self, prompt, system) -> str:
        try: import litellm
        except ImportError:
            raise ImportError("Install with: uv add 'wrapper-llm[litellm]'")
        ...
```

---

### `src/privacy_wrapper/formats/_helpers.py` — NEW (internal)

Private module. Moves these four functions verbatim from `demo.py` with one
change: `_anonymize_flat` receives an `Anonymizer` argument instead of
capturing the module-level `anon` global.

| Function | Current location | Destination |
|---|---|---|
| `_load_sidecar(path)` | `demo.py` | `formats/_helpers.py → load_sidecar()` |
| `_anonymize_flat(row, keys, cfg)` | `demo.py` | `formats/_helpers.py → anonymize_flat(row, keys, cfg, anonymizer)` |
| `_flatten(obj, prefix)` | `demo.py` (feat branch) | `formats/_helpers.py → flatten()` |
| `_unflatten(flat)` | `demo.py` (feat branch) | `formats/_helpers.py → unflatten()` |

Not exported publicly — imported only by `csv.py` and `json_format.py`.

---

### `src/privacy_wrapper/formats/csv.py` — NEW

Iterator-based. Caller controls output (write to file, stream, assert in tests).

```python
@dataclass
class CsvRowResult:
    row_index: int
    original: dict[str, str]
    anonymized: dict[str, str]
    mappings: dict[str, dict[str, str]]   # column → {placeholder: original}

    @property
    def flat_mapping(self) -> dict[str, str]: ...

class CsvAnonymizer:
    def __init__(self, anonymizer: Anonymizer | None = None): ...

    def anonymize_file(
        self,
        input_path: str | Path,
        field_config: dict[str, FieldConfig] | None = None,
    ) -> Iterator[CsvRowResult]: ...

    @staticmethod
    def load_sidecar(path: str | Path) -> tuple[SidecarConfig, dict[str, FieldConfig]]: ...
```

---

### `src/privacy_wrapper/formats/json_format.py` — NEW

```python
@dataclass
class JsonRecordResult:
    record_index: int
    original: dict[str, Any]
    anonymized: dict[str, Any]
    flat_mapping: dict[str, str]

class JsonAnonymizer:
    def __init__(self, anonymizer: Anonymizer | None = None): ...

    def anonymize_records(
        self,
        records: list[dict[str, Any]],
        field_config: dict[str, FieldConfig] | None = None,
    ) -> Iterator[JsonRecordResult]: ...

    def anonymize_file(
        self,
        input_path: str | Path,
        config_path: str | Path | None = None,
    ) -> Iterator[JsonRecordResult]: ...
```

---

### `src/privacy_wrapper/cli.py` — NEW (skeleton only)

Typer app with three commands. Bodies raise `NotImplementedError` in this phase.

```python
import typer
app = typer.Typer(name="privacy-wrapper", help="Anonymize files and text.")

@app.command()
def anonymize(input: Path, output: Path | None, entities: str | None, dry_run: bool): ...

@app.command()
def serve(host: str = "127.0.0.1", port: int = 8080): ...

@app.command()
def stats(path: Path): ...
```

---

### `src/privacy_wrapper/server.py` — NEW (skeleton only)

FastAPI app with four endpoints. Route handlers return `{"status": "not_implemented"}`
in this phase, so the app starts and responds but does no work yet.

```python
from fastapi import FastAPI
app = FastAPI(title="wrapper-llm", version="0.2.0")

@app.get("/health")
@app.post("/anonymize")
@app.post("/deanonymize")
@app.post("/chat")
```

FastAPI is an optional dependency. The module uses a conditional import with a
clear error message if the extra is not installed.

---

### `main.py` — CHANGED

Repurposed from a stub to the CLI entry point.

```python
from privacy_wrapper.cli import app

if __name__ == "__main__":
    app()
```

`uv run python main.py --help` works immediately after install.

---

### `demo.py` — CHANGED (thin shim)

Format logic moves into the package. `demo.py` handles only UI/display concerns.
`run_csv` and `run_json` become wrappers that call `CsvAnonymizer` and
`JsonAnonymizer` and print results, rather than containing the parsing logic
themselves. `run_py` stays inline — it's pure demo scaffolding.

Import changes:
```python
# Before
from src.privacy_wrapper.anonymizer import Anonymizer, AnonymizationResult

# After
from privacy_wrapper.anonymizer import Anonymizer, AnonymizationResult
from privacy_wrapper.formats import CsvAnonymizer, JsonAnonymizer
```

---

### `src/privacy_wrapper/__init__.py` — CHANGED

```python
from .anonymizer import Anonymizer, AnonymizationResult, DEFAULT_ENTITIES
from .client import PrivacyClient, PrivacyOpenAI, LiteLLMPrivacyClient
from .session import PrivacySession
from .audit import AuditLogger
from .formats import CsvAnonymizer, JsonAnonymizer
from .recognizers import build_custom_recognizers

# Module-level convenience — lazy shared Anonymizer instance
def anonymize(text: str, **kwargs) -> tuple[str, dict[str, str]]:
    """One-call anonymize. Returns (anonymized_text, mapping)."""
    ...

def deanonymize(text: str, mapping: dict[str, str]) -> str:
    """One-call deanonymize."""
    ...

__all__ = [
    "Anonymizer", "AnonymizationResult", "DEFAULT_ENTITIES",
    "anonymize", "deanonymize",
    "PrivacyClient", "PrivacyOpenAI", "LiteLLMPrivacyClient",
    "PrivacySession", "AuditLogger",
    "CsvAnonymizer", "JsonAnonymizer",
    "build_custom_recognizers",
]
```

---

### `pyproject.toml` — CHANGED

```toml
[project]
name = "wrapper-llm"          # unchanged
version = "0.2.0"
description = "Privacy-preserving LLM wrapper with local PII anonymization"
requires-python = ">=3.11"
dependencies = [
    "openai>=2.26.0",
    "presidio-analyzer>=2.2.361",
    "presidio-anonymizer>=2.2.361",
    "python-dotenv>=1.2.2",
    "typer>=0.13.0",           # NEW — CLI, always installed
]

[project.optional-dependencies]
server  = ["fastapi>=0.115.0", "uvicorn[standard]>=0.30.0"]
litellm = ["litellm>=1.40.0"]
all     = ["wrapper-llm[server,litellm]"]

[project.scripts]
wrapper-llm = "privacy_wrapper.cli:app"   # installs the CLI command

[build-system]                             # NEW — needed for editable install + CLI scripts
requires      = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[dependency-groups]
dev = [
    "pytest>=9.0.2",
    "pytest-asyncio>=1.3.0",
    "httpx>=0.27.0",           # NEW — for FastAPI TestClient
]

[tool.pytest.ini_options]
pythonpath = ["."]             # kept during transition; removed in Phase 7 after install
...
```

---

## Migration: What Moves Where

| Current location | Destination | Change |
|---|---|---|
| `src/privacy_wrapper/client.py` | `client/openai_client.py` | Inherits `BaseLLMClient`; identical `.chat()` signature |
| `demo.py → _load_sidecar()` | `formats/_helpers.py → load_sidecar()` | Anonymizer no longer global |
| `demo.py → _anonymize_flat()` | `formats/_helpers.py → anonymize_flat()` | Anonymizer injected as arg |
| `demo.py → _flatten()` | `formats/_helpers.py → flatten()` | Verbatim |
| `demo.py → _unflatten()` | `formats/_helpers.py → unflatten()` | Verbatim |
| `demo.py → run_csv()` display logic | Stays in `demo.py` | Calls `CsvAnonymizer`, prints results |
| `demo.py → run_json()` display logic | Stays in `demo.py` | Calls `JsonAnonymizer`, prints results |
| `demo.py → run_py()` | Stays in `demo.py` | Unchanged |
| `main.py` (stub) | Repurposed as CLI entry | Calls `privacy_wrapper.cli:app` |

---

## No-Touch Files

These files are not modified at all (post-merge state is final):

- `src/privacy_wrapper/anonymizer.py`
- `src/privacy_wrapper/recognizers/` — all 5 files
- `tests/unit/test_recognizers.py`
- `tests/fixtures/sample_prompts.py`
- `demo_data/` — all data files

---

## Test Import Path Fix

All test files currently import via the `src.` prefix workaround:
```python
# Before (all test files)
from src.privacy_wrapper.anonymizer import Anonymizer

# After
from privacy_wrapper.anonymizer import Anonymizer
```

Affected files:
- `tests/test_anonymizer.py`
- `tests/test_samples.py`
- `tests/unit/test_recognizers.py`

This requires the package to be installed. In Phase 7, `uv sync` (after adding the
`build-system` block to `pyproject.toml`) installs the package into the virtualenv
so the `src.` prefix is no longer needed. The `pythonpath = ["."]` line in
`pytest.ini_options` is removed at that point.

---

## Implementation Order

Every phase ends with `uv run pytest` passing. Commit at each phase boundary.

### Phase 0 — Merge feat/financial_specialisation
Fast-forward merge from `feat/financial_specialisation` into `refac/repo`.
No conflicts expected (the branch is directly ahead).
Verify all existing tests still pass before proceeding.

**Commit:** `Merge feat/financial_specialisation — custom recognizers and JSON support`

---

### Phase 1 — Foundation types and utilities
1. `src/privacy_wrapper/_types.py` — FieldConfig, SidecarConfig, LLMClient Protocol
2. `src/privacy_wrapper/session.py` — PrivacySession
3. `src/privacy_wrapper/audit.py` — AuditLogger

No imports from any other new file. Tests continue passing unchanged.

**Commits (3):**
- `Add _types.py — shared FieldConfig, SidecarConfig TypedDicts and LLMClient Protocol`
- `Add PrivacySession for multi-turn placeholder mapping persistence`
- `Add AuditLogger — append-only JSONL metadata log, never records raw text`

---

### Phase 2 — Client refactor
4. Create `src/privacy_wrapper/client/` directory
5. `src/privacy_wrapper/client/base.py` — BaseLLMClient
6. `src/privacy_wrapper/client/openai_client.py` — PrivacyClient + PrivacyOpenAI
7. `src/privacy_wrapper/client/litellm_client.py` — LiteLLMPrivacyClient (skeleton)
8. `src/privacy_wrapper/client/__init__.py`
9. Update `src/privacy_wrapper/__init__.py` to import from `client/`
10. **Run tests — must pass**
11. Delete `src/privacy_wrapper/client.py` — only after tests confirm the new package works

> ⚠️ Python cannot have both `client.py` and `client/` with the same stem.
> Steps 4–10 must complete before step 11 runs.

**Commits (2):**
- `Add client/ package with BaseLLMClient, PrivacyClient, PrivacyOpenAI, and LiteLLMPrivacyClient`
- `Remove old client.py — superseded by client/ package`

---

### Phase 3 — Format handlers
12. `src/privacy_wrapper/formats/_helpers.py` — move functions from `demo.py`
13. `src/privacy_wrapper/formats/csv.py` — CsvAnonymizer
14. `src/privacy_wrapper/formats/json_format.py` — JsonAnonymizer
15. `src/privacy_wrapper/formats/__init__.py`
16. Update `demo.py` to import format logic from the package; verify demo runs identically

**Commits (2):**
- `Add formats/ package — CsvAnonymizer, JsonAnonymizer, shared helpers`
- `Update demo.py to delegate format logic to the formats/ package`

---

### Phase 4 — CLI and server skeletons
17. `src/privacy_wrapper/cli.py` — typer app (commands raise NotImplementedError)
18. Update `main.py` to call `privacy_wrapper.cli:app`
19. `src/privacy_wrapper/server.py` — FastAPI skeleton (routes return not_implemented)
20. Update `pyproject.toml` — add build-system, typer dep, optional extras, scripts entry
21. `uv sync` to install the package into the virtualenv

**Commits (2):**
- `Add CLI skeleton (typer) and repurpose main.py as entry point`
- `Add FastAPI server skeleton and update pyproject.toml with build system and optional deps`

---

### Phase 5 — Clean public API and test import fix
22. Update `src/privacy_wrapper/__init__.py` — full exports + `anonymize`/`deanonymize` fns
23. Fix import paths in all test files (`src.privacy_wrapper` → `privacy_wrapper`)
24. Remove `pythonpath = ["."]` from `[tool.pytest.ini_options]`
25. `uv run pytest` — final green run confirms everything

**Commits (2):**
- `Expose clean public API in __init__.py with anonymize/deanonymize convenience functions`
- `Fix test imports — use privacy_wrapper.* now that package is installed`

---

## Architectural Notes

### `client.py` → `client/` rename risk
Python raises an `ImportError` if both `client.py` and `client/` exist with the
same stem. The sequence in Phase 2 (create directory → verify tests → delete
file) eliminates this risk. Never do both in the same step.

### `PrivacyOpenAI` delegation vs subclassing
Delegation via `__getattr__` is chosen over subclassing `openai.OpenAI`. The
OpenAI SDK reorganises its internal resource tree between versions; subclassing
would break on those updates. Delegation is forward-compatible.

Consequence: `isinstance(client, OpenAI)` returns `False` for `PrivacyOpenAI`.
This is documented explicitly. A `.pyi` stub file can be added later for
full type-checker compatibility.

### `LiteLLMPrivacyClient` lazy import
`import litellm` is deferred to `_call()` so the package is importable without
litellm installed. The `ImportError` surfaces at runtime with a clear install
message: `"Install with: uv add 'wrapper-llm[litellm]'"`.

### Server skeleton guards
`server.py` uses a conditional import:
```python
try:
    from fastapi import FastAPI
except ImportError:
    raise ImportError("Install with: uv add 'wrapper-llm[server]'")
```
This prevents `import privacy_wrapper.server` from failing when FastAPI is not
installed, making the rest of the package usable without the server extra.

### Module-level `anonymize()` singleton
The convenience `anonymize()` function in `__init__.py` uses a lazy module-level
`Anonymizer` instance. This is safe (Anonymizer holds no per-call state), but
users who configure a custom Anonymizer should instantiate `Anonymizer` directly
rather than using the convenience function. This is documented in the docstring.

### `score_threshold` in `anonymize_flat`
The `score_threshold` field in `FieldConfig` maps directly to the per-call
`score_threshold` parameter in `Anonymizer.anonymize()`, which was added in
`feat/financial_specialisation`. The format helpers pass it through unchanged;
no additional wiring is needed.
