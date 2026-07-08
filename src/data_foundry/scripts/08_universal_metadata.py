""" assemble universal_metadata.json (language-independent dataset).
"""

import json

from data_foundry.config import PDF_DIR, PROCESSED_DIR, RAW_DIR, RUN_DIR, ensure_dirs
from data_foundry.quality import (
    build_quality_report,
    count_missing,
    dedupe_by_key,
    normalize_record,
    validate_records,
)
from data_foundry.schemas import UniversalMetadataEntry


def load_json(base, name: str) -> dict | list:
    path = base / name
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {} if name != "catalog.json" else []


def assemble_universal_metadata(catalog: list, metadata: dict, hashes: dict, covers: dict) -> list[dict]:
    records = []
    for entry in catalog:
        code = entry["code"]
        meta = metadata.get(code, {})
        file_hash = hashes.get(f"{code}.pdf", {})
        cover = covers.get(code)

        accesses_raw = meta.get("accesses") or entry.get("accesses", "0")
        try:
            accesses = int(str(accesses_raw).replace(",", "").replace(".", "").strip())
        except ValueError:
            accesses = None

        size_bytes = file_hash.get("size_bytes")
        if not size_bytes:
            pdf_path = PDF_DIR / f"{code}.pdf"
            if pdf_path.exists():
                size_bytes = pdf_path.stat().st_size

        record = {
            "id": code,
            "cover_path": cover.get("path") if cover else None,
            "cover_hash": cover.get("hash") if cover else None,
            "document_hash": file_hash.get("sha256"),
            "accesses": accesses,
            "size_bytes": size_bytes,
            "category": meta.get("category"),
            "year": meta.get("year"),
        }
        records.append(normalize_record(record))
    return records


def main():
    ensure_dirs()

    catalog = load_json(RAW_DIR, "catalog.json")
    if not catalog:
        print("catalog.json not found")
        return

    metadata = load_json(RAW_DIR, "metadata.json")
    hashes_data = load_json(PROCESSED_DIR, "hashes.json")
    hashes = hashes_data.get("files", {}) if isinstance(hashes_data, dict) else {}
    covers = load_json(PROCESSED_DIR, "covers.json")

    metadata_records = assemble_universal_metadata(catalog, metadata, hashes, covers)

    # Dedup by document_hash catches byte-identical PDFs registered under different codes.
    deduped, dropped = dedupe_by_key(
        metadata_records, key_fn=lambda r: r["document_hash"]
    )
    valid, errors = validate_records(deduped, UniversalMetadataEntry)
    missing = count_missing(valid, ["document_hash", "cover_path", "category", "year"])

    report = build_quality_report(
        stage="universal_metadata",
        total_in=len(metadata_records),
        duplicates_dropped=len(dropped),
        validation_errors=errors,
        missing_fields=missing,
    )

    output_path = RUN_DIR / "universal_metadata.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(valid, f, ensure_ascii=False, indent=2)

    quality_path = RUN_DIR / "universal_metadata.quality.json"
    with open(quality_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    with_hash = sum(1 for r in valid if r["document_hash"])
    with_cover = sum(1 for r in valid if r["cover_path"])
    print(f"Done. {len(valid)} entries assembled.")
    print(f"  With hash: {with_hash}, with cover: {with_cover}")
    if dropped:
        print(f"  Dropped {len(dropped)} duplicate document(s) (identical content hash).")
    if errors:
        print(f"  {len(errors)} record(s) failed schema validation, see {quality_path.name}")
    print(f"Output saved to {output_path}")


if __name__ == "__main__":
    main()
