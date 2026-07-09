# Data Engineering - Data Foundry Challenge

Pipeline that scrapes, downloads, describes (via LLM), translates, and extracts
covers for works from [Domínio Público](https://dominiopublico.mec.gov.br/),
producing two versioned final datasets: `localized_catalog.json` and
`universal_metadata.json`.

Target areas covered: **data architecture**, **versioning**, **event-driven
pipeline**, **scalability**, and **data quality**.

## Setup

```bash
cp .env.example .env   # adjust LLM_BASE_URL/LLM_API_KEY/LLM_MODEL if not using local Ollama
docker compose up -d ollama
docker compose exec ollama ollama pull gemma3:4b
docker compose up --build pipeline
docker compose run --rm pipeline uv run pytest tests/ -v
```

> **No `make` on Windows** All commands below use `docker compose` directly —
> no `make` required. 

`docker compose up --build pipeline` builds the image and runs the Prefect
flow inside the `pipeline` container, writing to `./data` (mounted as a
volume). The `pipeline` container **exits after the run completes** — it is
not a long-lived service, so `docker compose exec pipeline ...` won't work
afterwards. Use `docker compose run --rm pipeline ...` instead to spin up a
fresh, short-lived container against the same `./data` volume (e.g. to run
tests or inspect outputs after the pipeline has finished):

```bash
docker compose run --rm pipeline uv run pytest tests/ -v
docker compose run --rm pipeline cat data/output/latest/localized_catalog.json
```

`ollama` and `prefect-server` (see below) *are* long-lived services, so
`docker compose exec ollama ...` / `docker compose exec prefect-server ...`
work normally against them.

### Quick smoke test (1 book instead of 10+)

Useful for validating the setup end-to-end without waiting for a full run:

```env
# in .env
MAX_BOOKS=1
```

Remember to set it back to `MAX_BOOKS=0` (unlimited) before running the real
pipeline — `MIN_BOOKS=10` (also in `.env`) is what the test suite actually
requires to pass.

## Prefect UI

By default Prefect spins up a short-lived, in-process ("ephemeral") server
for each flow run, so to save memory I am not implementing an UI.

## Data architecture

Three layers, each with a clear responsibility and data contract:

```
data/
├── raw/                  # IMMUTABLE — raw scrape + downloaded PDFs, keyed by `code`
│   ├── catalog.json
│   ├── metadata.json
│   └── pdfs/{code}.pdf
├── processed/              # DERIVED, CACHEABLE — reused across runs
│   ├── hashes.json
│   ├── descriptions.json
│   ├── translations.json
│   ├── description_translations.json
│   ├── covers.json
│   └── covers/{hash}.png
├── runs/                  # VERSIONED — one immutable snapshot per execution
│   └── <run_id>/
│       ├── localized_catalog.json
│       ├── universal_metadata.json
│       ├── *.quality.json     # per-dataset quality report
│       └── manifest.json      # run metadata
└── output/
    └── latest -> data/runs/<run_id>   # pointer to the most recent successful run
```

**Why 3 layers instead of 2:** the brief only asks for raw/processed, but
separating "processed" (per-book, reusable artifacts) from "final versioned"
(the two datasets, immutable per run) means versioning (layer 3) doesn't
force re-downloading or re-describing everything on every `docker compose up`
— only the final assembly (stages 7/8) is recomputed each run;
download/hash/describe/translate/cover act as a persistent incremental cache.


## Event-driven pipeline

The original `main.py` called the 8 scripts via `subprocess` in a fixed
list, one at a time, with no regard for whether there was actually new work
to do. This was replaced with a **Prefect flow** (`src/data_foundry/pipeline.py`):

- Every stage is a `@task`. Downstream tasks receive the **return value** of
  upstream tasks as input — the dependency graph reflects real data
  availability, not a hand-maintained sequence.
- Per-book stages (`download_book`, `hash_book`, `describe_book`,
  `translate_title`, `translate_description`, `extract_cover`) are fanned
  out with `.map()`/`.submit()`, each with independent retries — one book
  failing doesn't take down the whole run.
- Scripts `01`-`08` still work standalone (`docker compose run --rm pipeline
  uv run python src/data_foundry/scripts/01_download.py`, or `make download`
  if you have `make`) because the flow just orchestrates the same pure
  functions the scripts expose (`process_entry`, `hash_one`, `describe_one`, ...).

## Scalability

- **Real per-book parallelism**: download (thread pool,
  `MAX_DOWNLOAD_WORKERS`), hash, describe, translate, and covers run
  concurrently via Prefect (`ThreadPoolTaskRunner`).
- **Rate limiting**: LLM calls (describe/translate) are bounded by a
  semaphore (`MAX_LLM_CONCURRENCY`) to avoid overwhelming the backend,
  whether that's local Ollama or a paid, rate-limited API.
- **Pagination**: `scrape_catalog()` paginates the listing (`MAX_PAGES`,
  `PAGE_SIZE`, `MIN_BOOKS`) instead of only reading the first page — lets
  you scale from 10 to hundreds of books via env vars, no code changes.
- **`MAX_BOOKS`**: caps how many scraped entries actually get processed
  downstream — mainly a debugging/smoke-test knob (see above), but also
  useful to bound a run's cost/duration deliberately.
- When I was running a few tests, I got timed out by Ollama, 
  so the pipeline process all the downloadedbooks, but a few of then did not got a description or translation.
  I beliave if the pipeline run with an API KEY or in a machine with more resources it will work perfectly.

## Data quality

Applied at final assembly (`src/data_foundry/quality.py` + `schemas.py`),
with a report written to `*.quality.json` per run:

- **Encoding**: Unicode normalization (NFC), BOM/`\xa0` stripping, empty
  strings become explicit `null` instead of silently empty strings.
- **Duplicates**: `localized_catalog` dedupes by `id`; `universal_metadata`
  dedupes by `document_hash` — catches byte-identical PDFs registered under
  different `code`s (not uncommon with republished works in the archive).
- **Missing data**: tracked per field (`missing_fields` in the report,
  including nested fields like `description.pt` and `description.en`)
  instead of letting the pipeline crash or silently paper over gaps. This
  matters in practice: LLM calls can legitimately fail or time out under
  load (see Trade-offs below), and the report makes that visible rather
  than hiding it inside `null` values with no explanation.
- **Failed downloads excluded**: books that failed to download are filtered
  out before assembly (see Data architecture above) rather than appearing
  as empty records.
- **Schema validation**: every record is validated against Pydantic before
  reaching the final output; invalid records are reported, not silently
  dropped.

## Versioning

Every run gets a `run_id` (UTC timestamp + short hash, or pinned via
`RUN_ID` in `.env` for reruns/CI) and writes to `data/runs/<run_id>/` —
previous runs are never overwritten. On success, `data/output/latest` is
repointed (symlink, with a copy fallback on filesystems without symlink
support) to the most recent run. `make clean-runs` (or the equivalent
manual cleanup) keeps only the 5 most recent runs if the directory grows
too large.

## Tests

`tests/test_outputs.py` validates: presence and non-emptiness of files in
each layer, `data/output/latest` resolving, a minimum of 10 books, ID
consistency across `catalog`/`localized_catalog`/`universal_metadata`, no
duplicate `document_hash` in the final output, and that each run under
`data/runs/` has a `manifest.json`.

```bash
docker compose run --rm pipeline uv run pytest tests/ -v
```

## Trade-offs and decisions

- **Prefect chosen over Airflow(or other orchestrator)**: lower operational
  overhead for this scope — no separate scheduler/webserver/metadata DB
  needed, Python-native flow definitions, built-in retries and task mapping.
  The trade-off surfaced in practice: Prefect's default "ephemeral" mode
  uses SQLite, which doesn't handle concurrent writes well — this caused a
  `database is locked` error under load (Prefect's background telemetry
  service writing to the same file as task orchestration) and an ephemeral
  server startup timeout on a resource-constrained Docker Desktop/WSL2
  setup. Both were fixed by running a **persistent Prefect server**
  (`prefect-server` service in `compose.yaml`) instead of relying on the
  ephemeral mode — this also happens to unlock the Prefect UI.
- **Local vision-capable LLM sizing**: the starter `.env.example` pointed at
  `gemma4:e2b` (7.2GB). On an 8-16GB RAM machine running through
  Docker Desktop/WSL2, that left too little headroom for the model's own
  KV cache and image encoding, and the `llama-server` process running
  inside Ollama was repeatedly OOM-killed. I switched the default
  recommendation to `gemma3:4b` (3.3GB) — still vision-capable (needed
  because `describe.py` sends rendered PDF pages as images), but with much
  more memory headroom. `MAX_LLM_CONCURRENCY` and the per-call timeout
  (`timeout=300` in `03_describe.py`) are also tunable if a given machine
  still needs a lower-throughput/higher-timeout profile.
- **LLM failures are tolerated, not fatal**: on constrained hardware (CPU
  inference, no GPU passthrough), individual describe/translate calls can
  still time out under load even with a smaller model — cold starts after
  switching models, or contention when several concurrent tasks hit Ollama
  at once. Rather than failing the whole run, the affected field is left
  `null`. This is the intended behavior for a pipeline
  that has to run reliably on heterogeneous hardware — not a bug being
  quietly tolerated. Swapping `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL` for a
  paid, non-local API removes this constraint entirely, since the pipeline
  code doesn't care which backend serves the OpenAI-compatible endpoint.
- **`.dockerignore` is required, not optional**: without it, Docker's build
  context includes the entire `data/` directory (raw PDFs, processed cache,
  run history) generated by previous executions — including the `latest`
  symlink, which broke Docker's build-context packaging on Windows/WSL2.
  `data/`, `.git/`, `.venv/`, and caches are excluded.
- **Processed-layer cache never expires on its own**: today a book is only
  re-described/re-translated if its record disappears from
  `processed/*.json`. The cache isn't invalidated if `LLM_MODEL` changes
  (e.g. switching from Ollama to GPT-4o won't regenerate old descriptions).
  For production use, I'd key the cache by `LLM_MODEL` as well.
- **Symlink for `latest`**: simpler than copying files, but requires
  filesystem/OS symlink support — hence the `shutil.copytree` fallback in
  `finalize_run_task`.
- **Rate limiting via `threading.Semaphore`** rather than Prefect
  concurrency limits (which require a running Prefect Server/API):
  simpler to reason about locally, at the cost of not being reconfigurable
  at runtime without restarting the process.