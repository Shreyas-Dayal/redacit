"""
Anonymization demo.

Runs all data files in demo_data/ by default, or a specific one by name.

Usage:
    uv run python demo.py                   # run all data files
    uv run python demo.py financial         # run demo_data/financial.py only
    uv run python demo.py general_pii       # run demo_data/general_pii.py only
"""

import importlib
import sys
from pathlib import Path

from src.privacy_wrapper.anonymizer import Anonymizer

DEMO_DATA_DIR = Path(__file__).parent / "demo_data"
anon = Anonymizer()


def run_file(module_name: str) -> None:
    mod = importlib.import_module(f"demo_data.{module_name}")
    title = getattr(mod, "TITLE", module_name)
    samples: list[str] = mod.SAMPLES

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

        assert restored == text, f"Roundtrip failed:\n{text}"
        print("-" * width)

    print()


def available_files() -> list[str]:
    return sorted(
        p.stem for p in DEMO_DATA_DIR.glob("*.py") if p.stem != "__init__"
    )


def main() -> None:
    requested = sys.argv[1] if len(sys.argv) > 1 else None

    if requested:
        if not (DEMO_DATA_DIR / f"{requested}.py").exists():
            print(f"Unknown demo file '{requested}'. Available: {available_files()}")
            sys.exit(1)
        run_file(requested)
    else:
        for name in available_files():
            run_file(name)


if __name__ == "__main__":
    main()
