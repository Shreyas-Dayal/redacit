# PyPI Packaging Checklist

Status: **Code is production-ready, packaging metadata is not.**
192 tests passing. Estimated effort: 4-6 hours.

---

## Priority 1 — Blocking (must fix before first publish)

### 1.1 Create LICENSE file

Create `LICENSE` at project root with MIT text (compatible with all deps).

```
MIT License

Copyright (c) 2024 <Your Name>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### 1.2 Add missing pyproject.toml metadata

Add these fields to `[project]` section:

```toml
readme = "README.md"
license = "MIT"
authors = [
    { name = "Your Name", email = "you@example.com" },
]
keywords = [
    "privacy", "pii", "anonymization", "llm", "presidio",
    "openai", "anthropic", "gemini", "data-privacy", "security",
]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Natural Language :: English",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Security",
    "Topic :: Software Development :: Libraries :: Python Modules",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Typing :: Typed",
]

[project.urls]
Homepage = "https://github.com/<your-username>/redacit"
Repository = "https://github.com/<your-username>/redacit"
Documentation = "https://github.com/<your-username>/redacit#readme"
Issues = "https://github.com/<your-username>/redacit/issues"
Changelog = "https://github.com/<your-username>/redacit/releases"
```

### 1.3 Create MANIFEST.in

Create `MANIFEST.in` at project root to control what goes into the sdist:

```
include README.md
include LICENSE

# Exclude planning docs, demo files, and test data from the package
exclude RESTRUCTURE_PLAN.md
exclude IMPLEMENTATION_PLAN.md
exclude PRIVACY_LAYER_PLAN.md
exclude PYPI_PACKAGING_CHECKLIST.md
exclude demo.py
exclude main.py
recursive-exclude demo_data *
recursive-exclude tests *
recursive-exclude * __pycache__
recursive-exclude * *.pyc
```

---

## Priority 2 — High (fix before first publish)

### 2.1 Fix hardcoded version in server.py

**Current** (`src/redacit/server.py` line 45):
```python
app = FastAPI(
    title="redacit",
    description="Privacy-preserving LLM proxy with PII anonymization.",
    version="0.1.0",  # ← hardcoded
)
```

**Fix** — use `importlib.metadata`:
```python
from importlib.metadata import version as pkg_version

app = FastAPI(
    title="redacit",
    description="Privacy-preserving LLM proxy with PII anonymization.",
    version=pkg_version("redacit"),
)
```

### 2.2 Clean up stale plan files

Three planning docs are committed but no longer relevant:

| File | Size | Action |
|---|---|---|
| `RESTRUCTURE_PLAN.md` | 13.5 KB | Delete or move to `docs/history/` |
| `IMPLEMENTATION_PLAN.md` | 29 KB | Delete or move to `docs/history/` |
| `PRIVACY_LAYER_PLAN.md` | 9.4 KB | Delete or move to `docs/history/` |

If keeping for history, they're excluded from the package by MANIFEST.in
but still clutter the repo root.

### 2.3 Verify package builds cleanly

```bash
# Build the sdist and wheel
uv build

# Check the contents — verify no plan files, demo data, or tests
tar tzf dist/redacit-0.1.0.tar.gz | head -30
unzip -l dist/redacit-0.1.0-py3-none-any.whl | head -30

# Verify the wheel installs and imports correctly
pip install dist/redacit-0.1.0-py3-none-any.whl
python -c "from redacit import Anonymizer; print('OK')"
```

---

## Priority 3 — Recommended (before or shortly after first publish)

### 3.1 Create GitHub Actions publish workflow

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - "v*"

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install uv
      - run: uv sync
      - run: uv run pytest

  publish:
    needs: test
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install build
      - run: python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

### 3.2 Configure PyPI trusted publisher

1. Go to https://pypi.org → Your Account → Publishing
2. Add pending publisher:
   - PyPI project name: `redacit`
   - GitHub owner: `<your-username>`
   - Repository: `redacit`
   - Workflow: `publish.yml`
   - Environment: `pypi`

### 3.3 Create GitHub Actions test workflow

Create `.github/workflows/test.yml`:

```yaml
name: Tests

on:
  push:
    branches: [master]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install uv
      - run: uv sync
      - run: uv run pytest -q
```

### 3.4 Test with TestPyPI first

```bash
# Build
uv build

# Upload to TestPyPI
uv publish --publish-url https://test.pypi.org/legacy/

# Verify install from TestPyPI
pip install -i https://test.pypi.org/simple/ redacit
python -c "from redacit import anonymize; print(anonymize('test@test.com'))"
```

---

## Release workflow (after all fixes)

```bash
# 1. Ensure all tests pass
uv run pytest

# 2. Bump version in pyproject.toml (single source of truth)
#    e.g., version = "0.1.0"

# 3. Commit and tag
git add -A
git commit -m "release: v0.1.0"
git tag v0.1.0
git push origin master --tags

# 4. GitHub Actions builds, tests, and publishes to PyPI automatically

# 5. Verify
pip install redacit
python -c "from redacit import anonymize; print('Published!')"
```

---

## What's already done (no action needed)

- [x] 192 tests passing
- [x] Clean src/ layout with proper `__init__.py` files
- [x] All 22 public API exports in `__all__`
- [x] Optional deps properly guarded (FastAPI, LiteLLM, Anthropic, Gemini)
- [x] CLI entry point working (`redacit`)
- [x] No hardcoded secrets or API keys
- [x] `.env` in `.gitignore`
- [x] Comprehensive README with correct examples
- [x] Python 3.11+ requirement specified
- [x] Build system configured (setuptools)
- [x] Optional extras defined (model-sm, model-md, model-lg, server, litellm)
