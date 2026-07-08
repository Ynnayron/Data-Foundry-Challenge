"""Stage 5 - translate descriptions to EN/ES/FR (PROCESSED layer)."""

import json
import threading

from openai import OpenAI

from data_foundry.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    MAX_LLM_CONCURRENCY,
    PROCESSED_DIR,
)

TARGET_LANGUAGES = {"en": "English", "es": "Spanish", "fr": "French"}

client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
_LLM_SEMAPHORE = threading.Semaphore(MAX_LLM_CONCURRENCY)


def translate_text(text: str, target_lang: str) -> str | None:
    prompt = (
        f"Translate the following Portuguese text to {target_lang}. "
        f"Return ONLY the translated text, nothing else.\n\n"
        f"{text}"
    )

    with _LLM_SEMAPHORE:
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                timeout=60,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  LLM error: {e}")
    return None


def translate_description(description: str) -> dict:
    """Pure per-book function: translate one description to all target languages."""
    entry_translations = {"original": description}
    for lang_key, lang_name in TARGET_LANGUAGES.items():
        entry_translations[lang_key] = translate_text(description, lang_name)
    return entry_translations


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    desc_path = PROCESSED_DIR / "descriptions.json"
    if not desc_path.exists():
        print("descriptions.json not found. Run 03_describe.py first.")
        return

    with open(desc_path, encoding="utf-8") as f:
        descriptions = json.load(f)

    trans_path = PROCESSED_DIR / "description_translations.json"
    translations = {}
    if trans_path.exists():
        with open(trans_path, encoding="utf-8") as f:
            translations = json.load(f)

    entries = {k: v for k, v in descriptions.items() if v.get("description")}
    print(f"Translating {len(entries)} descriptions to {', '.join(TARGET_LANGUAGES.values())}...")
    print(f"Using model: {LLM_MODEL} via {LLM_BASE_URL} (max concurrency={MAX_LLM_CONCURRENCY})")

    for i, (code, entry) in enumerate(entries.items()):
        if code in translations:
            print(f"[{i + 1}/{len(entries)}] {code} - already translated, skipping")
            continue

        title = entry.get("title", code)
        print(f"[{i + 1}/{len(entries)}] {title[:50]}...")
        translations[code] = translate_description(entry["description"])

        with open(trans_path, "w", encoding="utf-8") as f:
            json.dump(translations, f, ensure_ascii=False, indent=2)

    translated = sum(1 for t in translations.values() if t.get("en"))
    print(f"\nDone. {translated}/{len(translations)} descriptions translated.")
    print(f"Output saved to {trans_path}")


if __name__ == "__main__":
    main()
