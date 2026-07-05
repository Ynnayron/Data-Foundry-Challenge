import hashlib
import json
from pathlib import Path

from data_foundry.config import (
    OUTPUT_DIR,
    PDF_DIR,
)


def compute_sha256(filepath: Path) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        print("No PDFs found in data/pdfs/. Run 01_download.py first.")
        return

    print(f"Hashing {len(pdf_files)} PDFs...")

    hashes = {}
    hash_to_files: dict[str, list[str]] = {}

    for pdf in pdf_files:
        h = compute_sha256(pdf)
        hashes[pdf.name] = {
            "sha256": h,
            "size_bytes": pdf.stat().st_size,
        }
        hash_to_files.setdefault(h, []).append(pdf.name)
        print(f"  {pdf.name}: {h[:16]}...")

    duplicates = {h: files for h, files in hash_to_files.items() if len(files) > 1}

    result = {
        "total_files": len(pdf_files),
        "unique_hashes": len(hash_to_files),
        "duplicates": duplicates,
        "files": hashes,
    }

    output_path = OUTPUT_DIR / "hashes.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(pdf_files)} files hashed.")
    if duplicates:
        print(f"Found {len(duplicates)} duplicate groups:")
        for h, files in duplicates.items():
            print(f"  {h[:16]}... → {files}")
    else:
        print("No duplicates found.")
    print(f"Output saved to {output_path}")


if __name__ == "__main__":
    main()
