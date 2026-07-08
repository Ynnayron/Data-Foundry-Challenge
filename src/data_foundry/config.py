"""Central configuration: env vars, LLM settings, and the layered data paths.

Data architecture (3 layers, see README for rationale):
  data/raw/        immutable inputs: scraped listing + downloaded PDFs, keyed by `code`
  data/processed/  derived, cacheable per-book artifacts: hashes, descriptions,
                    translations, covers. Reused across runs (never re-done if present).
  data/runs/<id>/  one immutable snapshot per pipeline execution: the two final
                    datasets + a manifest. Re-runs never overwrite previous ones.
  data/output/latest -> symlink to the most recent successful data/runs/<id>
"""

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://dominiopublico.mec.gov.br/pesquisa"


def list_url(page: int = 1, skip: int = 0, page_size: int = 10) -> str:
    """Build a listing URL. Supports pagination (`page`/`skip`) for scale-out scraping."""
    return (
        f"{BASE_URL}/ResultadoPesquisaObraForm.do?"
        f"first={page_size}&skip={skip}&ds_titulo=&co_autor=&no_autor="
        f"&co_categoria=41&pagina={page}&select_action=Submit"
        "&co_midia=2&co_obra=&co_idioma="
        "&colunaOrdenar=NU_PAGE_HITS&ordem=desc"
    )


# Backwards-compatible constant (page 1), individual scripts / older code can still use it.
LIST_URL = list_url()

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"

# --- Layer 1: raw (immutable, shared across runs) ---
RAW_DIR = DATA_DIR / "raw"
PDF_DIR = RAW_DIR / "pdfs"

# --- Layer 2: processed (derived, cacheable, shared across runs) ---
PROCESSED_DIR = DATA_DIR / "processed"
COVERS_DIR = PROCESSED_DIR / "covers"

# --- Layer 3: runs (versioned, immutable snapshots) ---
RUNS_DIR = DATA_DIR / "runs"
OUTPUT_DIR = DATA_DIR / "output"  # holds only the `latest` pointer

# Backwards-compat alias used by the pre-existing scripts before this refactor.
LEGACY_OUTPUT_DIR = PROCESSED_DIR


def _make_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = uuid.uuid4().hex[:6]
    return f"{ts}-{short}"


def resolve_run_id() -> str:
    """A run_id can be pinned via env var (useful for retries/CI); otherwise generate one."""
    env_id = os.getenv("RUN_ID")
    if env_id:
        return re.sub(r"[^A-Za-z0-9_.-]", "-", env_id)
    return _make_run_id()


RUN_ID = resolve_run_id()
RUN_DIR = RUNS_DIR / RUN_ID

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_MODEL = os.getenv("LLM_MODEL", "gemma4:e2b")

# --- Scalability knobs ---
MAX_DOWNLOAD_WORKERS = int(os.getenv("MAX_DOWNLOAD_WORKERS", "5"))
MAX_LLM_CONCURRENCY = int(os.getenv("MAX_LLM_CONCURRENCY", "3"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "1"))  # listing pages to scrape (pagination)
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "10"))
MIN_BOOKS = int(os.getenv("MIN_BOOKS", "10"))  # keep scraping extra pages until this many
MAX_BOOKS = int(os.getenv("MAX_BOOKS", "0"))  # 0 = unlimited; caps books processed after scraping (testing)

def ensure_dirs() -> None:
    for d in (RAW_DIR, PDF_DIR, PROCESSED_DIR, COVERS_DIR, RUNS_DIR, RUN_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
