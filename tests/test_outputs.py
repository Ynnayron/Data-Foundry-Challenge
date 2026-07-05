import json
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR = DATA_DIR / "output"
PDF_DIR = DATA_DIR / "pdfs"

MIN_ENTRIES = 10

EXPECTED_FILES = [
    "catalog.json",
    "metadata.json",
    "hashes.json",
    "descriptions.json",
    "translations.json",
    "description_translations.json",
    "covers.json",
    "localized_catalog.json",
    "universal_metadata.json",
]


def load_json(name: str):
    with open(OUTPUT_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("filename", EXPECTED_FILES)
def test_output_file_exists(filename):
    path = OUTPUT_DIR / filename
    assert path.exists() and path.stat().st_size > 0, f"{filename} missing or empty"


def test_minimum_pdfs():
    assert len(list(PDF_DIR.glob("*.pdf"))) >= MIN_ENTRIES


def test_localized_catalog():
    data = load_json("localized_catalog.json")
    assert len(data) >= MIN_ENTRIES
    for entry in data:
        assert entry.get("id") and entry.get("title", {}).get("pt")


def test_universal_metadata():
    data = load_json("universal_metadata.json")
    assert len(data) >= MIN_ENTRIES
    for entry in data:
        assert entry.get("id") and entry.get("document_hash")


def test_outputs_consistent():
    loc_ids = {e["id"] for e in load_json("localized_catalog.json")}
    uni_ids = {e["id"] for e in load_json("universal_metadata.json")}
    cat_ids = {e["code"] for e in load_json("catalog.json")}
    assert loc_ids == uni_ids == cat_ids
