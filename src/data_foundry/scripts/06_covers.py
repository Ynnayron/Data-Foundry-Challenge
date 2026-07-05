import hashlib
import json
from pathlib import Path

import fitz

from data_foundry.config import DATA_DIR, OUTPUT_DIR, PDF_DIR

COVERS_DIR = DATA_DIR / "covers"


def extract_cover(pdf_path: Path) -> tuple[Path | None, str | None]:
    try:
        doc = fitz.open(str(pdf_path))
        page = doc[0]
        pix = page.get_pixmap(dpi=150)
        png_bytes = pix.tobytes("png")
        doc.close()

        img_hash = hashlib.sha256(png_bytes).hexdigest()
        output_path = COVERS_DIR / f"{img_hash}.png"
        if not output_path.exists():
            output_path.write_bytes(png_bytes)
        return output_path, img_hash
    except Exception as e:
        print(f"  Error: {e}")
        return None, None


def main():
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        print("No PDFs found in data/pdfs/. Run 01_download.py first.")
        return

    covers_path = OUTPUT_DIR / "covers.json"
    if covers_path.exists():
        with open(covers_path, encoding="utf-8") as f:
            covers = json.load(f)
    else:
        covers = {}

    print(f"Extracting covers from {len(pdf_files)} PDFs...")

    for i, pdf in enumerate(pdf_files):
        code = pdf.stem

        if code in covers:
            print(f"[{i + 1}/{len(pdf_files)}] {code} — already extracted, skipping")
            continue

        print(f"[{i + 1}/{len(pdf_files)}] {code}...")
        cover_path, img_hash = extract_cover(pdf)
        if cover_path:
            covers[code] = {
                "path": str(cover_path.relative_to(DATA_DIR)),
                "hash": img_hash,
            }
            print(f"  → {cover_path.name}")
        else:
            covers[code] = None
            print("  → Failed")

        with open(covers_path, "w", encoding="utf-8") as f:
            json.dump(covers, f, ensure_ascii=False, indent=2)

    extracted = sum(1 for v in covers.values() if v)
    print(f"\nDone. {extracted}/{len(covers)} covers extracted.")
    print(f"Output saved to {covers_path}")


if __name__ == "__main__":
    main()
