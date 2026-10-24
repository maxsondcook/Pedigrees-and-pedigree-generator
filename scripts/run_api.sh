#!/bin/sh
set -e
cd "$(dirname "$0")/.."
if [ ! -f crossr_sales.db ]; then
  python3 scripts/index_sales.py
fi
uvicorn crossr_api.app:app --reload --port 8000
