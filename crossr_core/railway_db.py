"""Railway Postgres backend for Crossr.

Turned on by setting DATABASE_URL (Railway injects it into any service that
references its Postgres database). When it is unset, Crossr keeps using the local
files: data/*.csv for the 8 tables and pedigrees_database.py for pedigrees.

Tables
------
* The 8 runtime tables, one per CSV, with the exact CSV headers as TEXT columns
  (see crossr_core.sample_db.TABLES).
* pedigrees(key, tree JSONB) - the pedigree_map from pedigrees_database.py.
* crossr_table_versions - bumped on every write so the API reloads a table only
  when it changed (replaces the CSV mtime check).
* users / sessions / preferences - accounts and saved barns (crossr_core.auth).
* upcoming_lot_marks - starred hips and notes on Upcoming Sales catalogs, so they
  survive redeploys (the catalog CSVs ship inside the container).
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from typing import Iterable

_VERSION_TTL = float(os.environ.get("CROSSR_DB_VERSION_TTL", "15"))
_version_cache: dict[str, tuple[float, float]] = {}
_lock = threading.RLock()
_schema_ready = False


def database_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def enabled() -> bool:
    return bool(database_url()) and os.environ.get("CROSSR_FORCE_CSV", "").lower() not in {"1", "true", "yes"}


def _psycopg():
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("DATABASE_URL is set but psycopg is missing: pip install 'psycopg[binary]'") from exc
    return psycopg


@contextmanager
def connect():
    psycopg = _psycopg()
    conn = psycopg.connect(database_url(), connect_timeout=10)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def schema_sql() -> str:
    from crossr_core.sample_db import TABLES, UPSERT_KEYS

    parts = [
        "CREATE TABLE IF NOT EXISTS crossr_table_versions (\n"
        "    table_name TEXT PRIMARY KEY,\n"
        "    version DOUBLE PRECISION NOT NULL,\n"
        "    row_count BIGINT,\n"
        "    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()\n);",
    ]
    for table, columns in TABLES.items():
        cols = ",\n".join(f"    {_q(c)} TEXT" for c in columns)
        parts.append(f"CREATE TABLE IF NOT EXISTS {_q(table)} (\n{cols}\n);")
        keys = UPSERT_KEYS.get(table) or ()
        if keys:
            idx_cols = ", ".join(_q(k) for k in keys)
            parts.append(f"CREATE INDEX IF NOT EXISTS {_q('idx_' + table + '_key')} ON {_q(table)} ({idx_cols});")
    parts.append(
        "CREATE TABLE IF NOT EXISTS pedigrees (\n"
        "    key TEXT PRIMARY KEY,\n"
        "    tree JSONB NOT NULL,\n"
        "    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()\n);"
    )
    parts.append(
        "CREATE TABLE IF NOT EXISTS users (\n"
        "    id BIGSERIAL PRIMARY KEY,\n"
        "    email TEXT NOT NULL UNIQUE,\n"
        "    username TEXT NOT NULL UNIQUE,\n"
        "    password_hash TEXT NOT NULL,\n"
        "    created_at BIGINT NOT NULL\n);\n"
        "CREATE TABLE IF NOT EXISTS sessions (\n"
        "    token TEXT PRIMARY KEY,\n"
        "    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,\n"
        "    created_at BIGINT NOT NULL,\n"
        "    expires_at BIGINT NOT NULL\n);\n"
        "CREATE TABLE IF NOT EXISTS preferences (\n"
        "    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,\n"
        "    payload TEXT NOT NULL,\n"
        "    updated_at BIGINT NOT NULL\n);"
    )
    parts.append(
        "CREATE TABLE IF NOT EXISTS upcoming_lot_marks (\n"
        "    catalog_id TEXT NOT NULL,\n"
        "    hip TEXT NOT NULL,\n"
        "    starred BOOLEAN,\n"
        "    notes TEXT,\n"
        "    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),\n"
        "    PRIMARY KEY (catalog_id, hip)\n);"
    )
    return "\n\n".join(parts) + "\n"


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _lock:
        if _schema_ready:
            return
        with connect() as conn:
            conn.execute(schema_sql())
        _schema_ready = True


# ---------------------------------------------------------------------------
# The 8 tables
# ---------------------------------------------------------------------------

def read_table(table: str, columns: Iterable[str]) -> list[dict]:
    ensure_schema()
    columns = list(columns)
    col_sql = ", ".join(_q(c) for c in columns)
    with connect() as conn:
        cur = conn.execute(f"SELECT {col_sql} FROM {_q(table)}")
        return [{c: ("" if v is None else str(v)) for c, v in zip(columns, rec)} for rec in cur]


def iter_table(table: str, columns: Iterable[str], batch: int = 5000):
    """Stream rows as tuples of strings (server-side cursor, no full-table list)."""
    ensure_schema()
    columns = list(columns)
    col_sql = ", ".join(_q(c) for c in columns)
    with connect() as conn:
        with conn.cursor(name=f"iter_{table}") as cur:
            cur.itersize = batch
            cur.execute(f"SELECT {col_sql} FROM {_q(table)}")
            for rec in cur:
                yield tuple("" if v is None else str(v) for v in rec)


def table_version(table: str, max_age: float | None = None) -> float:
    """Version stamp for a table (0.0 when never loaded). Cached for a few seconds."""
    max_age = _VERSION_TTL if max_age is None else max_age
    now = time.monotonic()
    with _lock:
        hit = _version_cache.get(table)
        if hit and now - hit[0] < max_age:
            return hit[1]
    ensure_schema()
    with connect() as conn:
        rec = conn.execute(
            "SELECT version FROM crossr_table_versions WHERE table_name = %s", (table,)
        ).fetchone()
    version = float(rec[0]) if rec else 0.0
    with _lock:
        _version_cache[table] = (now, version)
    return version


def _bump(conn, table: str, row_count: int | None) -> float:
    version = time.time()
    conn.execute(
        "INSERT INTO crossr_table_versions (table_name, version, row_count, updated_at) "
        "VALUES (%s, %s, %s, now()) ON CONFLICT (table_name) DO UPDATE SET "
        "version = EXCLUDED.version, row_count = EXCLUDED.row_count, updated_at = now()",
        (table, version, row_count),
    )
    with _lock:
        _version_cache[table] = (time.monotonic(), version)
    return version


def replace_table(table: str, columns: Iterable[str], rows: Iterable[dict]) -> int:
    """Swap a whole table in one transaction (readers never see it half-written).

    ``rows`` may be a list or a generator (streamed straight into COPY).
    """
    ensure_schema()
    columns = list(columns)
    col_sql = ", ".join(_q(c) for c in columns)
    count = 0
    with connect() as conn:
        conn.execute(f"DELETE FROM {_q(table)}")
        with conn.cursor() as cur:
            with cur.copy(f"COPY {_q(table)} ({col_sql}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row([(None if row.get(c, "") in ("", None) else str(row.get(c))) for c in columns])
                    count += 1
        _bump(conn, table, count)
    return count


def row_counts() -> dict[str, int]:
    ensure_schema()
    with connect() as conn:
        return {
            name: int(count or 0)
            for name, count in conn.execute(
                "SELECT table_name, row_count FROM crossr_table_versions ORDER BY table_name"
            )
        }


# ---------------------------------------------------------------------------
# Pedigrees
# ---------------------------------------------------------------------------

def read_pedigree_map(compact: bool = False) -> dict:
    """All trees. ``compact`` returns a CompactPedigreeMap of JSON bytes, which
    streams rows as text so the full set is never parsed into dicts at once."""
    ensure_schema()
    with connect() as conn:
        if not compact:
            return {key: tree for key, tree in conn.execute("SELECT key, tree FROM pedigrees")}
        from crossr_core.pedigree_store import CompactPedigreeMap

        out = CompactPedigreeMap()
        with conn.cursor(name="pedigrees_stream") as cur:
            cur.itersize = 2000
            cur.execute("SELECT key, tree::text FROM pedigrees")
            for key, text in cur:
                out.set_raw(key, text.encode())
        return out


def upsert_pedigrees(items: dict, batch: int = 2000) -> int:
    """Insert or replace pedigree trees by key (used by scrapers / the CLI)."""
    if not items:
        return 0
    ensure_schema()
    _psycopg()
    from psycopg.types.json import Jsonb  # type: ignore

    pairs = list(items.items())
    with connect() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(pairs), batch):
                cur.executemany(
                    "INSERT INTO pedigrees (key, tree, updated_at) VALUES (%s, %s, now()) "
                    "ON CONFLICT (key) DO UPDATE SET tree = EXCLUDED.tree, updated_at = now()",
                    [(str(k), Jsonb(v)) for k, v in pairs[i:i + batch]],
                )
        count = conn.execute("SELECT count(*) FROM pedigrees").fetchone()[0]
        _bump(conn, "pedigrees", int(count))
    return len(pairs)


def replace_pedigrees(items: dict) -> int:
    """Load a full pedigree_map with COPY (initial Railway load)."""
    ensure_schema()
    with connect() as conn:
        conn.execute("DELETE FROM pedigrees")
        with conn.cursor() as cur:
            with cur.copy("COPY pedigrees (key, tree) FROM STDIN") as copy:
                for key, tree in items.items():
                    copy.write_row([str(key), json.dumps(tree)])
        _bump(conn, "pedigrees", len(items))
    return len(items)


# ---------------------------------------------------------------------------
# Upcoming Sales marks (starred hips + notes)
# ---------------------------------------------------------------------------

def read_lot_marks(catalog_id: str) -> dict[str, dict]:
    """hip -> {"starred": bool|None, "notes": str|None} for one catalog."""
    ensure_schema()
    with connect() as conn:
        return {
            hip: {"starred": starred, "notes": notes}
            for hip, starred, notes in conn.execute(
                "SELECT hip, starred, notes FROM upcoming_lot_marks WHERE catalog_id = %s",
                (catalog_id,),
            )
        }


def set_lot_mark(catalog_id: str, hip: str, starred: bool | None = None, notes: str | None = None) -> dict:
    """Upsert a mark; a None field keeps its stored value. Returns the stored mark."""
    ensure_schema()
    with connect() as conn:
        starred_out, notes_out = conn.execute(
            "INSERT INTO upcoming_lot_marks (catalog_id, hip, starred, notes, updated_at) "
            "VALUES (%s, %s, %s, %s, now()) ON CONFLICT (catalog_id, hip) DO UPDATE SET "
            "starred = COALESCE(EXCLUDED.starred, upcoming_lot_marks.starred), "
            "notes = COALESCE(EXCLUDED.notes, upcoming_lot_marks.notes), updated_at = now() "
            "RETURNING starred, notes",
            (catalog_id, hip, starred, notes),
        ).fetchone()
    return {"starred": starred_out, "notes": notes_out}
