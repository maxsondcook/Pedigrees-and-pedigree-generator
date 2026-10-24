#!/bin/zsh
# Run a command with DATABASE_URL pointing at Railway Postgres.
#
#   scripts/pipeline/railway_env.sh railway  python -m crossr_pipeline status   # production
#   scripts/pipeline/railway_env.sh crossr_dev python -m crossr_pipeline status  # test database
#
# The URL is built from the Railway CLI on each start, so no password is
# stored in files (launchd plists included).
set -euo pipefail
dbname="${1:?database name: railway (production) or crossr_dev}"
shift
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"
RAILWAY="${RAILWAY_CLI:-$HOME/.local/railway-cli/node_modules/.bin/railway}"
cd "$(dirname "$0")/../.."
vars="$("$RAILWAY" variables --service Postgres --kv)"
get() { print -r -- "$vars" | sed -n "s/^$1=//p" | head -1; }
user="$(get PGUSER)"; pass="$(get PGPASSWORD)"
host="$(get RAILWAY_TCP_PROXY_DOMAIN)"; port="$(get RAILWAY_TCP_PROXY_PORT)"
if [[ -z "$host" || -z "$port" ]]; then
  echo "railway_env: no TCP proxy on Postgres (railway tcp-proxy create -s Postgres --port 5432)" >&2
  exit 1
fi
export DATABASE_URL="postgresql://${user}:${pass}@${host}:${port}/${dbname}"
exec "$@"
