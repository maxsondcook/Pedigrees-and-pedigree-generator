#!/bin/bash
# One-shot: upload Crossr's data (data/*.csv + pedigrees_database.py) to Railway Postgres.
# Usage:  cd ~/Desktop/Crossr && ./scripts/load_to_railway.sh
set -e
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "Creating Python environment (.venv)..."
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q "psycopg[binary]>=3.1" pandas

if [ -z "$DATABASE_URL" ]; then
  echo
  echo "Paste the PUBLIC Postgres URL from Railway (Postgres -> Connect -> Public Network)."
  echo "It looks like postgresql://postgres:...@xxxx.proxy.rlwy.net:12345/railway"
  read -r -s -p "DATABASE_URL: " DATABASE_URL; echo
  export DATABASE_URL
fi

case "$DATABASE_URL" in
  *railway.internal*) echo "That is the private URL; use the Public Network one."; exit 1;;
esac

python scripts/load_railway.py "$@"
echo
echo "Done. Your data is in Railway."
