"""Stage 3 - generate Portuguese descriptions via a vision LLM (PROCESSED layer).

Refactored into a per-book `describe_one` function so the flow can run it
concurrently across books, bounded by MAX_LLM_CONCURRENCY (rate limiting
against the LLM backend).
"""

import base64
import json
import threading
from pathlib import Path

import fitz
from openai import OpenAI

from data_foundry.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    MAX_LLM_CONCURRENCY,
    PDF_DIR,
    PROCESSED_DIR,
    RAW_DIR,
)

MAX_PAGES = 1

client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
_LLM_SEMAPHORE = threading.Semaphore(MAX_LLM_CONCURRENCY)


def pdf_pages_to_base64(pdf_path: Path, max_pages: int = MAX_PAGES) -> list[str]:
    images = []
    try:
        doc = fitz.open(str(pdf_path))
        for i in range(min(max_pages, len(doc))):
            page = doc[i]
            pix = page.get_pixmap(dpi=150)
            png_bytes = pix.tobytes("png")
            b64 = base64.b64encode(png_bytes).decode("utf-8")
            images.append(b64)
        doc.close()
    except Exception as e:
        print(f"  Error rendering PDF: {e}")
    return images


def format_metadata(meta: dict) -> str:
    parts = []
    for key, value in meta.items():
        if value and key not in ("code", "download_url"):
            parts.append(f"- {key}: {value}")
    return "\n".join(parts)


def describe_document(
    images: list[str], title: str, metadata: dict | None = None
) -> str | None:
    meta_ctx = ""
    if metadata:
        meta_ctx = f"\n\nDocument metadata:\n{format_metadata(metadata)}\n"

    content = [
        {
            "type": "text",
            "text": (
                f"This document is titled '{title}'.{meta_ctx}\n"
                "Based on these pages and metadata, provide a concise description (2-3 sentences) "
                "of what this document is about. Include the main topic, methodology "
                "if visible, and key findings if apparent. Respond in Portuguese."
            ),
        },
    ]
    for b64 in images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )

    with _LLM_SEMAPHORE:  # rate limit concurrent calls to the LLM backend
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": content}],
                timeout=300,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  LLM error: {e}")
    return None


def describe_one(pdf_path: Path, title: str, metadata: dict | None) -> dict:
    """Pure per-book function: render + describe one PDF. Safe for concurrent .map()."""
    images = pdf_pages_to_base64(pdf_path)
    if not images:
        return {"title": title, "description": None, "error": "render_failed"}
    description = describe_document(images, title, metadata)
    return {"title": title, "description": description}


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    catalog_path = RAW_DIR / "catalog.json"
    if catalog_path.exists():
        with open(catalog_path, encoding="utf-8") as f:
            catalog = {e["code"]: e for e in json.load(f)}
    else:
        catalog = {}
        print("Warning: catalog.json not found. Titles will be 'Unknown'.")

    metadata_path = RAW_DIR / "metadata.json"
    if metadata_path.exists():
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)
    else:
        metadata = {}
        print("Warning: metadata.json not found. Descriptions will lack metadata context.")

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        print("No PDFs found in data/raw/pdfs/. Run 01_download.py first.")
        return

    desc_path = PROCESSED_DIR / "descriptions.json"
    descriptions = {}
    if desc_path.exists():
        with open(desc_path, encoding="utf-8") as f:
            descriptions = json.load(f)

    print(f"Generating descriptions for {len(pdf_files)} PDFs...")
    print(f"Using model: {LLM_MODEL} via {LLM_BASE_URL} (max concurrency={MAX_LLM_CONCURRENCY})")

    for i, pdf in enumerate(pdf_files):
        code = pdf.stem
        if code in descriptions:
            print(f"[{i + 1}/{len(pdf_files)}] {code} - already described, skipping")
            continue

        title = catalog.get(code, {}).get("title", "Unknown")
        print(f"[{i + 1}/{len(pdf_files)}] {title[:60]}...")

        result = describe_one(pdf, title, metadata.get(code))
        descriptions[code] = result

        with open(desc_path, "w", encoding="utf-8") as f:
            json.dump(descriptions, f, ensure_ascii=False, indent=2)

        if result.get("description"):
            print(f"  -> {result['description'][:100]}...")
        else:
            print("  -> No description generated")

    described = sum(1 for d in descriptions.values() if d.get("description"))
    print(f"\nDone. {described}/{len(descriptions)} documents described.")
    print(f"Output saved to {desc_path}")


if __name__ == "__main__":
    main()
