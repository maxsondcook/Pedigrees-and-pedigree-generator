# Data pipeline

Keeps Railway Postgres current from the Mac. Everything writes straight to
Postgres; no CSV or SQLite staging.

| Job | What it does | When |
| --- | --- | --- |
| `pedigrees-sales` | Sire and dam of every lot in `sales_lots`, filled to a full 5-generation tree from Equibase. Every horse opened on the way is stored as a race record too. | continuously (the `scrape` loop) |
| `races-refresh` | Re-opens each ok horse with a start in the last 60 days, so new starts and earnings land in `race_seasons` / `race_starts`. | weekly, inside the `scrape` loop |
| `sales-import` | Loads new or changed `sales_data/*.csv` into `sales_lots`, replacing only that file's rows. | daily at 07:00 |
| `racing-post-fees` | Racing Post fee history for every sire in `breeding_seasons` or `sales_lots`. Every row (fee, currency, private, country, standing) goes to `racing_post_fees`; `stud_fees` only gains years it had no fee for (existing fees win). | continuously (`racing-post --loop`); found sires are re-checked after 180 days |

## Running it

Every command needs `DATABASE_URL`. `scripts/pipeline/railway_env.sh` builds
it from the Railway CLI. The first argument is the database: `railway`
(production) or `crossr_dev` (the test database on the same server).

```bash
cd ~/Desktop/Crossr
E=scripts/pipeline/railway_env.sh
PY=.venv/bin/python

$E railway $PY -m crossr_pipeline status                   # what ran, queue state, counts
$E railway $PY -m crossr_pipeline scrape                   # the loop (runs until stopped)
$E railway $PY -m crossr_pipeline scrape --limit 20        # 20 queue items, then exit
$E railway $PY -m crossr_pipeline scrape --refresh-only    # just the weekly race refresh
$E railway $PY -m crossr_pipeline sales-import --dry-run   # list what would load
$E railway $PY -m crossr_pipeline sales-import             # load new/changed sale files
$E railway $PY -m crossr_pipeline sales-import --force keeneland_2026_september_yearling_sale.csv
```

Test against `crossr_dev` first by swapping `railway` for `crossr_dev`.

`.venv` needs `psycopg[binary]`, `playwright`, `beautifulsoup4`, `lxml`,
`pandas` (`pip install -r requirements.txt playwright`). Playwright uses your
installed Chrome (`channel="chrome"`), so no browser download is needed.

### After a sale

Download the sale's results file. Save it as a CSV in `sales_data/`, named the
same way as the others (`<company>_<year>_<sale>.csv`). The 07:00 job loads it,
or run `sales-import` yourself. Its new sires and dams join the pedigree queue
on the next pass.

## How the scrape works

- **One Chrome window**, the headed persistent profile the Equibase scraper
  already used (`equibase_scraper/chrome_profile`), about 3 s plus jitter
  between page loads.
- **Queue order:** sires first, then dams, each by their most recent sale
  (newest first), then by number of lots. Parents already complete in
  `pedigrees` are skipped.
- **Matching a sale parent to Equibase.** Sales give a name but no foal year,
  so a search is narrowed by:
  - thoroughbreds only;
  - the right sex (stallion for a sire, mare for a dam);
  - for a dam, the lot's damsire;
  - a foal-year window from the parent's sale foals (sire aged 3–30 and dam
    aged 3–25 at each foal's birth).

  Several hits after all that are recorded as `ambiguous` and not guessed.
- **Trees** are built from Equibase sire/dam refnos. Ancestors already in
  `pedigrees` are grafted in instead of re-fetched. Horses born before 1970
  are leaves.
- **Table versions** (what makes the API reload) are bumped every 30 minutes
  and at the end of a pass, not after every horse.

### Racing Post fees

`python -m crossr_pipeline racing-post [--limit N]` uses its own Chrome window
(`crossr_pipeline/chrome_profile_racingpost`), plain Playwright with no
stealth settings. For each sire it does two page loads:

1. `racingpost.com/search-results/?keyword=<name>`. Results read
   "Name (CTY) - YYYY". It keeps exact-name hits, then prefers the sire's
   country suffix (USA when there is none), then a foal-year window from its
   crops.
2. The horse's `fee-history` page (Sales Record → Fee History).

Added `stud_fees` rows have `Source List` = "Racing Post fee history":
- `Farm` is where the horse stood that year;
- `Notes` holds the Racing Post id, country and currency;
- non-USD fees keep their currency ("EUR 5,000");
- private fees are stored as "Private", not 0.

Item states are `found`, `no_fees`, `no_match` (retried after a year),
`ambiguous` (never retried) and `error` (retried after 3 days).

### Blocks

The Chrome profile lives in the checkout (`equibase_scraper/chrome_profile`,
gitignored). A new checkout starts with an empty profile, so expect to clear
one check on the first run.

When Equibase shows its "Pardon Our Interruption" check, the loop pauses and
sends a Mac notification, again every hour until someone clears the check in
the open Chrome window. Then it carries on with the same horse. The pipeline
never tries to get past the check by itself.

**Terms of service:** Equibase's terms forbid automated collection without
written permission. Running this is your decision and risk; at full speed a
block or an IP ban is likely.

### Retries

The state of each queue item is in `crossr_pipeline_queue`:

| status | meaning | retried |
| --- | --- | --- |
| `complete` | full 5-gen tree stored | never |
| `incomplete` | profile found, some ancestors missing on Equibase | after 30 days |
| `not_found` / `ambiguous` / `year_mismatch` | no single matching profile | never (delete the row to retry) |
| `error` | page or network error | after 3 days |

The loop stops after 8 errors in a row (usually Chrome closed); launchd starts
it again 5 minutes later.

## Scheduling (launchd)

launchd jobs can't read `~/Desktop` (macOS privacy rules), so the jobs run
from a separate clone at `~/Crossr-pipeline` with its own `.venv`, linked to
Railway once with `railway link` inside it. After merging new pipeline code
into `unified` on the Desktop checkout, update the clone:

```bash
git -C ~/Crossr-pipeline pull
launchctl kickstart -k gui/$(id -u)/com.crossr.pipeline.scrape
```

Install the agents from the clone:

```bash
.venv/bin/python -m crossr_pipeline install-launchd --db railway   # writes the plists, loads nothing
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.crossr.pipeline.scrape.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.crossr.pipeline.sales-import.plist
```

Stop with `launchctl bootout gui/$(id -u) <plist>`.

- **`com.crossr.pipeline.scrape`** starts at login and runs under
  `caffeinate -i`, so the Mac doesn't idle-sleep mid-run. launchd restarts it
  5 minutes after it exits.
- **`com.crossr.pipeline.sales-import`** runs daily at 07:00. If the Mac was
  asleep at 07:00, it runs on wake.
- **Logs** go to `logs/pipeline/scrape.log` and `logs/pipeline/sales-import.log`.
- **No password on disk:** the plists call `railway_env.sh`, which asks the
  Railway CLI for the database URL each time a job starts.
- **Location:** install from the checkout the jobs should run from
  (`~/Desktop/Crossr` on `unified`), because the plists point at that folder.

The old `com.maxsoncook.pq.fetch-gsw` / `fetch-watchdog` agents (pedigreequery)
are separate; leave them unloaded.

## Monitoring

- `python -m crossr_pipeline status` lists the last runs with their counts.
  A `running` row with no heartbeat for over an hour means the process died.
- Recent run history lives in `crossr_pipeline_runs` (job, status
  ok/partial/blocked/failed, counts JSON, detail, heartbeat).
- `tail -f logs/pipeline/scrape.log` shows each horse as it goes.

## Tables the pipeline adds

- `crossr_pipeline_runs`: run log.
- `crossr_pipeline_queue`: per-item state for `pedigrees-sales`.
- `crossr_pipeline_files`: sha256 of each loaded sales CSV. On the first run,
  files already in `sales_lots` are recorded without a reload.
- Sequences `crossr_race_*_id_seq` for new race ids, plus indexes on
  `race_horses` (pedigree_key, name_key + foal_year, refno, status) and on
  `race_seasons` / `race_starts` horse_id.
