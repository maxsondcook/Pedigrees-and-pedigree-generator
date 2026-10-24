#!/usr/bin/env python3
"""Load schema.sql, then every placeholderdatabase CSV, into DATABASE_URL.

When Railway is back, from the repo root:

    DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DB python scripts/load_railway.py

This script does not call the Railway API and does not create a project.
It refuses to run unless DATABASE_URL is already set.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import placeholder_store

LOAD_ORDER = [
    "industry_roles",
    "accounts",
    "clients",
    "client_preferences",
    "horses",
    "pedigree_lines",
    "sales",
    "sale_results",
    "catalog_hips",
    "stallion_stats",
    "broodmare_sire_stats",
    "mares_bred",
    "graded_stakes_winners",
    "notes",
    "hypothetical_matings",
]


def main():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is not set. Refusing to connect. Nothing was uploaded.")
        sys.exit(1)
    try:
        import psycopg
    except ImportError:
        print("Install psycopg first: pip install 'psycopg[binary]'")
        sys.exit(1)

    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
            for table in reversed(LOAD_ORDER):
                cur.execute(f"DELETE FROM {table}")
            for table in LOAD_ORDER:
                columns = placeholder_store.TABLES[table]
                rows = placeholder_store._load_csv(table)
                if not rows:
                    print(f"  {table}: 0 rows")
                    continue
                placeholders = ", ".join(["%s"] * len(columns))
                payload = []
                for row in rows:
                    values = []
                    for column in columns:
                        text = row.get(column, "")
                        values.append(None if text == "" else text)
                    payload.append(tuple(values))
                cur.executemany(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                    payload,
                )
                print(f"  {table}: {len(payload)} rows")
        conn.commit()
    print("Schema and placeholder CSVs loaded.")


if __name__ == "__main__":
    main()
