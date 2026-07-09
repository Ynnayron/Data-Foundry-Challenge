"""Stage 1 - scrape the catalog listing and download PDFs into the RAW layer.

Refactored to expose a per-book function so the prefect flow
can fan it out across a thread pool (scalability) instead of one book at a time.
Also supports pagination (MAX_PAGES / MIN_BOOKS) instead of a single hardcoded page.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from playwright.sync_api import sync_playwright

from data_foundry.config import (
    BASE_URL,
    MAX_BOOKS,
    MAX_DOWNLOAD_WORKERS,
    MAX_PAGES,
    MIN_BOOKS,
    PAGE_SIZE,
    PDF_DIR,
    RAW_DIR,
    list_url,
)

SESSION = cffi_requests.Session(impersonate="chrome")


def fetch_page(url: str) -> str | None:
    try:
        resp = SESSION.get(url, timeout=30)
        if resp.status_code == 200 and "challenge" not in resp.text[:500].lower():
            return resp.text
    except Exception as e:
        print(f"  curl-cffi failed: {e}")

    return fetch_page_playwright(url)


def fetch_page_playwright(url: str) -> str | None:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)
            time.sleep(3)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"  Playwright fallback failed: {e}")
    return None


def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="res")
    if not table:
        print("ERROR: Could not find results")
        return []

    tbody = table.find("tbody")
    if not tbody:
        print("ERROR: No tbody in results table")
        return []

    entries = []
    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 6:
            continue

        link = cells[2].find("a")
        if not link:
            continue
        href = link.get("href", "")
        code = None
        if "co_obra=" in href:
            code = href.split("co_obra=")[-1].strip("'\" ")

        title = link.get_text(strip=True)
        author = cells[3].get_text(strip=True)
        source = cells[4].get_text(strip=True)
        fmt = cells[5].get_text(strip=True)
        size = cells[6].get_text(strip=True) if len(cells) > 6 else ""
        accesses = cells[7].get_text(strip=True) if len(cells) > 7 else ""

        if code and title:
            entries.append(
                {
                    "code": code,
                    "title": title,
                    "author": author,
                    "source": source,
                    "format": fmt,
                    "size": size,
                    "accesses": accesses,
                }
            )

    return entries


def scrape_catalog(max_pages: int = MAX_PAGES, min_books: int = MIN_BOOKS) -> list[dict]:
    seen: dict[str, dict] = {}
    page = 1
    hard_limit = max(max_pages, 1) + 20  # safety valve
    while page <= hard_limit:
        skip = (page - 1) * PAGE_SIZE
        print(f"Fetching listing page {page} (skip={skip})...")
        html = fetch_page(list_url(page=page, skip=skip, page_size=PAGE_SIZE))
        if not html:
            print(f"  Failed to fetch page {page}, stopping pagination.")
            break
        entries = parse_listing(html)
        if not entries:
            print(f"  No entries on page {page}, stopping pagination.")
            break
        for e in entries:
            seen.setdefault(e["code"], e)
        if page >= max_pages and len(seen) >= min_books:
            break
        page += 1
    return list(seen.values())


def parse_detail_page(html: str) -> dict:
    metadata = {}
    field_map = {
        "Título:": "title",
        "Autor:": "author",
        "Categoria:": "category",
        "Idioma:": "language",
        "Instituição:/Parceiro": "institution",
        "Ano da Tese": "year",
        "Acessos:": "accesses",
    }

    matches = re.findall(r'class="detalhe\d"[^>]*>(.*?)</td>', html, re.DOTALL)
    clean = []
    for m in matches:
        text = BeautifulSoup(m, "html.parser").get_text(strip=True)
        clean.append(text)

    current_field = None
    for text in clean:
        matched_label = None
        for label, key in field_map.items():
            if label in text:
                matched_label = key
                break
        if matched_label:
            current_field = matched_label
        elif current_field and text and text != "\xa0":
            if current_field not in metadata:
                metadata[current_field] = text
            current_field = None

    return metadata


def get_download_url_and_metadata(code: str) -> tuple[str | None, dict]:
    detail_url = f"{BASE_URL}/DetalheObraForm.do?select_action=&co_obra={code}"
    html = fetch_page(detail_url)
    if not html:
        return None, {}

    metadata = parse_detail_page(html)

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "download" in href.lower():
            if href.startswith("../"):
                return href.replace(
                    "../", "https://dominiopublico.mec.gov.br/"
                ), metadata
            elif href.startswith("/"):
                return f"https://dominiopublico.mec.gov.br{href}", metadata
            elif not href.startswith("http"):
                return f"https://dominiopublico.mec.gov.br/pesquisa/{href}", metadata
            return href, metadata

    return None, metadata


def download_pdf(url: str, filepath: Path) -> bool:
    try:
        resp = SESSION.get(url, timeout=120)
        if resp.status_code == 200 and len(resp.content) > 1000:
            filepath.write_bytes(resp.content)
            return True
    except Exception as e:
        print(f"  Download error: {e}")
    return False


def process_entry(entry: dict) -> tuple[dict, dict]:
    code = entry["code"]
    entry = dict(entry)

    download_url, detail_meta = get_download_url_and_metadata(code)
    entry["download_url"] = download_url

    meta_record = {
        **detail_meta,
        "code": code,
        "download_url": download_url,
    }

    if download_url:
        pdf_path = PDF_DIR / f"{code}.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            entry["downloaded"] = True
        else:
            success = download_pdf(download_url, pdf_path)
            entry["downloaded"] = success
    else:
        entry["downloaded"] = False

    return entry, meta_record


def main():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    catalog_path = RAW_DIR / "catalog.json"
    metadata_path = RAW_DIR / "metadata.json"

    # Idempotency: don't re-fetch codes we've already downloaded successfully,
    # so re-running the pipeline is cheap and doesn't hammer the source site.
    existing_catalog = []
    if catalog_path.exists():
        with open(catalog_path, encoding="utf-8") as f:
            existing_catalog = json.load(f)
    already_have = {e["code"] for e in existing_catalog if e.get("downloaded")}

    entries = scrape_catalog()
    print(f"Found {len(entries)} unique entries across listing pages")

    if not entries:
        print("No entries found. Check if page structure changed.")
        return
    if MAX_BOOKS:
        entries = entries[:MAX_BOOKS]
        print(f"MAX_BOOKS set: limiting this run to {len(entries)} book(s)")

    to_fetch = [e for e in entries if e["code"] not in already_have]
    print(
        f"{len(already_have)} already downloaded, fetching {len(to_fetch)} new/missing "
        f"entries with {MAX_DOWNLOAD_WORKERS} workers..."
    )

    catalog_by_code = {e["code"]: e for e in existing_catalog}
    all_metadata: dict[str, dict] = {}
    if metadata_path.exists():
        with open(metadata_path, encoding="utf-8") as f:
            all_metadata = json.load(f)

    with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as pool:
        futures = {pool.submit(process_entry, e): e for e in to_fetch}
        for i, fut in enumerate(as_completed(futures)):
            entry = futures[fut]
            try:
                result_entry, meta_record = fut.result()
            except Exception as e:
                print(f"  [{i + 1}/{len(to_fetch)}] {entry['title'][:50]}: ERROR {e}")
                result_entry, meta_record = entry, {"code": entry["code"]}
            status = "OK" if result_entry.get("downloaded") else "FAILED"
            print(f"  [{i + 1}/{len(to_fetch)}] {result_entry['title'][:50]}... {status}")
            catalog_by_code[result_entry["code"]] = result_entry
            all_metadata[result_entry["code"]] = meta_record
            time.sleep(0.2)

    catalog = list(catalog_by_code.values())
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(all_metadata, f, ensure_ascii=False, indent=2)

    downloaded = sum(1 for e in catalog if e.get("downloaded"))
    print(f"\nDone. {downloaded}/{len(catalog)} PDFs downloaded.")
    print(f"Catalog saved to {catalog_path}")
    print(f"Metadata saved to {metadata_path}")


if __name__ == "__main__":
    main()
