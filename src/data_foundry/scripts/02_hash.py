"""

Also a data-quality checkpoint: flags byte-identical duplicate files across
different `code`s, which downstream stages use to avoid describing/translating
the same content twice.
"""

import hashlib
import json
from pathlib import Path

from data_foundry.config import PDF_DIR, PROCESSED_DIR


def compute_sha256(filepath: Path) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def hash_one(pdf_path: Path) -> dict:
    """Pure per-file function, safe to fan out with Prefect .map()."""
    return {
        "sha256": compute_sha256(pdf_path),
        "size_bytes": pdf_path.stat().st_size,
    }


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        print("No PDFs found in data/raw/pdfs/. Run 01_download.py first.")
        return

    hashes_path = PROCESSED_DIR / "hashes.json"
    existing = {}
    if hashes_path.exists():
        with open(hashes_path, encoding="utf-8") as f:
            existing = json.load(f).get("files", {})

    print(f"Hashing {len(pdf_files)} PDFs...")

    hashes = dict(existing)
    for pdf in pdf_files:
        if pdf.name in hashes:
            continue
        hashes[pdf.name] = hash_one(pdf)
        print(f"  {pdf.name}: {hashes[pdf.name]['sha256'][:16]}...")

    hash_to_files: dict[str, list[str]] = {}
    for name, info in hashes.items():
        hash_to_files.setdefault(info["sha256"], []).append(name)
    duplicates = {h: files for h, files in hash_to_files.items() if len(files) > 1}

    result = {
        "total_files": len(pdf_files),
        "unique_hashes": len(hash_to_files),
        "duplicates": duplicates,
        "files": hashes,
    }

    with open(hashes_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(pdf_files)} files hashed.")
    if duplicates:
        print(f"Found {len(duplicates)} duplicate groups:")
        for h, files in duplicates.items():
            print(f"  {h[:16]}... -> {files}")
    else:
        print("No duplicates found.")
    print(f"Output saved to {hashes_path}")


if __name__ == "__main__":
    main()
