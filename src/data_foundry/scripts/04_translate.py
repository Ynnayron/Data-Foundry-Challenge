"""Stage 4 - translate titles to EN/ES/FR (PROCESSED layer)."""

import json
import threading

from openai import OpenAI

from data_foundry.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    MAX_LLM_CONCURRENCY,
    PROCESSED_DIR,
    RAW_DIR,
)

TARGET_LANGUAGES = {"en": "English", "es": "Spanish", "fr": "French"}

client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
_LLM_SEMAPHORE = threading.Semaphore(MAX_LLM_CONCURRENCY)


def translate_title(
    title: str, target_lang: str, metadata: dict | None = None
) -> str | None:
    meta_ctx = ""
    if metadata:
        parts = [
            f"{k}: {v}"
            for k, v in metadata.items()
            if v and k not in ("code", "download_url", "title")
        ]
        if parts:
            meta_ctx = (
                "\n\nContext about this document:\n"
                + "\n".join(f"- {p}" for p in parts)
                + "\n"
            )

    prompt = (
        f"Translate the following Portuguese title to {target_lang}. "
        f"Return ONLY the translated title, nothing else.{meta_ctx}\n\n"
        f"Title: {title}"
    )

    with _LLM_SEMAPHORE:
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                timeout=60,
            )
            result = resp.choices[0].message.content.strip()
            result = result.strip("\"'")
            if "\n" in result:
                result = result.split("\n")[0].strip()
            return result
        except Exception as e:
            print(f"  LLM error: {e}")
    return None


def translate_entry(title: str, metadata: dict | None) -> dict:
    """Pure per-book function: translate one title to all target languages."""
    entry_translations = {"original": title}
    for lang_key, lang_name in TARGET_LANGUAGES.items():
        entry_translations[lang_key] = translate_title(title, lang_name, metadata)
    return entry_translations


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    catalog_path = RAW_DIR / "catalog.json"
    if not catalog_path.exists():
        print("catalog.json not found. Run 01_download.py first.")
        return

    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)

    metadata_path = RAW_DIR / "metadata.json"
    metadata = {}
    if metadata_path.exists():
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)

    trans_path = PROCESSED_DIR / "translations.json"
    translations = {}
    if trans_path.exists():
        with open(trans_path, encoding="utf-8") as f:
            translations = json.load(f)

    print(f"Translating {len(catalog)} titles to {', '.join(TARGET_LANGUAGES.values())}...")
    print(f"Using model: {LLM_MODEL} via {LLM_BASE_URL} (max concurrency={MAX_LLM_CONCURRENCY})")

    for i, entry in enumerate(catalog):
        code = entry["code"]
        title = entry["title"]

        if code in translations:
            print(f"[{i + 1}/{len(catalog)}] {title[:50]} - already translated, skipping")
            continue

        print(f"[{i + 1}/{len(catalog)}] {title[:50]}...")
        translations[code] = translate_entry(title, metadata.get(code))

        with open(trans_path, "w", encoding="utf-8") as f:
            json.dump(translations, f, ensure_ascii=False, indent=2)

    translated = sum(1 for t in translations.values() if t.get("en"))
    print(f"\nDone. {translated}/{len(translations)} titles translated.")
    print(f"Output saved to {trans_path}")


if __name__ == "__main__":
    main()
