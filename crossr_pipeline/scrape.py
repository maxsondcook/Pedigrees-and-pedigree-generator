"""The long-running Equibase loop: one Chrome window, Postgres writes.

Each cycle:
  1. races-refresh, when the last finished one is over a week old: re-open
     the profile of every ok horse with a start in the last 60 days, so new
     starts and earnings land in race_seasons / race_starts.
  2. pedigrees-sales: the sire and dam of every sale lot, to a full 5-gen
     tree (see sales_parents). Ancestors opened on the way are stored as race
     records too.
  3. Nothing left: sleep, then rebuild the queue (new sales, retries).

A block page pauses the loop and sends a Mac notification every hour until
someone clears the check in the open Chrome window. Nothing here tries to get
past the check on its own.
"""

from __future__ import annotations

import fcntl
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crossr_pipeline import notify, sales_parents, state

REPO = Path(__file__).resolve().parents[1]
LOG_DIR = REPO / "logs" / "pipeline"
LOCK_PATH = LOG_DIR / "scrape.lock"

REFRESH_JOB = "races-refresh"
REFRESH_EVERY_DAYS = 7
REFRESH_WINDOW_DAYS = 60
FLUSH_EVERY_S = 30 * 60
HEARTBEAT_EVERY = 25
IDLE_SLEEP_S = 6 * 3600
MAX_ERRORS_IN_A_ROW = 8


def _run_module():
    # Imported late: run.py picks Postgres or SQLite from DATABASE_URL at import.
    from equibase_scraper import run as eb

    if eb.db is not eb.pgdb:
        raise RuntimeError("DATABASE_URL is not set; the pipeline only writes Postgres")
    return eb


def take_lock():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another scrape is running (logs/pipeline/scrape.lock).")
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


class Flusher:
    """Bump crossr_table_versions at most every FLUSH_EVERY_S, so the API
    reloads the race tables and pedigrees once per batch, not per horse."""

    TABLES = ("race_horses", "race_seasons", "race_starts", "pedigrees")

    def __init__(self, conn, pgdb):
        self.conn = conn
        self.pgdb = pgdb
        self.dirty = False
        self.last = time.monotonic()

    def maybe(self, force: bool = False) -> None:
        if not self.dirty:
            return
        if force or time.monotonic() - self.last >= FLUSH_EVERY_S:
            self.pgdb.flush_versions(self.conn, self.TABLES)
            self.dirty = False
            self.last = time.monotonic()
            print("Flushed table versions (API reloads).", flush=True)


def wait_out_block(eb, page, horse, run: state.Run) -> None:
    """Block until the page is clear. Re-notify every hour; never give up."""
    require_seen = False
    while True:
        run.heartbeat("blocked: clear the check in the Chrome window")
        notify.send("Equibase block page", "Clear the check in the Crossr Chrome window to continue.")
        if eb.wait_until_clear(page, horse=horse, require_seen_block=require_seen, timeout_s=3600):
            run.heartbeat("running")
            return
        require_seen = True
        horse = None


def _with_block_retry(eb, page, run, horse, action):
    while True:
        try:
            return action()
        except eb.Blocked:
            run.bump("blocks")
            wait_out_block(eb, page, horse, run)


# ---------------------------------------------------------------------------
# races-refresh
# ---------------------------------------------------------------------------

def refresh_due(conn) -> bool:
    last = state.last_run(conn, REFRESH_JOB, "ok")
    if last is None:
        return True
    return datetime.now(timezone.utc) - last["started_at"] >= timedelta(days=REFRESH_EVERY_DAYS)


def refresh_candidates(conn, cap: int | None) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=REFRESH_WINDOW_DAYS)).date().isoformat()
    fetched_before = (datetime.now(timezone.utc) - timedelta(days=REFRESH_EVERY_DAYS - 1)).isoformat()
    sql = """
        SELECT h.*, s.last_start FROM race_horses h
        JOIN (
            SELECT horse_id, MAX(race_date) AS last_start FROM race_starts
            WHERE race_date >= %s GROUP BY horse_id
        ) s ON s.horse_id = h.id
        WHERE h.status = 'ok' AND COALESCE(h.profile_url, '') <> ''
          AND COALESCE(h.fetched_at, '') < %s
        ORDER BY s.last_start DESC
    """
    params: tuple = (since, fetched_before)
    if cap:
        sql += " LIMIT %s"
        params += (cap,)
    return conn.execute(sql, params).fetchall()


def refresh_one(eb, page, conn, horse: dict, delay: float) -> str:
    """Re-open a known profile (one page load) and replace its record."""
    eb.polite_wait(page, delay)
    html, err = eb.goto_profile(page, horse["profile_url"])
    if eb.is_blocked(html or ""):
        raise eb.Blocked()
    if err or not html:
        return "error"
    resolved = eb.resolve_html(html, horse.get("foal_year") or "")
    if resolved["kind"] == "blocked":
        raise eb.Blocked()
    if resolved["kind"] != "profile":
        return "error"
    eb._store_resolved(conn, horse["id"], resolved)
    return "ok"


def run_refresh(eb, page, conn, delay: float, cap: int | None, flusher: Flusher) -> None:
    horses = refresh_candidates(conn, cap)
    run = state.Run(conn, REFRESH_JOB)
    print(f"races-refresh: {len(horses)} horse(s) with a start in the last {REFRESH_WINDOW_DAYS} days", flush=True)
    status = "ok"
    try:
        for index, horse in enumerate(horses, start=1):
            horse = dict(horse)
            try:
                result = _with_block_retry(eb, page, run, horse, lambda: refresh_one(eb, page, conn, horse, delay))
            except Exception as exc:  # one bad page should not stop the refresh
                print(f"refresh error {horse['pedigree_key']}: {exc}", flush=True)
                result = "error"
            run.bump(result)
            flusher.dirty = True
            print(f"[refresh {index}/{len(horses)}] {horse['pedigree_key']}: {result}", flush=True)
            if index % HEARTBEAT_EVERY == 0:
                run.heartbeat("running")
                flusher.maybe()
    except BaseException as exc:
        status = "partial"
        run.finish(status, f"stopped: {exc.__class__.__name__}")
        raise
    run.finish(status, f"{len(horses)} horses")


# ---------------------------------------------------------------------------
# pedigrees-sales
# ---------------------------------------------------------------------------

def _row_for_item(eb, conn, item: dict) -> tuple[dict | None, str]:
    db = eb.db
    rows = db.find_horses(conn, item["name_key"], item["name_key"], None)
    row, why = sales_parents.pick_row(rows, item)
    if row is not None or why == "ambiguous rows":
        return row, why

    def taken(key: str) -> bool:
        return bool(conn.execute("SELECT 1 FROM race_horses WHERE pedigree_key = %s LIMIT 1", (key,)).fetchone())

    key = sales_parents.new_row_key(item, taken)
    db.insert_batch_horse(
        conn,
        {
            "pedigree_key": key,
            "name_key": item["name_key"],
            "display_name": item["name"],
            "sire": item["sire"] if item["role"] == "dam" else "",
            "sex": "",
            "queue_batch": sales_parents.QUEUE_BATCH,
        },
    )
    hits = [hit for hit in db.find_horses(conn, key, item["name_key"], None) if hit["pedigree_key"] == key]
    return (hits[0] if hits else None), ("" if hits else "insert failed")


def process_item(eb, page, conn, book, item: dict, delay: float) -> tuple[str, str]:
    """Fetch one sale parent if needed, then fill its tree. Returns (status, detail)."""
    row, why = _row_for_item(eb, conn, item)
    if row is None:
        return ("ambiguous" if why == "ambiguous rows" else "error"), why
    horse = dict(row)
    if horse["status"] in sales_parents.DONE:
        return horse["status"], f"race_horses {horse['id']}"
    if horse["status"] != "ok":
        horse["role"] = item["role"]
        horse["yob_range"] = item["yob_range"]
        if item["role"] == "dam" and not horse.get("sire") and item["sire"]:
            horse["sire"] = item["sire"]
        eb.fetch_horse(page, conn, horse, delay)
        horse = dict(eb.db.get_by_id(conn, horse["id"]))
        if horse["status"] != "ok":
            return horse["status"], horse.get("detail") or ""
    eb.fill_horse_pedigree(page, conn, horse, book, delay)
    if eb._subject_is_complete(book, horse):
        return "complete", f"race_horses {horse['id']}"
    return "incomplete", f"race_horses {horse['id']}"


def run_pedigrees(eb, page, conn, book, delay: float, limit: int | None, flusher: Flusher,
                  role: str | None = None) -> int:
    states = state.queue_states(conn, sales_parents.JOB)
    todo, skipped = sales_parents.build_queue(conn, book.index, states, time.time(), limit, role)
    run = state.Run(conn, sales_parents.JOB)
    for reason, n in skipped.items():
        run.counts[f"skipped: {reason}"] = n
    print(f"pedigrees-sales: {len(todo)} to do; skipped {dict(skipped)}", flush=True)
    run.heartbeat("running")
    errors_in_a_row = 0
    status = "ok"
    try:
        for index, item in enumerate(todo, start=1):
            label = f"{item['role']} {item['name']}" + (f" (by {item['sire']})" if item["sire"] else "")
            print(f"[{index}/{len(todo)}] {label}", flush=True)
            saved_before = book.saved
            try:
                result, detail = _with_block_retry(
                    eb, page, run, {"display_name": item["name"], "pedigree_key": item["name_key"]},
                    lambda: process_item(eb, page, conn, book, item, delay),
                )
                errors_in_a_row = 0 if result != "error" else errors_in_a_row + 1
            except Exception as exc:
                result, detail = "error", f"{exc.__class__.__name__}: {exc}"
                errors_in_a_row += 1
                print(f"  error: {detail}", flush=True)
            state.mark_item(conn, sales_parents.JOB, item["key"], result, detail)
            run.bump(result)
            run.bump("trees saved", book.saved - saved_before)
            flusher.dirty = True
            print(f"  -> {result} {detail}", flush=True)
            if errors_in_a_row >= MAX_ERRORS_IN_A_ROW:
                raise RuntimeError(f"{errors_in_a_row} errors in a row; stopping (Chrome closed?)")
            if index % HEARTBEAT_EVERY == 0:
                run.heartbeat("running")
                flusher.maybe()
    except BaseException as exc:
        status = "failed" if isinstance(exc, RuntimeError) else "partial"
        run.finish(status, f"stopped: {exc}")
        raise
    run.finish(status, f"{len(todo)} items")
    return len(todo)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def scrape(delay: float = 3.0, limit: int | None = None, refresh_cap: int | None = None,
           once: bool = False, skip_refresh: bool = False, refresh_only: bool = False,
           role: str | None = None) -> int:
    from playwright.sync_api import sync_playwright

    eb = _run_module()
    lock = take_lock()
    conn = eb.db.connect()
    state.ensure(conn)
    flusher = Flusher(conn, eb.pgdb)
    try:
        book = None if refresh_only else eb._PedigreeBook(conn)
        with sync_playwright() as playwright:
            context, page = eb._launch_context(playwright)
            try:
                if not eb.warmup(page):
                    boot = state.Run(conn, "warmup")
                    wait_out_block(eb, page, None, boot)
                    boot.finish("ok")
                while True:
                    if not skip_refresh and (refresh_only or refresh_due(conn)):
                        run_refresh(eb, page, conn, delay, refresh_cap, flusher)
                        flusher.maybe(force=True)
                    if refresh_only:
                        break
                    done = run_pedigrees(eb, page, conn, book, delay, limit, flusher, role)
                    flusher.maybe(force=True)
                    if once or limit:
                        break
                    if done == 0:
                        print(f"Queue empty. Sleeping {IDLE_SLEEP_S // 3600} h.", flush=True)
                        page.wait_for_timeout(IDLE_SLEEP_S * 1000)
            finally:
                context.close()
    except KeyboardInterrupt:
        print("Stopped.", flush=True)
        return 130
    except Exception as exc:
        notify.send("Crossr scrape stopped", str(exc)[:200])
        raise
    finally:
        flusher.maybe(force=True)
        conn.close()
        lock.close()
    return 0
