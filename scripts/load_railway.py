#!/usr/bin/env python3
"""Load schema_entity_csvs.sql + the 8 sample CSVs into DATABASE_URL.

When Railway is back, from the repo root:

    DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DB python scripts/load_railway.py

Refuses to run unless DATABASE_URL is set. Pedigrees stay in pedigrees_database.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossr_core import sample_db


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

    schema = (ROOT / "schema_entity_csvs.sql").read_text(encoding="utf-8")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
            for table, columns in sample_db.TABLES.items():
                rows = sample_db.load_table(table, refresh=True)
                if not rows:
                    print(f"  {table}: 0 rows")
                    continue
                placeholders = ", ".join(["%s"] * len(columns))
                col_sql = ", ".join(f'"{c}"' for c in columns)
                payload = []
                for row in rows:
                    values = []
                    for column in columns:
                        text = row.get(column, "")
                        values.append(None if text == "" else text)
                    payload.append(tuple(values))
                cur.executemany(
                    f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})",
                    payload,
                )
                print(f"  {table}: {len(payload)} rows")
        conn.commit()
    print("Schema and sample CSVs loaded.")


if __name__ == "__main__":
    main()
