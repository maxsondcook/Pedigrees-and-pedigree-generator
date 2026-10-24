# Running Crossr on Railway

Three services in one Railway project:

| Service | What it is | Built from |
| --- | --- | --- |
| **Postgres** | All Crossr data: the 8 tables, pedigrees, accounts | Railway's Postgres template |
| **api** | FastAPI (`crossr_api`) | `Dockerfile` |
| **web** | Next.js site | `web/Dockerfile` |

Live project: `vigilant-strength` (production).
Site: https://web-production-cbb1f5.up.railway.app · API: https://api-production-f372.up.railway.app/api/health

Build settings live on the services themselves; Railway no longer accepts `railway.json` config files.

When `DATABASE_URL` is set the app reads and writes Postgres. Without it, it
falls back to the local `data/*.csv` files and `pedigrees_database.py`, so local
development still works offline.

## 1. Push the repo

```bash
cd ~/Desktop/Crossr
git push -u origin unified        # then open a PR into main, or push to main
```

`data/` and `pedigrees_database.py` are gitignored on purpose: `sales_lots.csv`
is over GitHub's 100 MB limit, and the data belongs in Postgres anyway.

## 2. Create the Railway project

1. railway.com → **New Project** → **Deploy PostgreSQL**.
2. In that project: **+ Create → GitHub Repo → maxsondcook/Crossr**. Rename the
   service to `api`.
   - Settings → Source → branch: `unified` (or `main` after merging).
   - Settings → Build → Dockerfile path: `Dockerfile`; Deploy → healthcheck
     path `/api/health`, timeout 300.
   - Variables → add `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
     and `CROSSR_FRONTEND_ORIGIN` = `https://<your web domain>` (fill in after step 3).
3. **+ Create → GitHub Repo → maxsondcook/Crossr** again. Rename it to `web`.
   - Settings → Build → Dockerfile path: `web/Dockerfile` (build context stays the repo root).
   - Variables → `API_INTERNAL` = `http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000`
     and `PORT` = `3000`.
   - Settings → Networking → **Generate Domain** — this is the public site.
4. On `api`, set `PORT` = `8000` (it must match `API_INTERNAL`).

## 3. Load the data (once, from your Mac)

Easiest, with the Railway CLI logged in and this folder linked (`railway link`):

```bash
railway tcp-proxy create -s Postgres --port 5432   # once: public access
railway run -s Postgres -- ./scripts/load_via_railway_cli.sh
```

Or by hand: Railway → Postgres → **Connect** → copy the **public** connection URL.

```bash
cd ~/Desktop/Crossr
python3 -m pip install -r requirements.txt
export DATABASE_URL="postgresql://postgres:...@...proxy.rlwy.net:PORT/railway"
python3 scripts/load_railway.py
```

Takes about a minute and needs ~5 GB of free RAM (mostly reading the 51 MB
`pedigrees_database.py`). Re-run any time; each table is swapped in a single
transaction. Load one table with `--only sales_lots`, or `--skip-pedigrees`.

Expected counts (Oct 2026 data):

```
stud_fees 15,368   race_horses 318,504   race_seasons 112,276   race_starts 486,583
breeding_seasons 81,868   stallion_rankings 103,957   graded_stakes 90,518
sales_lots 399,590   pedigrees 39,213
```

## 4. Check it

`https://<api domain>/api/health` should return `"backend": "postgres"`.

## Scrapers

With `DATABASE_URL` exported, the pipeline (`scripts/pipeline/run.py`) and the
pedigree scrapers write straight to Railway. The running API notices changes
within ~15 s (`crossr_table_versions`) and reloads only the table that changed.

The scheduled pipeline (Equibase race records, sale-parent pedigrees, sales
CSV import) is in [PIPELINE.md](PIPELINE.md).

## Known limits

- The API still loads each table fully into memory the first time it is used
  (~3.5 GB with everything loaded). Moving the heavy lookups to SQL queries is
  the next step to cut RAM, and therefore cost.
