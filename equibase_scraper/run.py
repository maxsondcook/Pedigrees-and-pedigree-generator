"""Equibase race records via headed Chrome.

    python3 -m equibase_scraper.run --enqueue
    python3 -m equibase_scraper.run --horse "American Pharoah" --year 2012
    python3 -m equibase_scraper.run --resume --batch catalog-2026-10-15 --delay 3
    python3 -m equibase_scraper.run --show "American Pharoah" --year 2012
    python3 -m equibase_scraper.run --fill-pedigrees --delay 1

--fill-pedigrees walks status=ok horses whose 5-generation pedigree is still
incomplete. Ancestors opened on that walk are stored as race records too.

Equibase sits behind Imperva. Curl and headless browsers get a block page.
This uses the same headed Chrome setup as the BloodHorse sire-list fetcher:
Playwright, channel="chrome", a persistent profile, locale en-US.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pq_scraper.dbio import load_pedigree_map, save_pedigree_map

from equibase_scraper import db as sqlite_db, pgdb, queue
from equibase_scraper.parse import (
    is_blocked,
    is_empty_search,
    is_profile,
    is_search_list,
    page_is_clear,
    profile_url_for,
    resolve_html,
)
from equibase_scraper.pedigree_fill import (
    build_ancestor_index,
    fill_profile_pedigree,
    stored_pedigree_complete,
)

# DATABASE_URL set: race records and pedigrees go straight to Postgres.
db = pgdb if pgdb.enabled() else sqlite_db

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "equibase_scraper" / "cache"
PROFILE_DIR = REPO / "equibase_scraper" / "chrome_profile"
SEARCH_URL = "https://www.equibase.com/profiles/Results.cfm?type=Horse&SAP=TP"
HOME_URL = "https://www.equibase.com/"

BLOCK_MESSAGE = """
Equibase showed a block page (Pardon Our Interruption / Access Denied).
Complete that check in the open Chrome window. This run keeps Chrome open and continues when the page stays clear.
""".strip()

BLOCK_TIMEOUT_S = 600
CLEAR_GAP_MS = 4000


class Blocked(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def cache_slug(pedigree_key: str) -> str:
    import re

    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", pedigree_key).strip("_")
    return (slug or "horse")[:120]


def _read_cache(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text or is_blocked(text):
        return None
    # Stale partial/challenge HTML is not a usable Equibase response. Drop it
    # so resume refetches instead of re-marking the horse as unrecognized.
    if not (is_profile(text) or is_search_list(text) or is_empty_search(text)):
        return None


def _write_cache(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def polite_wait(page, delay: float) -> None:
    pause = max(0.0, delay) + random.uniform(0.25, 0.85)
    page.wait_for_timeout(int(pause * 1000))


def confirmed_clear(previous_clear: bool, current_clear: bool) -> bool:
    """True only after two checks in a row both saw a normal Equibase page."""
    return previous_clear and current_clear


def interruption_cleared(
    previous_clear: bool,
    current_clear: bool,
    seen_block: bool,
    require_seen_block: bool,
) -> bool:
    """Two clear checks, and a real block page first when that is required."""
    if not confirmed_clear(previous_clear, current_clear):
        return False
    if require_seen_block and not seen_block:
        return False
    return True


def _page_shows_block(page) -> bool:
    try:
        return is_blocked(page.content())
    except Exception:
        return False


def _surface_blocked_request(page, horse) -> None:
    """Open the blocked search as the document so the check is on screen.

    A fetch() block stays in the response body and never loads the interstitial.
    A form POST navigates Chrome onto that page without forging a token.
    """
    name = horse["display_name"] or horse["pedigree_key"]
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=60000):
            page.evaluate(
                """({url, name}) => {
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = url;
                    for (const [key, value] of [['horse_name', name], ['searchType', 'H']]) {
                        const input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = key;
                        input.value = value;
                        form.appendChild(input);
                    }
                    document.body.appendChild(form);
                    form.submit();
                }""",
                {"url": SEARCH_URL, "name": name},
            )
    except Exception as exc:
        print(f"Could not open the block page in Chrome: {exc}", flush=True)
        try:
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as inner:
            print(f"Could not open the block page in Chrome: {inner}", flush=True)


def wait_until_clear(page, horse=None, require_seen_block: bool = False, timeout_s: float = BLOCK_TIMEOUT_S) -> bool:
    """Poll the open page until it stays clear, or the timeout expires.

    Leaves the Playwright context open. A single non-block frame does not count.
    """
    print(BLOCK_MESSAGE, flush=True)
    if horse is not None and not _page_shows_block(page):
        _surface_blocked_request(page, horse)
    seen_block = _page_shows_block(page)
    previous_clear = False
    deadline = time.monotonic() + timeout_s
    while True:
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            print("Still blocked after 10 minutes. Exiting.", flush=True)
            return False
        page.wait_for_timeout(min(CLEAR_GAP_MS, remaining_ms))
        try:
            html = page.content()
        except Exception:
            previous_clear = False
            continue
        if is_blocked(html):
            seen_block = True
            previous_clear = False
            continue
        current_clear = page_is_clear(html)
        if interruption_cleared(previous_clear, current_clear, seen_block, require_seen_block):
            print("Interruption cleared. Continuing this run.", flush=True)
            return True
        previous_clear = current_clear


def post_search(page, name: str) -> tuple[str, str | None]:
    try:
        result = page.evaluate(
            """async ({url, name}) => {
                const body = new URLSearchParams();
                body.set('horse_name', name);
                body.set('searchType', 'H');
                const resp = await fetch(url, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'Accept': 'text/html'
                    },
                    body: body.toString()
                });
                const text = await resp.text();
                return {status: resp.status, text};
            }""",
            {"url": SEARCH_URL, "name": name},
        )
    except Exception as exc:
        return "", f"error:{exc}"
    status = int(result.get("status") or 0)
    text = result.get("text") or ""
    if status >= 400 and not is_profile(text) and not is_blocked(text):
        return text, f"http {status}"
    return text, None


def goto_profile(page, url: str) -> tuple[str, str | None]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector("#horseProfileInfo, h2.horse-name-header", timeout=20000)
        except Exception:
            pass
        return page.content(), None
    except Exception as exc:
        return "", f"error:{exc}"


def _store_resolved(conn, horse_id: int, resolved: dict) -> str:
    kind = resolved["kind"]
    fetched_at = _now()
    if kind == "profile":
        profile = resolved["profile"]
        db.save_profile(conn, horse_id, profile, "ok", "", fetched_at)
        conn.commit()
        starts = len(profile.get("starts") or [])
        return f"ok starts={starts}"
    if kind in {"not_found", "ambiguous", "year_mismatch"}:
        db.mark_status(conn, horse_id, kind, resolved.get("detail") or "", fetched_at)
        conn.commit()
        return f"{kind} {resolved.get('detail') or ''}".strip()
    db.mark_status(conn, horse_id, "error", resolved.get("detail") or kind, fetched_at)
    conn.commit()
    return f"error {resolved.get('detail') or kind}"


def _profile_from_row(row) -> dict:
    return {
        "display_name": row["display_name"] or row["pedigree_key"],
        "foal_year": row["foal_year"] or "",
        "sire": row["sire"],
        "sire_refno": row["sire_refno"],
        "dam": row["dam"],
        "dam_refno": row["dam_refno"],
        "damsire": row["damsire"],
        "damsire_refno": row["damsire_refno"],
        "equibase_refno": row["equibase_refno"],
        "registry": row["registry"] or "T",
    }


def _lookup_ancestor_row(conn, name: str, year: str, refno: str):
    """Prefer the refno row, then a single name+year row. Do not guess among years."""
    if refno:
        row = db.find_by_equibase_refno(conn, refno)
        if row is not None:
            return row
    name_key = queue.clean_name(name)
    if not name_key:
        return None
    hits = db.find_horses(conn, name, name_key, year or None)
    if year:
        hits = [hit for hit in hits if (hit["foal_year"] or "") == str(year)]
    if len(hits) == 1:
        return hits[0]
    return None


def _insert_ancestor_row(conn, profile: dict, fallback_name: str, fallback_year: str):
    name = (profile.get("display_name") or fallback_name or "").strip()
    year = str(profile.get("foal_year") or fallback_year or "").strip()
    name_key = queue.clean_name(name)
    if not name_key:
        return None
    pedigree_key = f"{name_key} ({year})" if year else name_key
    db.upsert_pending(
        conn,
        {
            "pedigree_key": pedigree_key,
            "name_key": name_key,
            "foal_year": year,
            "display_name": name,
        },
    )
    conn.commit()
    hits = db.find_horses(conn, pedigree_key, name_key, year or None)
    return hits[0] if hits else None


def _row_for_ancestor(conn, existing, profile: dict, fallback_name: str, fallback_year: str):
    if existing is not None and existing["status"] != "ok":
        return existing
    name = profile.get("display_name") or fallback_name or ""
    year = str(profile.get("foal_year") or fallback_year or "").strip()
    found = _lookup_ancestor_row(conn, name, year, str(profile.get("equibase_refno") or ""))
    if found is not None:
        return found
    if existing is not None:
        return existing
    return _insert_ancestor_row(conn, profile, fallback_name, fallback_year)


def save_ancestor_page(
    conn,
    html: str,
    *,
    existing,
    fallback_name: str,
    fallback_year: str,
) -> dict | None:
    """Parse a profile page and store the race record with save_profile.

    status=ok is reused and not written again. A pending catalog row is updated
    in place so a later catalog pass skips that horse.
    """
    year = str(fallback_year or "").strip()
    resolved = resolve_html(html, year)
    if resolved["kind"] == "blocked":
        raise Blocked()
    if resolved["kind"] != "profile":
        return None
    profile = resolved["profile"]
    if not profile.get("display_name") and fallback_name:
        profile = dict(profile)
        profile["display_name"] = fallback_name
    target = _row_for_ancestor(conn, existing, profile, fallback_name, year)
    if target is None:
        return profile
    if target["status"] == "ok":
        return _profile_from_row(target)
    summary = _store_resolved(conn, target["id"], resolved)
    label_year = profile.get("foal_year") or year
    label_name = profile.get("display_name") or fallback_name
    label = f"{label_name} ({label_year})" if label_year else label_name
    print(f"pedigree {label}: {summary}", flush=True)
    return profile


def _load_ancestor_html(page, delay: float, name: str, year: str, refno: str, registry: str):
    if refno:
        url = profile_url_for(refno, registry or "T")
        if not url:
            return "", "missing profile url"
        polite_wait(page, delay)
        return goto_profile(page, url)
    if not name:
        return "", "missing name"
    polite_wait(page, delay)
    html, err = post_search(page, name)
    if is_blocked(html or ""):
        raise Blocked()
    if err and not html:
        return "", err
    resolved = resolve_html(html or "", year)
    if resolved["kind"] == "blocked":
        raise Blocked()
    if resolved["kind"] == "profile":
        return html, None
    if resolved["kind"] != "candidate":
        return "", resolved.get("detail") or resolved["kind"]
    polite_wait(page, delay)
    return goto_profile(page, resolved["candidate"]["url"])


def fetch_ancestor_profile(page, conn, delay: float, query) -> dict | None:
    """Race record for one ancestor. Reuse status=ok; otherwise fetch and save_profile."""
    refno = (query.refno or "").strip()
    registry = (query.registry or "T").strip() or "T"
    name = query.name or ""
    year = (query.year or "").strip()
    row = _lookup_ancestor_row(conn, name, year, refno)
    if row is not None and row["status"] == "ok":
        return _profile_from_row(row)
    html, err = _load_ancestor_html(page, delay, name, year, refno, registry)
    if is_blocked(html or ""):
        raise Blocked()
    if not html:
        if err:
            print(f"pedigree fetch failed {name or refno}: {err}", flush=True)
        return None
    return save_ancestor_page(
        conn,
        html,
        existing=row,
        fallback_name=name,
        fallback_year=year,
    )


class _PedigreeBook:
    """Pedigree map and ancestor index. With Postgres, trees go straight to the
    pedigrees table (no pedigrees_database.py rewrite); ``saved`` counts them."""

    def __init__(self, conn=None):
        print("Loading pedigree map for 5-generation fill...", flush=True)
        self.conn = conn if db is pgdb else None
        if self.conn is not None:
            self.pedigree_map = pgdb.load_pedigree_map(self.conn)
        else:
            self.pedigree_map = load_pedigree_map()
        self.index = build_ancestor_index(self.pedigree_map)
        self.failed_refnos: set[str] = set()
        self.failed_names: set[tuple[str, str]] = set()
        self.saved = 0
        print(f"Pedigree map: {len(self.pedigree_map)} horses", flush=True)

    def save(self, keys: set[str]) -> None:
        if not keys:
            return
        if self.conn is not None:
            items = {key: self.pedigree_map[key] for key in keys if key in self.pedigree_map}
            self.saved += pgdb.upsert_pedigrees(self.conn, items)
            return
        save_pedigree_map(self.pedigree_map, overwrite_keys=set(keys))


def _subject_is_complete(book: _PedigreeBook, row) -> bool:
    year = row["foal_year"] or queue.foaling_year(row["pedigree_key"] or "")
    name = row["display_name"] or ""
    key = row["pedigree_key"] or ""
    if name and stored_pedigree_complete(book.index, name, year):
        return True
    return bool(key) and stored_pedigree_complete(book.index, key, year)


def fill_horse_pedigree(page, conn, row, book: _PedigreeBook, delay: float) -> None:
    label_year = row["foal_year"] or ""
    label_name = row["display_name"] or row["pedigree_key"]
    label = f"{label_name} ({label_year})" if label_year else label_name
    if _subject_is_complete(book, row):
        print(f"pedigree graft/skip {label}: already complete", flush=True)
        return

    print(f"pedigree-fill {label}", flush=True)

    def fetch(query):
        return fetch_ancestor_profile(page, conn, delay, query)

    result = fill_profile_pedigree(
        _profile_from_row(row),
        book.pedigree_map,
        fetch,
        index=book.index,
        failed_refnos=book.failed_refnos,
        failed_names=book.failed_names,
    )
    book.save(result["updated_keys"])
    print(
        f"pedigree-fill {label}: fetches={result['fetches']} keys={len(result['updated_keys'])}",
        flush=True,
    )


def _fill_loaded_horse(page, conn, horse, book: _PedigreeBook, delay: float) -> None:
    try:
        fill_horse_pedigree(page, conn, horse, book, delay)
    except Blocked:
        raise
    except Exception as exc:
        label = horse.get("pedigree_key") or horse.get("display_name")
        print(f"pedigree error {label}: {exc}", flush=True)


def fetch_horse(page, conn, horse, delay: float) -> str:
    """Fetch one horse. Raises Blocked so the caller can wait, then retry it."""
    horse_id = horse["id"]
    year = horse["foal_year"] or ""
    slug = cache_slug(horse["pedigree_key"])
    profile_path = CACHE / "profile" / f"{slug}.html"
    search_path = CACHE / "search" / f"{slug}.html"
    label = f"{horse['display_name']} ({year})" if year else horse["display_name"]

    expected_sire = horse["sire"] if "sire" in horse.keys() else None
    expected_dam = horse["dam"] if "dam" in horse.keys() else None
    yob_range = horse.get("yob_range")
    role = horse.get("role")
    refresh = bool(horse.get("refresh"))
    cached = None if refresh else _read_cache(profile_path)
    if cached and is_profile(cached):
        resolved = resolve_html(cached, year, expected_sire, expected_dam, yob_range, role)
        if resolved["kind"] in {"profile", "year_mismatch"}:
            summary = _store_resolved(conn, horse_id, resolved)
            print(f"{label}: {summary} cache", flush=True)
            return resolved["kind"]

    polite_wait(page, delay)
    search_html = None if refresh else _read_cache(search_path)
    search_note = "cache"
    if search_html is None:
        search_html, err = post_search(page, horse["display_name"] or horse["pedigree_key"])
        search_note = "fetch"
        if err and not search_html:
            db.mark_status(conn, horse_id, "error", err, _now())
            conn.commit()
            print(f"{label}: error {err}", flush=True)
            return "error"
        if search_html:
            _write_cache(search_path, search_html)
    if is_blocked(search_html or ""):
        db.mark_status(conn, horse_id, "blocked", "search blocked", _now())
        conn.commit()
        print(f"{label}: blocked", flush=True)
        raise Blocked()

    resolved = resolve_html(search_html or "", year, expected_sire, expected_dam, yob_range, role)
    if resolved["kind"] == "blocked":
        db.mark_status(conn, horse_id, "blocked", resolved.get("detail") or "", _now())
        conn.commit()
        raise Blocked()
    if resolved["kind"] == "profile":
        _write_cache(profile_path, search_html)
        summary = _store_resolved(conn, horse_id, resolved)
        print(f"{label}: {summary} {search_note}", flush=True)
        return "ok"
    if resolved["kind"] != "candidate":
        summary = _store_resolved(conn, horse_id, resolved)
        print(f"{label}: {summary}", flush=True)
        return resolved["kind"]

    candidate = resolved["candidate"]
    print(
        f"{label}: match refno={candidate.get('refno')} registry={candidate.get('registry')}",
        flush=True,
    )
    polite_wait(page, delay)
    profile_html, err = goto_profile(page, candidate["url"])
    if is_blocked(profile_html):
        if profile_html:
            _write_cache(profile_path, profile_html)
        db.mark_status(conn, horse_id, "blocked", "profile blocked", _now())
        conn.commit()
        print(f"{label}: blocked", flush=True)
        raise Blocked()
    if err or not profile_html:
        db.mark_status(conn, horse_id, "error", err or "empty profile", _now())
        conn.commit()
        print(f"{label}: error {err or 'empty profile'}", flush=True)
        return "error"
    _write_cache(profile_path, profile_html)
    resolved = resolve_html(profile_html, year, expected_sire, expected_dam, yob_range, role)
    if resolved["kind"] == "blocked":
        db.mark_status(conn, horse_id, "blocked", "profile blocked", _now())
        conn.commit()
        raise Blocked()
    summary = _store_resolved(conn, horse_id, resolved)
    print(f"{label}: {summary}", flush=True)
    return resolved["kind"]


def _launch_context(playwright):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        locale="en-US",
        viewport={"width": 1440, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(60000)
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return context, page


def warmup(page) -> bool:
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    return not is_blocked(page.content())


def run_fetch(conn, horses, delay: float, pedigree_fill: bool = True) -> int:
    from playwright.sync_api import sync_playwright

    if not horses:
        print("Nothing to fetch.", flush=True)
        return 0
    book = _PedigreeBook(conn) if pedigree_fill else None
    if not pedigree_fill:
        print("Pedigree fill disabled for this run.", flush=True)
    print(f"Fetching {len(horses)} horse(s), delay={delay}s", flush=True)
    with sync_playwright() as playwright:
        context, page = _launch_context(playwright)
        try:
            if not warmup(page):
                if not wait_until_clear(page, require_seen_block=True):
                    return 2
            total = len(horses)
            for index, horse in enumerate(horses, start=1):
                horse = dict(horse)
                if horse["status"] == "ok":
                    print(f"[{index}/{total}] skip {horse['pedigree_key']} (ok)", flush=True)
                    continue
                print(f"[{index}/{total}] {horse['pedigree_key']}", flush=True)
                require_seen_block = False
                while True:
                    try:
                        if horse["status"] != "ok":
                            fetch_horse(page, conn, horse, delay)
                            fresh = db.get_by_id(conn, horse["id"])
                            if fresh is not None:
                                horse = dict(fresh)
                        if horse["status"] == "ok" and book is not None:
                            _fill_loaded_horse(page, conn, horse, book, delay)
                        break
                    except Blocked:
                        if not wait_until_clear(
                            page,
                            horse=horse,
                            require_seen_block=require_seen_block,
                        ):
                            return 2
                        require_seen_block = True
                        fresh = db.get_by_id(conn, horse["id"])
                        if fresh is not None:
                            horse = dict(fresh)
                        print(f"[{index}/{total}] retry {horse['pedigree_key']}", flush=True)
        finally:
            context.close()
    print("Fetch finished.", flush=True)
    return 0


def run_fill_pedigrees(conn, delay: float) -> int:
    """Walk status=ok horses whose 5-generation pedigree is not in the book yet."""
    from playwright.sync_api import sync_playwright

    book = _PedigreeBook(conn)
    horses = [dict(row) for row in db.ok_horses(conn) if not _subject_is_complete(book, row)]
    print(f"Pedigree fill: {len(horses)} ok horse(s) still incomplete.", flush=True)
    if not horses:
        return 0
    with sync_playwright() as playwright:
        context, page = _launch_context(playwright)
        try:
            if not warmup(page):
                if not wait_until_clear(page, require_seen_block=True):
                    return 2
            total = len(horses)
            for index, horse in enumerate(horses, start=1):
                print(f"[{index}/{total}] {horse['pedigree_key']}", flush=True)
                require_seen_block = False
                while True:
                    try:
                        _fill_loaded_horse(page, conn, horse, book, delay)
                        break
                    except Blocked:
                        if not wait_until_clear(
                            page,
                            horse=horse,
                            require_seen_block=require_seen_block,
                        ):
                            return 2
                        require_seen_block = True
                        print(f"[{index}/{total}] retry {horse['pedigree_key']}", flush=True)
        finally:
            context.close()
    print("Pedigree fill finished.", flush=True)
    return 0


def enqueue(conn) -> int:
    print(f"Reading {queue.PEDIGREE_PATH.name} ...", flush=True)
    seen = 0
    if db is pgdb:
        for subject in queue.iter_subjects():
            db.upsert_pending(conn, subject)
            seen += 1
        total = db.count_rows(conn)
    else:
        with conn:
            for subject in queue.iter_subjects():
                db.upsert_pending(conn, subject)
                seen += 1
        total = conn.execute("SELECT COUNT(*) FROM horses").fetchone()[0]
    print(f"Queued {seen} pedigree horses. {total} rows in {db.DB_PATH.name}.", flush=True)
    return 0


def ensure_horse(conn, name: str, year: int) -> dict:
    year_s = str(year)
    name_key = queue.clean_name(name)
    rows = db.find_horses(conn, name, name_key, year_s)
    if len(rows) > 1:
        listed = ", ".join(f"{row['pedigree_key']} ({row['foal_year']})" for row in rows)
        raise SystemExit(f"More than one pedigree match: {listed}")
    if len(rows) == 1:
        return dict(rows[0])
    print(f"Looking up {name} ({year_s}) in pedigrees_database.py ...", flush=True)
    hits = queue.find_subjects(name, year_s)
    if len(hits) > 1:
        listed = ", ".join(f"{hit['pedigree_key']} ({hit['foal_year']})" for hit in hits)
        raise SystemExit(f"More than one pedigree match: {listed}")
    if len(hits) == 1:
        subject = hits[0]
    else:
        subject = {
            "pedigree_key": f"{name_key} ({year_s})",
            "name_key": name_key,
            "foal_year": year_s,
            "display_name": name.strip(),
        }
    db.upsert_pending(conn, subject)
    conn.commit()
    rows = db.find_horses(conn, subject["pedigree_key"], subject["name_key"], year_s)
    if not rows:
        raise SystemExit(f"Could not store a queue row for {name} ({year_s})")
    return dict(rows[0])


def _money(value) -> str:
    if value is None:
        return ""
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(int(value)):,}"


def _year_table(rows: list) -> tuple[list[list[str]], list[str]]:
    career = next((row for row in rows if str(row["year"]).lower() == "career"), None)
    years = [row for row in rows if str(row["year"]).lower() != "career"]
    years.sort(key=lambda row: (0, int(row["year"])) if str(row["year"]).isdigit() else (1, str(row["year"])))
    body = [
        [
            str(row["year"]),
            _cell(row["starts"]),
            _cell(row["firsts"]),
            _cell(row["seconds"]),
            _cell(row["thirds"]),
            _money(row["earnings"]),
        ]
        for row in years
    ]
    if career is not None:
        totals = career
    else:
        totals = {
            "starts": sum(row["starts"] or 0 for row in years),
            "firsts": sum(row["firsts"] or 0 for row in years),
            "seconds": sum(row["seconds"] or 0 for row in years),
            "thirds": sum(row["thirds"] or 0 for row in years),
            "earnings": sum(row["earnings"] or 0 for row in years),
        }
    body.append(
        [
            "Totals",
            _cell(totals["starts"]),
            _cell(totals["firsts"]),
            _cell(totals["seconds"]),
            _cell(totals["thirds"]),
            _money(totals["earnings"]),
        ]
    )
    return body, ["Year", "Starts", "1sts", "2nds", "3rds", "Earnings"]


def _cell(value) -> str:
    return "" if value is None else str(value)


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    def line(cells: list[str]) -> str:
        return " | ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells))
    print(line(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(line(row))


def show_horse(conn, query: str, year: int | None) -> int:
    name_key = queue.clean_name(query)
    year_s = str(year) if year is not None else ""
    rows = db.find_horses(conn, query, name_key, year_s or None)
    if not rows:
        print(f"No stored horse for {query}" + (f" ({year_s})" if year_s else ""))
        return 1
    if len(rows) > 1:
        print("More than one horse. Pass --year.")
        for row in rows:
            print(f"  {row['pedigree_key']}  {row['foal_year']}  {row['status']}")
        return 1
    horse = rows[0]
    title_year = horse["foal_year"] or ""
    name = horse["display_name"] or horse["pedigree_key"]
    print(f"{name} ({title_year})" if title_year else name)
    if horse["status"] != "ok":
        detail = f" ({horse['detail']})" if horse["detail"] else ""
        print(f"status: {horse['status']}{detail}")
    years = db.year_rows(conn, horse["id"])
    starts = db.start_rows(conn, horse["id"])
    if years:
        print()
        body, headers = _year_table(years)
        _print_table(headers, body)
    if starts:
        print()
        body = [
            [
                row["race_date"] or "",
                row["track"] or "",
                row["race_name"] or row["race_number"] or "",
                name,
                row["place"] or "",
                _cell(row["esf"]),
            ]
            for row in starts
        ]
        _print_table(["Date", "Track", "Race", "Horse", "Place", "ESF"], body)
    if not years and not starts:
        print("No race rows stored.")
    return 0 if horse["status"] == "ok" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Equibase race-record scraper")
    parser.add_argument("--enqueue", action="store_true", help="Queue top-level pedigree horses")
    parser.add_argument("--resume", action="store_true", help="Fetch horses that are not ok")
    parser.add_argument("--horse", help="Fetch one horse by name or pedigree key")
    parser.add_argument("--show", help="Print stored year totals and starts")
    parser.add_argument(
        "--fill-pedigrees",
        action="store_true",
        help="Fill 5-gen pedigrees for status=ok horses and store ancestor race records",
    )
    parser.add_argument("--year", type=int, help="Foaling year")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between requests")
    parser.add_argument(
        "--batch",
        help="With --resume, fetch only horses tagged with this queue_batch",
    )
    parser.add_argument(
        "--no-pedigree-fill",
        action="store_true",
        help="With --resume/--horse, skip 5-gen pedigree grafting (avoids loading pedigrees_database.py)",
    )
    args = parser.parse_args(argv)
    if not any([args.enqueue, args.resume, args.horse, args.show, args.fill_pedigrees]):
        parser.print_help()
        return 1
    if args.resume and args.horse:
        print("Pass either --horse or --resume, not both.")
        return 1
    if args.fill_pedigrees and (args.resume or args.horse or args.enqueue):
        print("Pass --fill-pedigrees on its own.")
        return 1
    if args.horse and args.year is None:
        print('Pass --year. Example: python3 -m equibase_scraper.run --horse "American Pharoah" --year 2012')
        return 1

    conn = db.connect()
    try:
        if args.enqueue:
            enqueue(conn)
        code = 0
        if args.horse:
            horse = ensure_horse(conn, args.horse, args.year)
            if horse["status"] == "ok":
                print(
                    f"{horse['display_name']} ({horse['foal_year']}) already stored. "
                    f'Print it with --show "{args.horse}" --year {args.year}',
                    flush=True,
                )
            else:
                code = run_fetch(
                    conn, [horse], args.delay, pedigree_fill=not args.no_pedigree_fill
                )
        elif args.resume:
            horses = db.resume_horses(conn, batch=args.batch)
            if args.batch:
                print(f"Batch {args.batch}: {len(horses)} horse(s) to fetch.", flush=True)
            code = run_fetch(
                conn, horses, args.delay, pedigree_fill=not args.no_pedigree_fill
            )
        elif args.fill_pedigrees:
            code = run_fill_pedigrees(conn, args.delay)
        if args.show:
            show_code = show_horse(conn, args.show, args.year)
            if code == 0:
                code = show_code
        return code
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
