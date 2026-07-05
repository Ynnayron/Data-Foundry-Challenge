import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"

STEPS = [
    ("01_download.py", "Scrape catalog and download PDFs"),
    ("02_hash.py", "Calculate document hashes"),
    ("03_describe.py", "Generate descriptions via vision LLM"),
    ("04_translate.py", "Translate titles"),
    ("05_translate_descriptions.py", "Translate descriptions"),
    ("06_covers.py", "Extract cover pages"),
    ("07_localized_catalog.py", "Assemble localized catalog"),
    ("08_universal_metadata.py", "Assemble universal metadata"),
]


def run_step(script: str, description: str) -> bool:
    print(f"\n{'=' * 60}")
    print(f"  {description}")
    print(f"  Running: {script}")
    print(f"{'=' * 60}\n")

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script)],
        cwd=str(SCRIPTS_DIR.parent),
    )
    return result.returncode == 0


def main():
    print("Domínio Público Data Pipeline")
    print("=" * 60)

    results = {}
    for script, description in STEPS:
        success = run_step(script, description)
        results[script] = "ok" if success else "failed"

        if not success:
            print(f"\nStep failed: {script}. Stopping pipeline.")
            break

    print(f"\n{'=' * 60}")
    print("Pipeline Summary")
    print(f"{'=' * 60}")
    for script, status in results.items():
        icon = {"ok": "+", "failed": "X"}[status]
        print(f"  [{icon}] {script}: {status}")


if __name__ == "__main__":
    main()
