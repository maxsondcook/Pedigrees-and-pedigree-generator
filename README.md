# Crossr

Thoroughbred pedigree, stallion, sales, and mating research. The same data powers a **Next.js** site (`web/`) and a **Python CLI** (`main.py`).

The public UI never sees Keeneland/Fasig-Tipton CSVs or `graded_stakes_winners.csv`. Those stay on the API machine; the browser only gets JSON.

## What it does

- **Horse profiles** — 5-generation catalog pedigree, female family / produce, race record, stud fee and mares bred, stallion rankings, broodmare-sire history, progeny stats, and proven crosses.
- **Stallion directory** — filter Kentucky and other commercial books by farm, crop, fee, and stud year; compare stallions; star horses into **My Barn**.
- **Hypomating** — given a broodmare, suggest stallions from graded-stakes winner crosses (surface + fee), then offer sons/ancestors when the proven sire is too expensive. Same-cross inbreeding is blocked (for example Citizen Bull is not re-suggested on Into Mischief × Distorted Humor).
- **Sales** — Fasig-Tipton (2004–) and Keeneland (1999–) catalogs: browse a sale, search a sire’s auction record, or look up one horse’s sale history.
- **Accounts** — register / sign in for saved preferences.

Horses are stored as `NAME (YYYY)`. If a search hits two or more foaling years, the app asks which horse you mean.

## Run locally

Python 3.11+ and Node 18+.

```bash
python3 -m pip install -r requirements.txt
python3 scripts/index_sales.py          # once, or after sales_data/ changes
python3 -m uvicorn crossr_api.app:app --reload --port 8000
```

```bash
cd web
npm install
npm run dev                             # http://localhost:3000
```

Or `./scripts/run_api.sh` (indexes sales if `crossr_sales.db` is missing, then starts the API).

Docker (after the sales index exists):

```bash
docker compose up --build
```

Do not upload `sales_data/` or stakes CSVs to a public frontend host.

## CLI

```bash
python3 main.py
```

1. Search a horse profile / pedigree  
2. Farm rosters  
3. Interactive pedigree builder (`add_pedigrees.py`)  
4. Stallion stats  
5. Hypomating  
6. Sales history  

If a horse is missing from `pedigrees_database.py`, the builder walks the 5-generation tree and writes it back.

## Horse profile panels

On `/horses/{name}` (and in the CLI stallion printout):

| Panel | Source |
| --- | --- |
| Pedigree + female family | `pedigrees_database.py` |
| Stud fee & mares bred | `stud_fee_database.csv`, `live_foal_statistics/` |
| **Stallion rankings** | BloodHorse lists in `stallion_rankings_data/` (2001–2026), plus computed mares-bred and USD stud-fee ranks |
| **Broodmare sire** | Leading Broodmare Sires lists + average sold yearling price (damsire) from `crossr_sales.db` |

Ranking dropdowns only include lists that stallion actually appears on. Years before he entered stud are omitted. **2027 stud fees are hidden.**

- **Leading Sire Rankings** — year, rank, total progeny earnings that year  
- **Stud Fee Rankings** — year, rank, stud fee (USD only; Private / foreign currency unranked)  
- Other BloodHorse lists (first/second/third crop, 2YO, turf, AEI, international regions, etc.) — year and rank  

## Data

| Path | Role |
| --- | --- |
| `pedigrees_database.py` | 5-generation trees (live file; importer writes here) |
| `stallion_profiles.py` | Commercial stallion cards (farm, fee, crop, race record) |
| `stallion_rankings_data/` | Year folders of BloodHorse ranking CSVs (28 lists × 2001–2026) |
| `stud_fee_database.csv` | Year / stallion / advertised fee |
| `live_foal_statistics/` | Jockey Club-style mares bred / live foals |
| `ifha_scraper/ifha_graded_stakes_2003_2026.csv` | IFHA G1–G3 results, worldwide |
| `graded_stakes_winners.csv` | Derived GSW file used by hypomating |
| `sales_data/` | Catalog CSVs (API only) |
| `crossr_sales.db` | Indexed lots (`scripts/index_sales.py`) |

## Pipelines (optional)

**Pedigrees from Pedigree Query.** Headed Chrome is the primary path (live PQ blocks curl). After graded-stakes horses are in the DB or are real terminal misses, `--queue auto` walks incomplete ancestor slots the same way `pedigrees_cleaner.py` would. Wayback is a polite fallback only and is paused for a few days after an IP block (`pq_scraper/wayback_pause_until.txt`).

```bash
python3 pq_scraper/fetch_pedigrees.py --resume --retry-misses --queue auto --source live --delay 1.5 --save-every 10
```

The live job is a LaunchAgent (`com.maxsoncook.pq.fetch-gsw`) plus a 5-minute heartbeat watchdog (`com.maxsoncook.pq.fetch-watchdog`). Progress: `pq_scraper/progress.json` (`last_added`, `last_attempt`, `heartbeat_at`). Misses: `pq_scraper/misses.csv`. HTTP 0 / connect failures are **not** 404s. Do not raise Wayback concurrency.

If a horse already has sire/dam names and those parents are in `pedigrees_database.py`, stitch the parent trees in (no network):

```bash
python3 -m pq_scraper.stitch
```

**IFHA graded stakes** (2003–2026): scrapers and checks live under `ifha_scraper/`. Output CSV is `ifha_scraper/ifha_graded_stakes_2003_2026.csv`.

**BloodHorse stallion lists**: yearly CSVs under `stallion_rankings_data/{year}/`. Stud-fee compilation: `stallion_rankings_data/build_stud_fee_database.py`.

**Equibase race records** (headed Chrome; Imperva blocks scripted fetches). Queue is the top-level horses in `pedigrees_database.py`. Results go in `equibase_results.db` at the repo root (year totals and each start). Raw HTML is cached under `equibase_scraper/cache/`. The full pass is long — about two days at the default delay — and resumable: horses already marked ok are skipped. If Chrome shows “Pardon Our Interruption,” finish that page once and rerun the same command.

```bash
python3 -m equibase_scraper.run --enqueue
python3 -m equibase_scraper.run --resume --delay 3
python3 -m equibase_scraper.run --horse "American Pharoah" --year 2012
python3 -m equibase_scraper.run --show "American Pharoah" --year 2012
python3 -m equibase_scraper.run --fill-pedigrees --delay 1
```

**Re-index sales** after adding catalogs:

```bash
python3 scripts/index_sales.py
```

## Layout

```
main.py                 CLI + shared name cleaning / pedigree lookup
hypomating_engine.py    Mating suggestions from GSW crosses
crossr_api/             FastAPI JSON API (:8000)
crossr_core/            Horse profiles, sales queries, auth
web/                    Next.js 14 UI (:3000)
pq_scraper/             Pedigree Query / Wayback importer
ifha_scraper/           IFHA graded-stakes scrape + validation
stallion_rankings_data/ BloodHorse ranking CSVs + fee builders
scripts/                Sales indexer, API helper
```

Web routes: `/` home, `/stallions`, `/horses/[name]`, `/hypomating`, `/sales`, `/compare`, `/barn`, `/signin`.
