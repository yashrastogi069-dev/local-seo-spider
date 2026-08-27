#!/usr/bin/env bash
# Local SEO Spider — one-command first run for Python 3.12 and Chromium.
set -euo pipefail

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "Python 3.12 is required. Install Python 3.12 and rerun this command." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  python3.12 -m venv .venv
fi

if [ ! -f .env ]; then
  cp local-seo-spider.env.example .env
  echo "Created local .env from the checked-in configuration template."
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/playwright install chromium
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
