"""Racing Post stud-fee history for every sire in breeding_seasons or sales_lots.

Per sire, two page loads in one Chrome window (plain Playwright, no stealth):
  1. https://www.racingpost.com/search-results/?keyword=<name>
     Results read "Name (CTY) - YYYY"; keep exact-name hits, then narrow by
     country suffix and a foal-year window from the sire's crops.
  2. /profile/horse/<id>/<slug>/fee-history/ : the page's __NEXT_DATA__ JSON
     has one row per year (fee, currency, private flag, country, stud).

Every row goes to racing_post_fees (raw, with standing location and country).
stud_fees only gains (Year, Stallion) pairs it does not already have: when
Racing Post disagrees with an existing fee, the existing fee wins.
"""

from __future__ import annotations

import fcntl
import json
import os
import random
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from crossr_pipeline import notify, state
from equibase_scraper.queue import clean_name

REPO = Path(__file__).resolve().parents[1]
PROFILE_DIR = REPO / "crossr_pipeline" / "chrome_profile_racingpost"
LOCK_PATH = REPO / "logs" / "pipeline" / "racing-post.lock"
BASE = "https://www.racingpost.com"
JOB = "racing-post-fees"
SOURCE = "Racing Post fee history"

DONE = {"ambiguous"}
RETRY_DAYS = {"found": 180, "no_fees": 365, "no_match": 365, "error": 3, "blocked": 0}

SCHEMA = """
CREATE TABLE IF NOT EXISTS racing_post_fees (
    stallion_key TEXT NOT NULL,
    stallion TEXT,
    rp_horse_id TEXT NOT NULL,
    rp_name TEXT,
    year INTEGER NOT NULL,
    stud_fee BIGINT,
    currency TEXT,
    is_private BOOLEAN,
    country TEXT,
    standing TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_racing_post_fees_key ON racing_post_fees (stallion_key, year);
CREATE INDEX IF NOT EXISTS idx_racing_post_fees_horse ON racing_post_fees (rp_horse_id);
"""

RESULT_RE = re.compile(r"^(?P<name>.+?)\s*(?:\((?P<cty>[A-Z]{2,4})\))?\s*-\s*(?P<year>\d{4})\s*$")
SUFFIX_RE = re.compile(r"\(([A-Za-z]{2,4})\)")


# ---------------------------------------------------------------------------
# pure helpers (tested)
# ---------------------------------------------------------------------------

def name_suffix(name: str) -> str:
    match = SUFFIX_RE.search(name or "")
    return match.group(1).upper() if match else ""


def parse_result(text: str) -> dict | None:
    """'Smarty Jones (USA) - 2001' -> name, country, foal year."""
    match = RESULT_RE.match(" ".join((text or "").split()))
    if not match:
        return None
    return {
        "name": match.group("name").strip(),
        "country": (match.group("cty") or "").upper(),
        "year": int(match.group("year")),
    }


def yob_window(first_year: int | None, last_year: int | None) -> tuple[int, int] | None:
    """A sire covering mares in ``first_year`` was at least 3; at most 30 by ``last_year``."""
    if not first_year or not last_year:
        return None
    low, high = last_year - 30, first_year - 3
    return (low, high) if low <= high else None


def pick_candidates(results: list[dict], sire: dict) -> list[dict]:
    """Exact-name hits for the sire, narrowed by country and foal-year window.

    Each narrowing step applies only when it leaves at least one hit.
    """
    key = sire["key"]
    hits = [r for r in results if clean_name(r["name"]) == key]

    def keep(rows, test):
        kept = [row for row in rows if test(row)]
        return kept or rows

    suffix = sire.get("suffix") or ""
    if suffix:
        hits = keep(hits, lambda r: r["country"] == suffix)
    else:
        hits = keep(hits, lambda r: r["country"] in ("USA", ""))
    window = sire.get("yob_range")
    if window:
        hits = keep(hits, lambda r: window[0] <= r["year"] <= window[1])
    return hits


def fee_rows(payload: dict) -> list[dict]:
    """Fee-history rows from a fee-history page's __NEXT_DATA__, duplicates removed."""
    data = (
        payload.get("props", {}).get("pageProps", {}).get("initialState", {})
        .get("horseProfile", {}).get("feeHistory", {}).get("data")
    ) or []
    seen = set()
    out = []
    for row in data:
        year = row.get("nominationYear")
        if not year:
            continue
        fee = row.get("studFee")
        item = {
            "year": int(year),
            "stud_fee": int(fee) if isinstance(fee, (int, float)) and fee > 0 else None,
            "currency": (row.get("currencyCode") or "").upper() or None,
            "is_private": bool(row.get("isPrivate")),
            "country": (row.get("countryDesc") or "").strip() or None,
            "standing": (row.get("studName") or "").strip() or None,
        }
        ident = tuple(item.values())
        if ident in seen:
            continue
        seen.add(ident)
        out.append(item)
    return out


def is_usa(row: dict) -> bool:
    country = (row.get("country") or "").upper().replace(".", "")
    return country in ("USA", "US") or row.get("currency") == "USD"


def format_fee(row: dict) -> str:
    if row["is_private"]:
        return "Private"
    if row["stud_fee"] is None:
        return "N/A"
    if row["currency"] in (None, "USD"):
        return f"${row['stud_fee']:,}"
    return f"{row['currency']} {row['stud_fee']:,}"


def stud_fee_additions(sire: dict, rp_id: str, rows: list[dict], have_years: set[int]) -> list[dict]:
    """stud_fees rows for years we have no fee for; one row per year, US row first."""
    by_year: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_year[row["year"]].append(row)
    out = []
    for year, options in sorted(by_year.items()):
        if year in have_years:
            continue
        options.sort(key=lambda r: (not is_usa(r), r["is_private"], r["stud_fee"] is None))
        best = options[0]
        notes = "; ".join(x for x in (f"Racing Post {rp_id}", best["country"], best["currency"]) if x)
        out.append({
            "Year": str(year),
            "Stallion": sire["name"],
            "Stud Fee": format_fee(best),
            "Farm": best["standing"] or "",
            "Source List": SOURCE,
            "Notes": notes,
        })
    return out


# ---------------------------------------------------------------------------
# database
# ---------------------------------------------------------------------------

def ensure(conn) -> None:
    state.ensure(conn)
    conn.execute(SCHEMA)


def load_sires(conn) -> list[dict]:
    """Every sire in breeding_seasons or sales_lots, newest activity first."""
    agg: dict[str, dict] = {}

    def add(name: str, year, first_crop_year):
        name = (name or "").strip()
        key = clean_name(name)
        if not key or not str(year or "").isdigit():
            return
        year = int(year)
        entry = agg.setdefault(key, {"key": key, "name": name, "latest": year, "first": None, "rows": 0, "suffix": ""})
        entry["latest"] = max(entry["latest"], year)
        entry["rows"] += 1
        if first_crop_year:
            entry["first"] = min(entry["first"] or first_crop_year, first_crop_year)
        if not entry["suffix"] and name_suffix(name):
            entry["suffix"] = name_suffix(name)
            entry["name"] = name

    for row in conn.execute("SELECT stallion, breeding_year FROM breeding_seasons"):
        year = row["breeding_year"]
        add(row["stallion"], year, int(year) if str(year or "").isdigit() else None)
    for row in conn.execute(
        "SELECT sire, catalog_year, birth_year FROM sales_lots WHERE COALESCE(sire, '') <> ''"
    ):
        birth = row["birth_year"]
        # A foal born in Y was conceived in Y-1.
        add(row["sire"], row["catalog_year"], int(birth) - 1 if str(birth or "").isdigit() else None)
    sires = list(agg.values())
    for sire in sires:
        sire["yob_range"] = yob_window(sire["first"], sire["latest"])
    sires.sort(key=lambda s: (-s["latest"], -s["rows"], s["key"]))
    return sires


def existing_fee_years(conn) -> dict[str, set[int]]:
    have: dict[str, set[int]] = defaultdict(set)
    for row in conn.execute('SELECT "Year" AS year, "Stallion" AS stallion FROM stud_fees'):
        if str(row["year"] or "").isdigit():
            have[clean_name(row["stallion"] or "")].add(int(row["year"]))
    return have


def due(sire: dict, states: dict, now_ts: float) -> bool:
    found = states.get(sire["key"])
    if not found:
        return True
    if found["status"] in DONE:
        return False
    days = RETRY_DAYS.get(found["status"], 1)
    return now_ts - found["last_attempt"].timestamp() >= days * 86400


def store(conn, sire: dict, rp: dict, rows: list[dict], additions: list[dict]) -> None:
    with conn.transaction():
        conn.execute("DELETE FROM racing_post_fees WHERE rp_horse_id = %s", (rp["id"],))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO racing_post_fees (stallion_key, stallion, rp_horse_id, rp_name, year, stud_fee, "
                "currency, is_private, country, standing) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (sire["key"], sire["name"], rp["id"], rp["label"], r["year"], r["stud_fee"], r["currency"],
                     r["is_private"], r["country"], r["standing"])
                    for r in rows
                ],
            )
            if additions:
                cur.executemany(
                    'INSERT INTO stud_fees ("Year", "Stallion", "Stud Fee", "Farm", "Source List", "Notes") '
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [(a["Year"], a["Stallion"], a["Stud Fee"], a["Farm"] or None, a["Source List"], a["Notes"])
                     for a in additions],
                )


# ---------------------------------------------------------------------------
# browser
# ---------------------------------------------------------------------------

def _blocked(response, page) -> bool:
    if response is not None and response.status in (403, 429, 503):
        return True
    try:
        title = (page.title() or "").lower()
    except Exception:
        return False
    return any(text in title for text in ("access denied", "just a moment", "attention required", "pardon our"))


def _wait_out_block(page, url: str, run: state.Run):
    """Notify, leave the window for a person to clear, recheck every 15 min."""
    while True:
        run.bump("blocks")
        run.heartbeat("blocked: clear the check in the Racing Post Chrome window")
        notify.send("Racing Post block page", "Clear the check in the Racing Post Chrome window to continue.")
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            page.wait_for_timeout(15 * 60 * 1000)
            response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if not _blocked(response, page):
                run.heartbeat("running")
                return response


def _goto(page, url: str, delay: float, run: state.Run):
    page.wait_for_timeout(int((delay + random.uniform(0.3, 1.2)) * 1000))
    response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
    if _blocked(response, page):
        response = _wait_out_block(page, url, run)
    return response


def search(page, name: str, delay: float, run: state.Run) -> list[dict]:
    bare = SUFFIX_RE.sub("", name).strip()
    _goto(page, f"{BASE}/search-results/?keyword={quote(bare.lower())}", delay, run)
    try:
        page.wait_for_selector('a[href*="/profile/horse/"]', timeout=8000)
    except Exception:
        return []
    out = []
    for link in page.locator('a[href*="/profile/horse/"]').all():
        href = link.get_attribute("href") or ""
        match = re.search(r"/profile/horse/(\d+)/([a-z0-9-]+)", href)
        if not match:
            continue
        parsed = parse_result(link.inner_text())
        if not parsed:
            continue
        parsed.update({"id": match.group(1), "slug": match.group(2), "label": " ".join(link.inner_text().split())})
        if all(o["id"] != parsed["id"] for o in out):
            out.append(parsed)
    return out


def fee_history(page, rp: dict, delay: float, run: state.Run) -> list[dict]:
    _goto(page, f"{BASE}/profile/horse/{rp['id']}/{rp['slug']}/fee-history/", delay, run)
    html = page.content()
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        raise RuntimeError("fee-history page has no __NEXT_DATA__")
    return fee_rows(json.loads(match.group(1)))


def process(page, conn, sire: dict, have_years: set[int], delay: float, run: state.Run) -> tuple[str, str]:
    results = search(page, sire["name"], delay, run)
    hits = pick_candidates(results, sire)
    if not hits:
        return "no_match", f"{len(results)} search results"
    if len(hits) > 1:
        # Same name, country and window: keep the one(s) that stood at stud.
        with_fees = []
        for hit in hits[:3]:
            rows = fee_history(page, hit, delay, run)
            if rows:
                with_fees.append((hit, rows))
        if len(with_fees) != 1:
            return "ambiguous", ", ".join(h["label"] for h in hits[:5])
        rp, rows = with_fees[0]
    else:
        rp = hits[0]
        rows = fee_history(page, rp, delay, run)
    if not rows:
        store(conn, sire, rp, [], [])
        return "no_fees", rp["label"]
    additions = stud_fee_additions(sire, rp["id"], rows, have_years)
    store(conn, sire, rp, rows, additions)
    run.bump("fee years read", len({r["year"] for r in rows}))
    run.bump("stud_fees rows added", len(additions))
    return "found", f"{rp['label']}: {len(rows)} rows, {len(additions)} new years"


def run_racing_post(conn, delay: float = 3.0, limit: int | None = None) -> int:
    from playwright.sync_api import sync_playwright

    from equibase_scraper import pgdb

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK_PATH.open("a+")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another racing-post run is going (logs/pipeline/racing-post.lock).")
    ensure(conn)
    states = state.queue_states(conn, JOB)
    have = existing_fee_years(conn)
    now = time.time()
    todo = [s for s in load_sires(conn) if due(s, states, now)]
    if limit:
        todo = todo[:limit]
    if not todo:
        lock.close()
        return 0
    run = state.Run(conn, JOB)
    print(f"racing-post: {len(todo)} sire(s) to look up", flush=True)
    status = "ok"
    last_flush = time.monotonic()
    dirty = False
    try:
        with sync_playwright() as playwright:
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR), channel="chrome", headless=False,
                locale="en-US", viewport={"width": 1280, "height": 900},
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(60000)
            try:
                errors_in_a_row = 0
                for index, sire in enumerate(todo, start=1):
                    try:
                        result, detail = process(page, conn, sire, have.get(sire["key"], set()), delay, run)
                        errors_in_a_row = 0
                    except Exception as exc:
                        result, detail = "error", f"{exc.__class__.__name__}: {exc}"[:300]
                        errors_in_a_row += 1
                    state.mark_item(conn, JOB, sire["key"], result, detail)
                    run.bump(result)
                    dirty = dirty or result == "found"
                    print(f"[{index}/{len(todo)}] {sire['name']}: {result} {detail}", flush=True)
                    if errors_in_a_row >= 8:
                        raise RuntimeError("8 errors in a row; stopping (Chrome closed?)")
                    if index % 25 == 0:
                        run.heartbeat("running")
                    if dirty and time.monotonic() - last_flush > 1800:
                        pgdb.flush_versions(conn, ("stud_fees",))
                        last_flush, dirty = time.monotonic(), False
            finally:
                context.close()
    except BaseException as exc:
        status = "failed" if isinstance(exc, RuntimeError) else "partial"
        run.finish(status, f"stopped: {exc}")
        if status == "failed":
            notify.send("Racing Post scrape stopped", str(exc)[:200])
        raise
    finally:
        if dirty:
            pgdb.flush_versions(conn, ("stud_fees",))
        lock.close()
    run.finish(status, f"{len(todo)} sires")
    return len(todo)
