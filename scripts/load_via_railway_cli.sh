#!/bin/bash
# Load data into Railway Postgres using the Railway CLI's login, so the
# database password never has to be copied by hand.
# Usage:  cd ~/Desktop/Crossr && railway run -s Postgres -- ./scripts/load_via_railway_cli.sh
set -e
cd "$(dirname "$0")/.."

if [ -z "$RAILWAY_TCP_PROXY_DOMAIN" ]; then
  echo "Postgres has no public TCP proxy. Run: railway tcp-proxy create -s Postgres --port 5432"
  exit 1
fi

DATABASE_URL="$(python3 -c 'import os, urllib.parse as u; e = os.environ
print("postgresql://%s:%s@%s:%s/%s" % (u.quote(e["PGUSER"], safe=""), u.quote(e["PGPASSWORD"], safe=""),
      e["RAILWAY_TCP_PROXY_DOMAIN"], e["RAILWAY_TCP_PROXY_PORT"], e["PGDATABASE"]))')"
export DATABASE_URL

exec ./scripts/load_to_railway.sh "$@"
