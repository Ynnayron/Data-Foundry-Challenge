#Event-driven orchestration of the pipeline, built on Prefect.

import importlib
import json
import shutil
from pathlib import Path

from prefect import flow, get_run_logger, task
from prefect.futures import wait
from prefect.task_runners import ThreadPoolTaskRunner

from data_foundry import config
from data_foundry.quality import (
    build_quality_report,
    count_missing,
    dedupe_by_key,
    normalize_record,
    validate_records,
)
from data_foundry.schemas import LocalizedCatalogEntry, UniversalMetadataEntry


def _load(name: str):
    return importlib.import_module(f"data_foundry.scripts.{name}")


download_mod = _load("01_download")
hash_mod = _load("02_hash")
describe_mod = _load("03_describe")
translate_mod = _load("04_translate")
translate_desc_mod = _load("05_translate_descriptions")
covers_mod = _load("06_covers")


def _load_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _dump_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Stage 1: scrape + download (event: triggered by nothing upstream — the source)
# --------------------------------------------------------------------------


@task(name="scrape_catalog", retries=2, retry_delay_seconds=10)
def scrape_catalog_task() -> list[dict]:
    return download_mod.scrape_catalog()


@task(name="download_book", retries=2, retry_delay_seconds=5)
def download_book_task(entry: dict) -> tuple[dict, dict]:
    return download_mod.process_entry(entry)


@task(name="persist_raw")
def persist_raw_task(results: list[tuple[dict, dict]]) -> list[dict]:
    logger = get_run_logger()
    catalog_path = config.RAW_DIR / "catalog.json"
    metadata_path = config.RAW_DIR / "metadata.json"

    catalog_by_code = {e["code"]: e for e in _load_json(catalog_path, [])}
    all_metadata = _load_json(metadata_path, {})

    for entry, meta in results:
        catalog_by_code[entry["code"]] = entry
        all_metadata[entry["code"]] = meta

    catalog = list(catalog_by_code.values())
    _dump_json(catalog_path, catalog)
    _dump_json(metadata_path, all_metadata)

    downloaded = sum(1 for e in catalog if e.get("downloaded"))
    logger.info(f"Raw layer: {downloaded}/{len(catalog)} PDFs available")
    return catalog


# --------------------------------------------------------------------------
# Stage 2: hash (event: reacts to PDFs present in the raw layer)
# --------------------------------------------------------------------------


@task(name="hash_book")
def hash_book_task(pdf_path: Path) -> tuple[str, dict]:
    return pdf_path.name, hash_mod.hash_one(pdf_path)


@task(name="persist_hashes")
def persist_hashes_task(results: list[tuple[str, dict]]) -> dict:
    hashes_path = config.PROCESSED_DIR / "hashes.json"
    existing = _load_json(hashes_path, {"files": {}}).get("files", {})
    for name, info in results:
        existing[name] = info

    hash_to_files: dict[str, list[str]] = {}
    for name, info in existing.items():
        hash_to_files.setdefault(info["sha256"], []).append(name)
    duplicates = {h: files for h, files in hash_to_files.items() if len(files) > 1}

    result = {
        "total_files": len(existing),
        "unique_hashes": len(hash_to_files),
        "duplicates": duplicates,
        "files": existing,
    }
    _dump_json(hashes_path, result)
    return result


# --------------------------------------------------------------------------
# Stage 3/4/5: describe + translate (event: reacts to catalog + PDFs present;
# LLM concurrency is bounded inside each pure function via a semaphore)
# --------------------------------------------------------------------------


@task(name="describe_book", tags=["llm"], retries=1)
def describe_book_task(code: str, pdf_path: Path, title: str, meta: dict | None) -> tuple[str, dict]:
    return code, describe_mod.describe_one(pdf_path, title, meta)


@task(name="persist_descriptions")
def persist_descriptions_task(results: list[tuple[str, dict]]) -> dict:
    path = config.PROCESSED_DIR / "descriptions.json"
    descriptions = _load_json(path, {})
    for code, result in results:
        descriptions[code] = result
    _dump_json(path, descriptions)
    return descriptions


@task(name="translate_title", tags=["llm"], retries=1)
def translate_title_task(code: str, title: str, meta: dict | None) -> tuple[str, dict]:
    return code, translate_mod.translate_entry(title, meta)


@task(name="persist_translations")
def persist_translations_task(results: list[tuple[str, dict]]) -> dict:
    path = config.PROCESSED_DIR / "translations.json"
    translations = _load_json(path, {})
    for code, result in results:
        translations[code] = result
    _dump_json(path, translations)
    return translations


@task(name="translate_description", tags=["llm"], retries=1)
def translate_description_task(code: str, description: str) -> tuple[str, dict]:
    return code, translate_desc_mod.translate_description(description)


@task(name="persist_description_translations")
def persist_description_translations_task(results: list[tuple[str, dict]]) -> dict:
    path = config.PROCESSED_DIR / "description_translations.json"
    translations = _load_json(path, {})
    for code, result in results:
        translations[code] = result
    _dump_json(path, translations)
    return translations


# --------------------------------------------------------------------------
# Stage 6: covers (event: reacts to PDFs present)
# --------------------------------------------------------------------------


@task(name="extract_cover")
def extract_cover_task(code: str, pdf_path: Path) -> tuple[str, dict | None]:
    cover_path, img_hash = covers_mod.extract_cover(pdf_path)
    if cover_path is None:
        return code, None
    return code, {"path": str(cover_path.relative_to(config.PROCESSED_DIR.parent)), "hash": img_hash}


@task(name="persist_covers")
def persist_covers_task(results: list[tuple[str, dict | None]]) -> dict:
    path = config.PROCESSED_DIR / "covers.json"
    covers = _load_json(path, {})
    for code, result in results:
        covers[code] = result
    _dump_json(path, covers)
    return covers


# --------------------------------------------------------------------------
# Stage 7/8: assemble final, versioned datasets (event: reacts to all upstream
# artifacts being present; this is the only place that writes to RUN_DIR)
# --------------------------------------------------------------------------


@task(name="assemble_localized_catalog")
def assemble_localized_catalog_task(
    catalog: list, translations: dict, descriptions: dict, desc_translations: dict
) -> dict:
    logger = get_run_logger()
    localized_mod = _load("07_localized_catalog")
    localized = localized_mod.assemble_localized_catalog(
        catalog, translations, descriptions, desc_translations
    )
    deduped, dropped = dedupe_by_key(localized, key_fn=lambda r: r["id"])
    valid, errors = validate_records(deduped, LocalizedCatalogEntry)
    missing = count_missing(valid, ["author", "source"])
    report = build_quality_report(
        "localized_catalog", len(localized), len(dropped), errors, missing
    )

    _dump_json(config.RUN_DIR / "localized_catalog.json", valid)
    _dump_json(config.RUN_DIR / "localized_catalog.quality.json", report)
    logger.info(f"localized_catalog: {len(valid)} valid, {len(dropped)} dup, {len(errors)} invalid")
    return report


@task(name="assemble_universal_metadata")
def assemble_universal_metadata_task(catalog: list, metadata: dict, hashes: dict, covers: dict) -> dict:
    logger = get_run_logger()
    universal_mod = _load("08_universal_metadata")
    records = universal_mod.assemble_universal_metadata(catalog, metadata, hashes, covers)
    deduped, dropped = dedupe_by_key(records, key_fn=lambda r: r["document_hash"])
    valid, errors = validate_records(deduped, UniversalMetadataEntry)
    missing = count_missing(valid, ["document_hash", "cover_path", "category", "year"])
    report = build_quality_report(
        "universal_metadata", len(records), len(dropped), errors, missing
    )

    _dump_json(config.RUN_DIR / "universal_metadata.json", valid)
    _dump_json(config.RUN_DIR / "universal_metadata.quality.json", report)
    logger.info(f"universal_metadata: {len(valid)} valid, {len(dropped)} dup, {len(errors)} invalid")
    return report


@task(name="finalize_run")
def finalize_run_task(loc_report: dict, uni_report: dict) -> str:
    manifest = {
        "run_id": config.RUN_ID,
        "localized_catalog": loc_report,
        "universal_metadata": uni_report,
    }
    _dump_json(config.RUN_DIR / "manifest.json", manifest)

    latest_link = config.OUTPUT_DIR / "latest"
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if latest_link.is_symlink() or latest_link.exists():
        if latest_link.is_dir() and not latest_link.is_symlink():
            shutil.rmtree(latest_link)
        else:
            latest_link.unlink()
    try:
        latest_link.symlink_to(config.RUN_DIR, target_is_directory=True)
    except OSError:
        shutil.copytree(config.RUN_DIR, latest_link)

    return config.RUN_ID


# --------------------------------------------------------------------------
# The flow
# --------------------------------------------------------------------------


@flow(name="data-foundry-pipeline", task_runner=ThreadPoolTaskRunner(max_workers=config.MAX_DOWNLOAD_WORKERS))
def data_foundry_flow() -> str:
    logger = get_run_logger()
    config.ensure_dirs()
    logger.info(f"Starting run {config.RUN_ID}")

    # --- download layer ---
    # --- download layer ---
    entries = scrape_catalog_task()
    if config.MAX_BOOKS:
        entries = entries[: config.MAX_BOOKS]
        logger.info(f"MAX_BOOKS set: limiting this run to {len(entries)} book(s)")
    download_futures = download_book_task.map(entries)
    download_results = [f.result() for f in download_futures]
    catalog = persist_raw_task(download_results)

    pdf_files = sorted(config.PDF_DIR.glob("*.pdf"))
    by_code = {e["code"]: e for e in catalog}
    metadata = _load_json(config.RAW_DIR / "metadata.json", {})

    # --- hash layer (reacts to PDFs present on disk) ---
    hash_futures = hash_book_task.map(pdf_files)
    hashes_result = persist_hashes_task([f.result() for f in hash_futures])
    hashes = hashes_result["files"]

    # --- describe / translate / covers (fan out per book, LLM-bounded) ---
    describe_futures = [
        describe_book_task.submit(pdf.stem, pdf, by_code.get(pdf.stem, {}).get("title", "Unknown"), metadata.get(pdf.stem))
        for pdf in pdf_files
    ]
    wait(describe_futures)
    descriptions = persist_descriptions_task([f.result() for f in describe_futures])

    title_futures = [
        translate_title_task.submit(code, entry["title"], metadata.get(code))
        for code, entry in by_code.items()
    ]
    wait(title_futures)
    translations = persist_translations_task([f.result() for f in title_futures])

    desc_items = [(code, d["description"]) for code, d in descriptions.items() if d.get("description")]
    desc_futures = [translate_description_task.submit(code, text) for code, text in desc_items]
    wait(desc_futures)
    desc_translations = persist_description_translations_task([f.result() for f in desc_futures])

    cover_futures = [extract_cover_task.submit(pdf.stem, pdf) for pdf in pdf_files]
    wait(cover_futures)
    covers = persist_covers_task([f.result() for f in cover_futures])

    # --- final, versioned assembly (reacts to all of the above) ---
    loc_report = assemble_localized_catalog_task(catalog, translations, descriptions, desc_translations)
    uni_report = assemble_universal_metadata_task(catalog, metadata, hashes, covers)

    run_id = finalize_run_task(loc_report, uni_report)
    logger.info(f"Run {run_id} complete. Outputs at data/runs/{run_id}/ (data/output/latest -> it)")
    return run_id


if __name__ == "__main__":
    data_foundry_flow()
