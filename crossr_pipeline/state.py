"""Pipeline bookkeeping in Postgres: run log, per-item queue state, loaded files.

    crossr_pipeline_runs   one row per job run (status, counts, heartbeat)
    crossr_pipeline_queue  one row per queue item a job has tried
    crossr_pipeline_files  sha256 of each sales CSV already loaded
"""

from __future__ import annotations

import json
import socket

SCHEMA = """
CREATE TABLE IF NOT EXISTS crossr_pipeline_runs (
    id BIGSERIAL PRIMARY KEY,
    job TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    detail TEXT,
    host TEXT
);
CREATE INDEX IF NOT EXISTS idx_crossr_pipeline_runs_job ON crossr_pipeline_runs (job, started_at DESC);

CREATE TABLE IF NOT EXISTS crossr_pipeline_queue (
    job TEXT NOT NULL,
    item_key TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt TIMESTAMPTZ NOT NULL DEFAULT now(),
    detail TEXT,
    PRIMARY KEY (job, item_key)
);

CREATE TABLE IF NOT EXISTS crossr_pipeline_files (
    path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    row_count INTEGER,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Run statuses: running, ok, partial (stopped early: limit, block timeout,
# Ctrl-C), blocked, failed. A 'running' row whose heartbeat is old crashed.


def ensure(conn) -> None:
    conn.execute(SCHEMA)


class Run:
    """One crossr_pipeline_runs row. ``bump`` adds to counts in memory;
    ``heartbeat`` writes them; ``finish`` closes the row."""

    def __init__(self, conn, job: str):
        self.conn = conn
        self.job = job
        self.counts: dict[str, int] = {}
        row = conn.execute(
            "INSERT INTO crossr_pipeline_runs (job, host) VALUES (%s, %s) RETURNING id",
            (job, socket.gethostname()),
        ).fetchone()
        self.id = row["id"] if isinstance(row, dict) else row[0]

    def bump(self, key: str, by: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + by

    def heartbeat(self, detail: str | None = None) -> None:
        self.conn.execute(
            "UPDATE crossr_pipeline_runs SET heartbeat_at = now(), counts = %s::jsonb, "
            "detail = COALESCE(%s, detail) WHERE id = %s",
            (json.dumps(self.counts), detail, self.id),
        )

    def finish(self, status: str, detail: str | None = None) -> None:
        self.conn.execute(
            "UPDATE crossr_pipeline_runs SET status = %s, finished_at = now(), heartbeat_at = now(), "
            "counts = %s::jsonb, detail = COALESCE(%s, detail) WHERE id = %s",
            (status, json.dumps(self.counts), detail, self.id),
        )


def last_run(conn, job: str, status: str | None = None):
    if status:
        return conn.execute(
            "SELECT * FROM crossr_pipeline_runs WHERE job = %s AND status = %s "
            "ORDER BY started_at DESC LIMIT 1",
            (job, status),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM crossr_pipeline_runs WHERE job = %s ORDER BY started_at DESC LIMIT 1",
        (job,),
    ).fetchone()


def recent_runs(conn, limit: int = 15) -> list:
    return conn.execute(
        "SELECT id, job, status, started_at, heartbeat_at, finished_at, counts, detail "
        "FROM crossr_pipeline_runs ORDER BY started_at DESC LIMIT %s",
        (limit,),
    ).fetchall()


def queue_states(conn, job: str) -> dict[str, dict]:
    return {
        row["item_key"]: row
        for row in conn.execute(
            "SELECT item_key, status, attempts, last_attempt FROM crossr_pipeline_queue WHERE job = %s",
            (job,),
        )
    }


def mark_item(conn, job: str, item_key: str, status: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO crossr_pipeline_queue (job, item_key, status, attempts, last_attempt, detail) "
        "VALUES (%s, %s, %s, 1, now(), %s) ON CONFLICT (job, item_key) DO UPDATE SET "
        "status = EXCLUDED.status, attempts = crossr_pipeline_queue.attempts + 1, "
        "last_attempt = now(), detail = EXCLUDED.detail",
        (job, item_key, status, (detail or "")[:500]),
    )


def queue_summary(conn) -> list:
    return conn.execute(
        "SELECT job, status, COUNT(*) AS n FROM crossr_pipeline_queue GROUP BY job, status ORDER BY job, n DESC"
    ).fetchall()
