.PHONY: setup setup-ollama ollama-up ollama-pull run run-flow run-legacy download hash describe translate translate-descriptions covers localized-catalog universal-metadata test lint clean-runs

ollama-up:
	docker compose up -d ollama

ollama-pull:
	docker compose exec ollama ollama pull gemma4:e2b

setup:
	uv sync --group dev

setup-ollama: setup ollama-up ollama-pull

# Full pipeline via Docker, orchestrated by the Prefect flow (event-driven,
# see src/data_foundry/pipeline.py). This is the target the challenge expects.
run:
	docker compose up --build pipeline

# Run the Prefect flow locally (no Docker), e.g. for development.
run-flow:
	uv run python -m data_foundry.pipeline

# Individual stages, useful for debugging one step at a time. Each is
# idempotent: re-running only fills in what's missing.
download:
	uv run python src/data_foundry/scripts/01_download.py

hash:
	uv run python src/data_foundry/scripts/02_hash.py

describe:
	uv run python src/data_foundry/scripts/03_describe.py

translate:
	uv run python src/data_foundry/scripts/04_translate.py

translate-descriptions:
	uv run python src/data_foundry/scripts/05_translate_descriptions.py

covers:
	uv run python src/data_foundry/scripts/06_covers.py

localized-catalog:
	uv run python src/data_foundry/scripts/07_localized_catalog.py

universal-metadata:
	uv run python src/data_foundry/scripts/08_universal_metadata.py

# Legacy: same 8 stages, run sequentially without Prefect (kept for comparison
# / as a fallback if Prefect is unavailable).
run-legacy: download hash describe translate translate-descriptions covers localized-catalog universal-metadata

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

# Versioning cleanup helper: data/runs/ accumulates one folder per execution.
clean-runs:
	find data/runs -mindepth 1 -maxdepth 1 -type d | sort | head -n -5 | xargs -r rm -rf
