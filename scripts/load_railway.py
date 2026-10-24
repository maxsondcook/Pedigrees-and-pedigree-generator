#!/usr/bin/env python3
"""Load Crossr's data into Railway Postgres.

Copies the 8 runtime tables (data/*.csv) and the pedigree map
(pedigrees_database.py) into the database named by DATABASE_URL.
Safe to re-run: each table is replaced in its own transaction.

    export DATABASE_URL="postgresql://..."     # Railway -> Postgres -> Connect (public URL)
    python scripts/load_railway.py             # everything
    python scripts/load_railway.py --only stud_fees sales_lots
    python scripts/load_railway.py --skip-pedigrees
    python scripts/load_railway.py --schema-only
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Read the source files from disk; writes still go to DATABASE_URL.
os.environ["CROSSR_FORCE_CSV"] = "1"


def _stream_csv(path: Path, columns: list[str]):
    """Yield rows one at a time so big tables (sales_lots, race_starts) never sit in RAM."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            yield {col: (raw.get(col) or "") for col in columns}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", help="load just these tables ('pedigrees' for the pedigree map)")
    parser.add_argument("--skip-pedigrees", action="store_true")
    parser.add_argument("--schema-only", action="store_true")
    args = parser.parse_args()

    from crossr_core import railway_db, sample_db

    if not railway_db.database_url():
        print("DATABASE_URL is not set. Copy it from Railway -> Postgres -> Connect, then:")
        print('  export DATABASE_URL="postgresql://..."')
        return 1

    railway_db.ensure_schema()
    print("Schema ready.")
    if args.schema_only:
        return 0

    wanted = set(args.only or [])
    for table, columns in sample_db.TABLES.items():
        if wanted and table not in wanted:
            continue
        path = sample_db.csv_path(table)
        if not path.exists():
            print(f"  {table:<18} skipped (no {path.relative_to(ROOT)})")
            continue
        started = time.time()
        count = railway_db.replace_table(table, columns, _stream_csv(path, columns))
        print(f"  {table:<18} {count:>9,} rows    ({time.time() - started:.1f}s)")

    if not args.skip_pedigrees and (not wanted or "pedigrees" in wanted):
        started = time.time()
        from pq_scraper.dbio import _load_file_map

        pedigree_map = _load_file_map()
        count = railway_db.replace_pedigrees(pedigree_map)
        del pedigree_map
        print(f"  {'pedigrees':<18} {count:>9,} horses  ({time.time() - started:.1f}s)")

    print("\nRow counts in Railway:")
    for name, count in railway_db.row_counts().items():
        print(f"  {name:<22} {count:>9,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
