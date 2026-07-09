import json
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
PDF_DIR = RAW_DIR / "pdfs"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUT_DIR = DATA_DIR / "output"
LATEST_DIR = OUTPUT_DIR / "latest"

MIN_ENTRIES = 10

EXPECTED_RAW_FILES = ["catalog.json", "metadata.json"]
EXPECTED_PROCESSED_FILES = [
    "hashes.json",
    "descriptions.json",
    "translations.json",
    "description_translations.json",
    "covers.json",
]
EXPECTED_RUN_FILES = ["localized_catalog.json", "universal_metadata.json"]


def load_json(base: Path, name: str):
    with open(base / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("filename", EXPECTED_RAW_FILES)
def test_raw_file_exists(filename):
    path = RAW_DIR / filename
    assert path.exists() and path.stat().st_size > 0, f"{filename} missing or empty"


@pytest.mark.parametrize("filename", EXPECTED_PROCESSED_FILES)
def test_processed_file_exists(filename):
    path = PROCESSED_DIR / filename
    assert path.exists() and path.stat().st_size > 0, f"{filename} missing or empty"


@pytest.mark.parametrize("filename", EXPECTED_RUN_FILES)
def test_latest_run_file_exists(filename):
    path = LATEST_DIR / filename
    assert path.exists() and path.stat().st_size > 0, f"{filename} missing or empty"


def test_latest_pointer_exists():
    assert LATEST_DIR.exists(), "data/output/latest missing — no successful run yet"


def test_minimum_pdfs():
    assert len(list(PDF_DIR.glob("*.pdf"))) >= MIN_ENTRIES


def test_localized_catalog():
    data = load_json(LATEST_DIR, "localized_catalog.json")
    assert len(data) >= MIN_ENTRIES
    for entry in data:
        assert entry.get("id") and entry.get("title", {}).get("pt")


def test_universal_metadata():
    data = load_json(LATEST_DIR, "universal_metadata.json")
    assert len(data) >= MIN_ENTRIES
    for entry in data:
        assert entry.get("id") and entry.get("document_hash")


def test_outputs_consistent():
    loc_ids = {e["id"] for e in load_json(LATEST_DIR, "localized_catalog.json")}
    uni_ids = {e["id"] for e in load_json(LATEST_DIR, "universal_metadata.json")}
    cat_ids = {e["code"] for e in load_json(RAW_DIR, "catalog.json") if e.get("downloaded")}
    # universal_metadata dedupes by document_hash, so it may be <= cat_ids;
    # localized_catalog dedupes by id, so it should match 1:1 with downloaded books.
    assert loc_ids == cat_ids
    assert uni_ids <= cat_ids


def test_no_duplicate_document_hashes():
    data = load_json(LATEST_DIR, "universal_metadata.json")
    hashes = [e["document_hash"] for e in data if e.get("document_hash")]
    assert len(hashes) == len(set(hashes)), "duplicate document_hash values leaked into output"


def test_run_is_versioned():
    assert LATEST_DIR.is_symlink() or LATEST_DIR.is_dir()
    runs_dir = DATA_DIR / "runs"
    assert runs_dir.exists()
    run_folders = [p for p in runs_dir.iterdir() if p.is_dir()]
    assert len(run_folders) >= 1
    for run_folder in run_folders:
        assert (run_folder / "manifest.json").exists()
