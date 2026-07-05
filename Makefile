.PHONY: setup setup-ollama ollama-up ollama-pull run run-all download hash describe translate translate-descriptions covers localized-catalog universal-metadata test lint

ollama-up:
	docker compose up -d ollama

ollama-pull:
	docker compose exec ollama ollama pull gemma4:e2b

setup:
	uv sync --group dev

setup-ollama: setup ollama-up ollama-pull

run:
	docker compose up --build pipeline

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

run-all: download hash describe translate translate-descriptions covers localized-catalog universal-metadata

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/
