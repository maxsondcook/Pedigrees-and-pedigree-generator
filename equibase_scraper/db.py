"""SQLite storage for Equibase race records. Not pedigrees_database.py."""

from __future__ import annotations

import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "equibase_results.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS horses (
    id INTEGER PRIMARY KEY,
    pedigree_key TEXT NOT NULL UNIQUE,
    name_key TEXT,
    foal_year TEXT,
    display_name TEXT,
    foaled_in TEXT,
    breed TEXT,
    color TEXT,
    sex TEXT,
    foaled TEXT,
    sire TEXT,
    sire_refno TEXT,
    dam TEXT,
    dam_refno TEXT,
    damsire TEXT,
    damsire_refno TEXT,
    jockey TEXT,
    trainer TEXT,
    owner TEXT,
    breeder TEXT,
    best_class TEXT,
    equibase_refno TEXT,
    registry TEXT,
    profile_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    detail TEXT,
    fetched_at TEXT,
    queue_batch TEXT
);

CREATE TABLE IF NOT EXISTS year_stats (
    id INTEGER PRIMARY KEY,
    horse_id INTEGER NOT NULL REFERENCES horses(id) ON DELETE CASCADE,
    year TEXT NOT NULL,
    starts INTEGER,
    firsts INTEGER,
    seconds INTEGER,
    thirds INTEGER,
    highest_esf INTEGER,
    earnings INTEGER,
    earnings_per_start INTEGER,
    UNIQUE (horse_id, year)
);

CREATE TABLE IF NOT EXISTS starts (
    id INTEGER PRIMARY KEY,
    horse_id INTEGER NOT NULL REFERENCES horses(id) ON DELETE CASCADE,
    race_date TEXT,
    track TEXT,
    track_code TEXT,
    country TEXT,
    race_number TEXT,
    race_name TEXT,
    grade TEXT,
    breed TEXT,
    place TEXT,
    esf INTEGER,
    stakes_id TEXT,
    chart_url TEXT,
    video_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_horses_status ON horses(status);
CREATE INDEX IF NOT EXISTS idx_horses_name_year ON horses(name_key, foal_year);
CREATE INDEX IF NOT EXISTS idx_starts_horse_date ON starts(horse_id, race_date);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(horses)")}
    if "queue_batch" not in columns:
        conn.execute("ALTER TABLE horses ADD COLUMN queue_batch TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_horses_batch ON horses(queue_batch)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_horses_refno ON horses(equibase_refno)"
    )


def connect(path: Path | None = None) -> sqlite3.Connection:
    dest = path or DB_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(dest, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def upsert_pending(conn: sqlite3.Connection, subj: dict) -> None:
    """Insert a queue row. Existing ok/not_found/ambiguous rows keep their status."""
    conn.execute(
        """
        INSERT INTO horses (pedigree_key, name_key, foal_year, display_name, status)
        VALUES (?, ?, ?, ?, 'pending')
        ON CONFLICT(pedigree_key) DO UPDATE SET
            name_key = excluded.name_key,
            foal_year = excluded.foal_year,
            display_name = excluded.display_name
        WHERE horses.status IN ('pending', 'error', 'blocked')
        """,
        (
            subj["pedigree_key"],
            subj.get("name_key") or "",
            subj.get("foal_year") or "",
            subj.get("display_name") or "",
        ),
    )


def get_by_id(conn: sqlite3.Connection, horse_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM horses WHERE id = ?", (horse_id,)).fetchone()


def find_by_equibase_refno(conn: sqlite3.Connection, refno: str | None) -> sqlite3.Row | None:
    token = str(refno or "").strip()
    if not token:
        return None
    return conn.execute(
        """
        SELECT * FROM horses
        WHERE equibase_refno = ?
        ORDER BY CASE status WHEN 'ok' THEN 0 ELSE 1 END, id
        LIMIT 1
        """,
        (token,),
    ).fetchone()


def ok_horses(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM horses WHERE status = 'ok' ORDER BY id"
        ).fetchall()
    )


def find_horses(
    conn: sqlite3.Connection,
    query: str,
    name_key: str,
    year: str | None,
) -> list[sqlite3.Row]:
    year_s = str(year).strip() if year else ""
    rows = conn.execute(
        """
        SELECT * FROM horses
        WHERE pedigree_key = ? OR pedigree_key = ?
        ORDER BY foal_year, pedigree_key
        """,
        (query.strip(), query.strip().upper()),
    ).fetchall()
    if not rows and name_key:
        if year_s:
            rows = conn.execute(
                """
                SELECT * FROM horses
                WHERE name_key = ? AND foal_year = ?
                ORDER BY pedigree_key
                """,
                (name_key, year_s),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM horses
                WHERE name_key = ?
                ORDER BY foal_year, pedigree_key
                """,
                (name_key,),
            ).fetchall()
    elif year_s:
        rows = [row for row in rows if (row["foal_year"] or "") == year_s]
    return list(rows)


def insert_batch_horse(conn: sqlite3.Connection, subj: dict) -> bool:
    """Insert one new queue row. An existing pedigree_key, including ok, is left alone."""
    cursor = conn.execute(
        """
        INSERT INTO horses (
            pedigree_key, name_key, foal_year, display_name,
            sire, dam, sex, status, queue_batch
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        ON CONFLICT(pedigree_key) DO NOTHING
        """,
        (
            subj["pedigree_key"],
            subj.get("name_key") or "",
            subj.get("foal_year") or "",
            subj.get("display_name") or "",
            subj.get("sire") or "",
            subj.get("dam") or "",
            subj.get("sex") or "",
            subj.get("queue_batch") or "",
        ),
    )
    return cursor.rowcount == 1


def resume_horses(conn: sqlite3.Connection, batch: str | None = None) -> list[sqlite3.Row]:
    """Horses still worth a fetch. ok / not_found / ambiguous / year_mismatch stay put.

    A batch limits the fetch to rows inserted for that list, so an older error
    outside the batch is not retried.
    """
    if batch:
        return list(
            conn.execute(
                """
                SELECT * FROM horses
                WHERE queue_batch = ?
                  AND status IN ('pending', 'error', 'blocked')
                ORDER BY id
                """,
                (batch,),
            ).fetchall()
        )
    return list(
        conn.execute(
            """
            SELECT * FROM horses
            WHERE status IN ('pending', 'error', 'blocked')
            ORDER BY id
            """
        ).fetchall()
    )


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM horses GROUP BY status"):
        counts[row["status"]] = row["n"]
    return counts


def mark_status(
    conn: sqlite3.Connection,
    horse_id: int,
    status: str,
    detail: str,
    fetched_at: str,
) -> None:
    conn.execute(
        """
        UPDATE horses
        SET status = ?, detail = ?, fetched_at = ?
        WHERE id = ?
        """,
        (status, (detail or "")[:500], fetched_at, horse_id),
    )


def save_profile(
    conn: sqlite3.Connection,
    horse_id: int,
    profile: dict,
    status: str,
    detail: str,
    fetched_at: str,
) -> None:
    conn.execute(
        """
        UPDATE horses SET
            display_name = COALESCE(?, display_name),
            foal_year = CASE
                WHEN ? IS NOT NULL AND TRIM(CAST(? AS TEXT)) != '' THEN ?
                ELSE foal_year
            END,
            foaled_in = ?,
            breed = ?,
            color = ?,
            sex = ?,
            foaled = ?,
            sire = ?,
            sire_refno = ?,
            dam = ?,
            dam_refno = ?,
            damsire = ?,
            damsire_refno = ?,
            jockey = ?,
            trainer = ?,
            owner = ?,
            breeder = ?,
            best_class = ?,
            equibase_refno = ?,
            registry = ?,
            profile_url = ?,
            status = ?,
            detail = ?,
            fetched_at = ?
        WHERE id = ?
        """,
        (
            profile.get("display_name"),
            profile.get("foal_year") or "",
            profile.get("foal_year") or "",
            profile.get("foal_year") or "",
            profile.get("foaled_in"),
            profile.get("breed"),
            profile.get("color"),
            profile.get("sex"),
            profile.get("foaled"),
            profile.get("sire"),
            profile.get("sire_refno"),
            profile.get("dam"),
            profile.get("dam_refno"),
            profile.get("damsire"),
            profile.get("damsire_refno"),
            profile.get("jockey"),
            profile.get("trainer"),
            profile.get("owner"),
            profile.get("breeder"),
            profile.get("best_class"),
            profile.get("equibase_refno"),
            profile.get("registry"),
            profile.get("profile_url"),
            status,
            (detail or "")[:500],
            fetched_at,
            horse_id,
        ),
    )
    conn.execute("DELETE FROM year_stats WHERE horse_id = ?", (horse_id,))
    conn.execute("DELETE FROM starts WHERE horse_id = ?", (horse_id,))
    conn.executemany(
        """
        INSERT INTO year_stats (
            horse_id, year, starts, firsts, seconds, thirds,
            highest_esf, earnings, earnings_per_start
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                horse_id,
                row.get("year"),
                row.get("starts"),
                row.get("firsts"),
                row.get("seconds"),
                row.get("thirds"),
                row.get("highest_esf"),
                row.get("earnings"),
                row.get("earnings_per_start"),
            )
            for row in profile.get("year_stats") or []
        ],
    )
    conn.executemany(
        """
        INSERT INTO starts (
            horse_id, race_date, track, track_code, country, race_number,
            race_name, grade, breed, place, esf, stakes_id, chart_url, video_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                horse_id,
                row.get("race_date"),
                row.get("track"),
                row.get("track_code"),
                row.get("country"),
                row.get("race_number"),
                row.get("race_name"),
                row.get("grade"),
                row.get("breed"),
                row.get("place"),
                row.get("esf"),
                row.get("stakes_id"),
                row.get("chart_url"),
                row.get("video_url"),
            )
            for row in profile.get("starts") or []
        ],
    )


def year_rows(conn: sqlite3.Connection, horse_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM year_stats WHERE horse_id = ? ORDER BY year",
            (horse_id,),
        ).fetchall()
    )


def start_rows(conn: sqlite3.Connection, horse_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM starts
            WHERE horse_id = ?
            ORDER BY race_date, CAST(race_number AS INTEGER), id
            """,
            (horse_id,),
        ).fetchall()
    )
