FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY . .

RUN uv sync

# Playwright is the fallback scraper for 01_download.py when curl-cffi is blocked.
RUN uv run playwright install --with-deps chromium

CMD ["uv", "run", "python", "-m", "data_foundry.main"]
