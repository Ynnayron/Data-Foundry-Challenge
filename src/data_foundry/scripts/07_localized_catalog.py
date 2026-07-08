"""Stage 7 - assemble localized_catalog.json (language-dependent dataset).

Reads from RAW (catalog) + PROCESSED (translations/descriptions), writes the
versioned output into the current RUN_DIR, and applies the data-quality gate:
normalization, dedup by id, and schema validation.
"""

import json

from data_foundry.config import PROCESSED_DIR, RAW_DIR, RUN_DIR, ensure_dirs
from data_foundry.quality import (
    build_quality_report,
    count_missing,
    dedupe_by_key,
    normalize_record,
    validate_records,
)
from data_foundry.schemas import LocalizedCatalogEntry


def load_json(base, name: str) -> dict | list:
    path = base / name
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {} if name != "catalog.json" else []


def assemble_localized_catalog(
    catalog: list, translations: dict, descriptions: dict, desc_translations: dict
) -> list[dict]:
    localized = []
    for entry in catalog:
        code = entry["code"]
        title_trans = translations.get(code, {})
        desc_data = descriptions.get(code, {})
        desc_trans = desc_translations.get(code, {})

        record = {
            "id": code,
            "title": {
                "pt": entry["title"],
                "en": title_trans.get("en"),
                "es": title_trans.get("es"),
                "fr": title_trans.get("fr"),
            },
            "description": {
                "pt": desc_data.get("description"),
                "en": desc_trans.get("en"),
                "es": desc_trans.get("es"),
                "fr": desc_trans.get("fr"),
            },
            "author": entry.get("author"),
            "source": entry.get("source"),
        }
        localized.append(normalize_record(record))
    return localized


def main():
    ensure_dirs()

    catalog = load_json(RAW_DIR, "catalog.json")
    if not catalog:
        print("catalog.json not found. Run 01_download.py first.")
        return

    translations = load_json(PROCESSED_DIR, "translations.json")
    descriptions = load_json(PROCESSED_DIR, "descriptions.json")
    desc_translations = load_json(PROCESSED_DIR, "description_translations.json")

    localized = assemble_localized_catalog(
        catalog, translations, descriptions, desc_translations
    )

    deduped, dropped = dedupe_by_key(localized, key_fn=lambda r: r["id"])
    valid, errors = validate_records(deduped, LocalizedCatalogEntry)
    missing = count_missing(valid, ["author", "source"])

    report = build_quality_report(
        stage="localized_catalog",
        total_in=len(localized),
        duplicates_dropped=len(dropped),
        validation_errors=errors,
        missing_fields=missing,
    )

    output_path = RUN_DIR / "localized_catalog.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(valid, f, ensure_ascii=False, indent=2)

    quality_path = RUN_DIR / "localized_catalog.quality.json"
    with open(quality_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    complete = sum(1 for r in valid if r["title"].get("en") and r["description"].get("pt"))
    print(f"Done. {len(valid)} entries assembled ({complete} fully localized).")
    if dropped:
        print(f"  Dropped {len(dropped)} duplicate id(s).")
    if errors:
        print(f"  {len(errors)} record(s) failed schema validation, see {quality_path.name}")
    print(f"Output saved to {output_path}")


if __name__ == "__main__":
    main()
