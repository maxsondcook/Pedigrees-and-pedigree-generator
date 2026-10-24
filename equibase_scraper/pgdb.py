"""Postgres storage for Equibase race records: the db.py API on race_* tables.

run.py uses this instead of the SQLite db.py whenever DATABASE_URL is set.
Tables (all TEXT columns, see crossr_core.sample_db.TABLES):

    horses     -> race_horses
    year_stats -> race_seasons
    starts     -> race_starts

New ids come from sequences seeded past the highest existing id. Writes do not
bump crossr_table_versions; call ``flush_versions`` every so often so the API
reloads once per batch instead of once per horse.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from crossr_core.sample_db import TABLES  # noqa: E402

HORSES = "race_horses"
SEASONS = "race_seasons"
STARTS = "race_starts"
RACE_TABLES = (HORSES, SEASONS, STARTS)
DB_PATH = Path("postgres")  # run.py prints DB_PATH.name

_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_race_horses_pedigree_key ON race_horses (pedigree_key);
CREATE INDEX IF NOT EXISTS idx_race_horses_name_year ON race_horses (name_key, foal_year);
CREATE INDEX IF NOT EXISTS idx_race_horses_refno ON race_horses (equibase_refno);
CREATE INDEX IF NOT EXISTS idx_race_horses_status ON race_horses (status);
CREATE INDEX IF NOT EXISTS idx_race_seasons_horse ON race_seasons (horse_id);
CREATE INDEX IF NOT EXISTS idx_race_starts_horse ON race_starts (horse_id);
CREATE INDEX IF NOT EXISTS idx_race_starts_date ON race_starts (race_date);
CREATE SEQUENCE IF NOT EXISTS crossr_race_horses_id_seq;
CREATE SEQUENCE IF NOT EXISTS crossr_race_seasons_id_seq;
CREATE SEQUENCE IF NOT EXISTS crossr_race_starts_id_seq;
"""


def enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL", "").strip())


def _cell(value):
    """TEXT columns: None for blanks (matches railway_db COPY), str otherwise."""
    if value is None:
        return None
    text = str(value)
    return text if text.strip() != "" else None


class PgConn:
    """Autocommit psycopg connection that reconnects once if the proxy drops it.

    run.py calls ``conn.commit()`` after each write; with autocommit that is a
    no-op, and multi-statement writes use ``transaction()``.
    """

    def __init__(self, url: str):
        self.url = url
        self._conn = None

    def raw(self):
        import psycopg
        from psycopg.rows import dict_row

        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                self.url, autocommit=True, row_factory=dict_row, connect_timeout=20
            )
        return self._conn

    def execute(self, sql: str, params=None):
        import psycopg

        try:
            return self.raw().execute(sql, params)
        except psycopg.OperationalError:
            self._conn = None
            time.sleep(2)
            return self.raw().execute(sql, params)

    def transaction(self):
        return self.raw().transaction()

    def cursor(self):
        return self.raw().cursor()

    def commit(self) -> None:
        pass

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None


def ensure_schema(conn: PgConn) -> None:
    from crossr_core import railway_db

    railway_db.ensure_schema()
    conn.execute(_SCHEMA)
    for table in RACE_TABLES:
        seq = f"crossr_{table}_id_seq"
        conn.execute(
            f"SELECT setval('{seq}', GREATEST("
            f"(SELECT COALESCE(MAX(id::bigint), 0) FROM {table} WHERE id ~ '^[0-9]+$'), "
            f"(SELECT last_value FROM {seq}), 1))"
        )


def connect(path: Path | None = None) -> PgConn:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    conn = PgConn(url)
    ensure_schema(conn)
    return conn


def _next_id(conn: PgConn, table: str) -> str:
    return str(conn.execute(f"SELECT nextval('crossr_{table}_id_seq') AS n").fetchone()["n"])


def flush_versions(conn: PgConn, tables=RACE_TABLES) -> None:
    """Bump crossr_table_versions so the API reloads the changed tables."""
    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        conn.execute(
            "INSERT INTO crossr_table_versions (table_name, version, row_count, updated_at) "
            "VALUES (%s, %s, %s, now()) ON CONFLICT (table_name) DO UPDATE SET "
            "version = EXCLUDED.version, row_count = EXCLUDED.row_count, updated_at = now()",
            (table, time.time(), int(count)),
        )


# ---------------------------------------------------------------------------
# db.py API
# ---------------------------------------------------------------------------

def upsert_pending(conn: PgConn, subj: dict) -> None:
    """Insert a queue row. Existing ok/not_found/ambiguous rows keep their status."""
    key = subj["pedigree_key"]
    params = (
        _cell(subj.get("name_key")),
        _cell(subj.get("foal_year")),
        _cell(subj.get("display_name")),
        key,
    )
    with conn.transaction():
        found = conn.execute(
            f"SELECT id FROM {HORSES} WHERE pedigree_key = %s LIMIT 1", (key,)
        ).fetchone()
        if found:
            conn.execute(
                f"UPDATE {HORSES} SET name_key = %s, foal_year = %s, display_name = %s "
                "WHERE pedigree_key = %s AND status IN ('pending', 'error', 'blocked')",
                params,
            )
            return
        conn.execute(
            f"INSERT INTO {HORSES} (id, name_key, foal_year, display_name, pedigree_key, status) "
            "VALUES (%s, %s, %s, %s, %s, 'pending')",
            (_next_id(conn, HORSES), *params),
        )


def get_by_id(conn: PgConn, horse_id) -> dict | None:
    return conn.execute(
        f"SELECT * FROM {HORSES} WHERE id = %s", (str(horse_id),)
    ).fetchone()


def find_by_equibase_refno(conn: PgConn, refno: str | None) -> dict | None:
    token = str(refno or "").strip()
    if not token:
        return None
    return conn.execute(
        f"""
        SELECT * FROM {HORSES}
        WHERE equibase_refno = %s
        ORDER BY CASE status WHEN 'ok' THEN 0 ELSE 1 END, id::bigint
        LIMIT 1
        """,
        (token,),
    ).fetchone()


def ok_horses(conn: PgConn) -> list[dict]:
    return conn.execute(
        f"SELECT * FROM {HORSES} WHERE status = 'ok' ORDER BY id::bigint"
    ).fetchall()


def find_horses(conn: PgConn, query: str, name_key: str, year: str | None) -> list[dict]:
    year_s = str(year).strip() if year else ""
    rows = conn.execute(
        f"""
        SELECT * FROM {HORSES}
        WHERE pedigree_key = %s OR pedigree_key = %s
        ORDER BY foal_year, pedigree_key
        """,
        (query.strip(), query.strip().upper()),
    ).fetchall()
    if not rows and name_key:
        if year_s:
            rows = conn.execute(
                f"SELECT * FROM {HORSES} WHERE name_key = %s AND foal_year = %s ORDER BY pedigree_key",
                (name_key, year_s),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM {HORSES} WHERE name_key = %s ORDER BY foal_year, pedigree_key",
                (name_key,),
            ).fetchall()
    elif year_s:
        rows = [row for row in rows if (row["foal_year"] or "") == year_s]
    return list(rows)


def insert_batch_horse(conn: PgConn, subj: dict) -> bool:
    """Insert one new queue row. An existing pedigree_key, including ok, is left alone."""
    with conn.transaction():
        if conn.execute(
            f"SELECT 1 FROM {HORSES} WHERE pedigree_key = %s LIMIT 1", (subj["pedigree_key"],)
        ).fetchone():
            return False
        conn.execute(
            f"""
            INSERT INTO {HORSES} (
                id, pedigree_key, name_key, foal_year, display_name,
                sire, dam, sex, status, queue_batch
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)
            """,
            (
                _next_id(conn, HORSES),
                subj["pedigree_key"],
                _cell(subj.get("name_key")),
                _cell(subj.get("foal_year")),
                _cell(subj.get("display_name")),
                _cell(subj.get("sire")),
                _cell(subj.get("dam")),
                _cell(subj.get("sex")),
                _cell(subj.get("queue_batch")),
            ),
        )
    return True


def resume_horses(conn: PgConn, batch: str | None = None) -> list[dict]:
    if batch:
        return conn.execute(
            f"""
            SELECT * FROM {HORSES}
            WHERE queue_batch = %s AND status IN ('pending', 'error', 'blocked')
            ORDER BY id::bigint
            """,
            (batch,),
        ).fetchall()
    return conn.execute(
        f"SELECT * FROM {HORSES} WHERE status IN ('pending', 'error', 'blocked') ORDER BY id::bigint"
    ).fetchall()


def count_by_status(conn: PgConn) -> dict[str, int]:
    return {
        row["status"]: row["n"]
        for row in conn.execute(f"SELECT status, COUNT(*) AS n FROM {HORSES} GROUP BY status")
    }


def count_rows(conn: PgConn) -> int:
    return conn.execute(f"SELECT COUNT(*) AS n FROM {HORSES}").fetchone()["n"]


def mark_status(conn: PgConn, horse_id, status: str, detail: str, fetched_at: str) -> None:
    conn.execute(
        f"UPDATE {HORSES} SET status = %s, detail = %s, fetched_at = %s WHERE id = %s",
        (status, _cell((detail or "")[:500]), fetched_at, str(horse_id)),
    )


_PROFILE_FIELDS = (
    "foaled_in", "breed", "color", "sex", "foaled", "sire", "sire_refno", "dam",
    "dam_refno", "damsire", "damsire_refno", "jockey", "trainer", "owner",
    "breeder", "best_class", "equibase_refno", "registry", "profile_url",
)
_SEASON_FIELDS = (
    "year", "starts", "firsts", "seconds", "thirds", "highest_esf", "earnings",
    "earnings_per_start",
)
_START_FIELDS = (
    "race_date", "track", "track_code", "country", "race_number", "race_name",
    "grade", "breed", "place", "esf", "stakes_id", "chart_url", "video_url",
)


def save_profile(conn: PgConn, horse_id, profile: dict, status: str, detail: str, fetched_at: str) -> None:
    """Store the profile and replace that horse's seasons and starts in one transaction."""
    horse_id = str(horse_id)
    sets = ", ".join(f"{field} = %s" for field in _PROFILE_FIELDS)
    year = _cell(profile.get("foal_year"))
    with conn.transaction():
        conn.execute(
            f"""
            UPDATE {HORSES} SET
                display_name = COALESCE(%s, display_name),
                foal_year = COALESCE(%s, foal_year),
                {sets},
                status = %s, detail = %s, fetched_at = %s
            WHERE id = %s
            """,
            (
                _cell(profile.get("display_name")),
                year,
                *(_cell(profile.get(field)) for field in _PROFILE_FIELDS),
                status,
                _cell((detail or "")[:500]),
                fetched_at,
                horse_id,
            ),
        )
        conn.execute(f"DELETE FROM {SEASONS} WHERE horse_id = %s", (horse_id,))
        conn.execute(f"DELETE FROM {STARTS} WHERE horse_id = %s", (horse_id,))
        _insert_children(conn, SEASONS, _SEASON_FIELDS, horse_id, profile.get("year_stats") or [])
        _insert_children(conn, STARTS, _START_FIELDS, horse_id, profile.get("starts") or [])


def _insert_children(conn: PgConn, table: str, fields: tuple, horse_id: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = ", ".join(("id", "horse_id", *fields))
    marks = ", ".join(["%s"] * (len(fields) + 2))
    seq = f"crossr_{table}_id_seq"
    ids = [
        str(row["n"])
        for row in conn.execute(
            "SELECT nextval(%s) AS n FROM generate_series(1, %s)", (seq, len(rows))
        ).fetchall()
    ]
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {table} ({cols}) VALUES ({marks})",
            [
                (new_id, horse_id, *(_cell(row.get(field)) for field in fields))
                for new_id, row in zip(ids, rows)
            ],
        )


def year_rows(conn: PgConn, horse_id) -> list[dict]:
    return conn.execute(
        f"SELECT * FROM {SEASONS} WHERE horse_id = %s ORDER BY year", (str(horse_id),)
    ).fetchall()


def start_rows(conn: PgConn, horse_id) -> list[dict]:
    return conn.execute(
        f"""
        SELECT * FROM {STARTS} WHERE horse_id = %s
        ORDER BY race_date, NULLIF(regexp_replace(race_number, '[^0-9]', '', 'g'), '')::int, id::bigint
        """,
        (str(horse_id),),
    ).fetchall()


# ---------------------------------------------------------------------------
# Pedigrees (no version bump per write; see flush_versions)
# ---------------------------------------------------------------------------

def load_pedigree_map(conn: PgConn) -> dict:
    """All trees, with identical subtrees shared (about 5x less memory).

    Shared nodes are safe because pedigree_fill copies before it changes a tree.
    """
    canon: dict = {}

    def intern(node):
        out = {}
        for key, value in node.items():
            if isinstance(value, dict):
                value = intern(value)
            elif isinstance(value, str):
                value = sys.intern(value)
            out[sys.intern(key)] = value
        try:
            sig = tuple(
                (key, id(value) if isinstance(value, dict) else value)
                for key, value in sorted(out.items())
            )
        except TypeError:
            return out
        return canon.setdefault(sig, out)

    from psycopg.rows import tuple_row

    out: dict = {}
    raw = conn.raw()
    with raw.transaction(), raw.cursor(name="pedigree_stream", row_factory=tuple_row) as cur:
        cur.itersize = 2000
        cur.execute("SELECT key, tree::text FROM pedigrees")
        for key, text in cur:
            tree = json.loads(text)
            out[key] = intern(tree) if isinstance(tree, dict) else tree
    return out


def upsert_pedigrees(conn: PgConn, items: dict) -> int:
    if not items:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO pedigrees (key, tree, updated_at) VALUES (%s, %s::jsonb, now()) "
            "ON CONFLICT (key) DO UPDATE SET tree = EXCLUDED.tree, updated_at = now()",
            [(str(key), json.dumps(tree)) for key, tree in items.items()],
        )
    return len(items)
