import json

from openai import OpenAI

from data_foundry.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, OUTPUT_DIR

TARGET_LANGUAGES = {"en": "English", "es": "Spanish", "fr": "French"}

client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


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


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    catalog_path = OUTPUT_DIR / "catalog.json"
    if not catalog_path.exists():
        print("catalog.json not found. Run 01_download.py first.")
        return

    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)

    metadata_path = OUTPUT_DIR / "metadata.json"
    if metadata_path.exists():
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)
    else:
        metadata = {}

    trans_path = OUTPUT_DIR / "translations.json"
    if trans_path.exists():
        with open(trans_path, encoding="utf-8") as f:
            translations = json.load(f)
    else:
        translations = {}

    print(
        f"Translating {len(catalog)} titles to {', '.join(TARGET_LANGUAGES.values())}..."
    )
    print(f"Using model: {LLM_MODEL} via {LLM_BASE_URL}")

    for i, entry in enumerate(catalog):
        code = entry["code"]
        title = entry["title"]

        if code in translations:
            print(
                f"[{i + 1}/{len(catalog)}] {title[:50]} — already translated, skipping"
            )
            continue

        print(f"[{i + 1}/{len(catalog)}] {title[:50]}...")

        meta = metadata.get(code)
        entry_translations = {"original": title}
        for lang_key, lang_name in TARGET_LANGUAGES.items():
            translated = translate_title(title, lang_name, meta)
            entry_translations[lang_key] = translated
            if translated:
                print(f"  {lang_key}: {translated[:60]}")

        translations[code] = entry_translations

        with open(trans_path, "w", encoding="utf-8") as f:
            json.dump(translations, f, ensure_ascii=False, indent=2)

    translated = sum(1 for t in translations.values() if t.get("en"))
    print(f"\nDone. {translated}/{len(translations)} titles translated.")
    print(f"Output saved to {trans_path}")


if __name__ == "__main__":
    main()
