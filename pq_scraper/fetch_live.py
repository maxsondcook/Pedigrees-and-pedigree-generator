#!/usr/bin/env python3
"""Live Pedigree Query importer via headed persistent Chrome (Playwright).

Mirrors the BloodHorse scrape that beat Imperva: real Chrome, persistent
profile, --disable-blink-features=AutomationControlled. Does NOT use Wayback.

Queue is Place 1/2/3 horses missing from pedigree_map, processed Z→A so this
process does not collide with the forward Wayback cursor.

Usage:
  python3 pq_scraper/fetch_live.py --smoke
  python3 pq_scraper/fetch_live.py --limit 4000 --concurrency 1 --delay 1.0
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import time
from datetime import datetime, timezone
from multiprocessing import Process, Queue
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import clean_horse_name  # noqa: E402
from pq_scraper.client import (  # noqa: E402
    HOMONYM_MAX,
    countries_compatible,
    horse_slug,
    horse_url,
    slug_with_suffix,
    years_match,
)
from pq_scraper.dbio import (  # noqa: E402
    backup_database_once,
    existing_name_years,
    load_pedigree_map,
    save_pedigree_map,
    storage_key_for,
)
from pq_scraper.fetch_pedigrees import (  # noqa: E402
    MISS_FIELDS,
    SMOKE_CASES,
    names_compat,
    unique_placed,
)
from pq_scraper.parser import (  # noqa: E402
    looks_like_challenge,
    looks_like_not_found,
    looks_like_pedigree_page,
    node_at,
    parse_pedigree_html,
)

SCRAPER_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRAPER_DIR / "cache_live"
PROFILE_BASE = SCRAPER_DIR / "chrome_profile_live"
PROGRESS_PATH = SCRAPER_DIR / "progress_live.json"
MISSES_PATH = SCRAPER_DIR / "misses_live.csv"
SESSION_PATH = SCRAPER_DIR / "live_session.json"
HOME_URL = "https://www.pedigreequery.com/"
CF_STOP_AFTER = 5
# Sit on the same tab while the user clicks the Cloudflare box. Reloading
# (page.goto again) is what makes it ask "are you a bot?" over and over.
HUMAN_CF_WAIT_S = 300
TERMINAL_REASONS = {"404", "ambiguous", "year mismatch", "parse error"}
SMOKE_LIVE = [c for c in SMOKE_CASES if c["label"] in {"Frammento", "American Pharoah", "Winx"}]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def cache_paths(url: str) -> tuple[Path, Path]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _hash_url(url)
    return CACHE_DIR / f"{key}.html", CACHE_DIR / f"{key}.meta.json"


def read_cache(url: str) -> tuple[str | None, dict | None]:
    html_path, meta_path = cache_paths(url)
    if not html_path.is_file():
        return None, None
    html = html_path.read_text(encoding="utf-8", errors="replace")
    meta = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    return html, meta


def write_cache(url: str, html: str, meta: dict) -> None:
    html_path, meta_path = cache_paths(url)
    html_path.write_text(html, encoding="utf-8")
    payload = dict(meta)
    payload["url"] = url
    payload["bytes"] = len(html.encode("utf-8", errors="replace"))
    payload["cached_at"] = _now()
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_progress() -> dict:
    if PROGRESS_PATH.is_file():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "started_at": _now(),
        "updated_at": _now(),
        "added": 0,
        "missed": 0,
        "skipped_already_in_db": 0,
        "remaining": 0,
        "cursor": 0,
        "by_reason": {},
        "last_added": "",
        "last_names": [],
        "cf_blocks": 0,
        "queue": "placed_123_reverse",
        "source": "live_headed_chrome",
    }


def save_progress(progress: dict) -> None:
    progress["updated_at"] = _now()
    PROGRESS_PATH.write_text(json.dumps(progress, indent=2), encoding="utf-8")


def load_session_added() -> dict:
    if not SESSION_PATH.is_file():
        return {}
    try:
        return json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_session_added(session_added: dict) -> None:
    SESSION_PATH.write_text(json.dumps(session_added), encoding="utf-8")


def existing_key_set(pedigree_map: dict | None = None) -> set[str]:
    pedigree_map = pedigree_map if pedigree_map is not None else load_pedigree_map()
    return {clean_horse_name(k) for k in pedigree_map.keys()}


def existing_identity_set(pedigree_map: dict | None = None) -> set[tuple[str, str]]:
    pedigree_map = pedigree_map if pedigree_map is not None else load_pedigree_map()
    return existing_name_years(pedigree_map, clean_horse_name)


def load_live_miss_keys() -> set[tuple[str, str]]:
    keys = set()
    if not MISSES_PATH.is_file():
        return keys
    with MISSES_PATH.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            reason = (row.get("reason") or "").strip()
            if reason in TERMINAL_REASONS:
                keys.add((row.get("clean_key") or "", row.get("year") or ""))
    return keys


def append_miss(row: dict) -> None:
    new_file = not MISSES_PATH.is_file()
    with MISSES_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MISS_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in MISS_FIELDS})


def reverse_missing(existing=None) -> list[dict]:
    """Unique Place 1/2/3 not in pedigree_map, Z→A by clean name."""
    ident = existing if existing is not None else existing_identity_set()
    if ident and not isinstance(next(iter(ident)), tuple):
        ident = existing_identity_set()
    missing = [w for w in unique_placed() if (w["clean_key"], w["year"]) not in ident]
    missing.sort(key=lambda h: (h["clean_key"], h["year"]), reverse=True)
    return missing


def browser_closed(exc: BaseException | str) -> bool:
    text = str(exc).lower()
    return "has been closed" in text or "target page, context or browser" in text


def launch_chrome(profile_name: str):
    from playwright.sync_api import sync_playwright

    profile = PROFILE_BASE / profile_name
    profile.mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    # Do not spoof UA — BloodHorse only passed with Chrome's real version string.
    context = pw.chromium.launch_persistent_context(
        user_data_dir=str(profile),
        channel="chrome",
        headless=False,
        locale="en-US",
        viewport={"width": 1440, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return pw, context, page


def _page_debug(page, html: str, label: str) -> None:
    title = ""
    url = ""
    try:
        title = page.title() or ""
    except Exception:
        pass
    try:
        url = page.url or ""
    except Exception:
        pass
    snippet = " ".join((html or "")[:400].split())
    print(f"  {label} url={url!r} title={title!r} snippet={snippet!r}", flush=True)
    debug = CACHE_DIR / "debug_last_block.html"
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        debug.write_text(html or "", encoding="utf-8")
    except OSError:
        pass


def _looks_like_pq_home(html: str) -> bool:
    if not html:
        return False
    low = html.lower()
    if looks_like_challenge(html):
        return False
    return "thoroughbred horse pedigree" in low or "pedigreequery" in low


def wait_out_challenge(page, html: str, label: str, seconds: int = HUMAN_CF_WAIT_S) -> tuple[str, str]:
    """Poll the current page. Do not navigate — that retriggers Cloudflare."""
    if not looks_like_challenge(html):
        return html, "ok"
    print(
        f"  Cloudflare check on {label}. Click it ONCE in the Chrome window and wait. "
        f"I will not reload ({seconds}s).",
        flush=True,
    )
    _page_debug(page, html, label)
    deadline = time.time() + seconds
    last_note = 0.0
    while time.time() < deadline:
        page.wait_for_timeout(1000)
        try:
            html = page.content()
        except Exception as exc:
            if browser_closed(exc):
                return html, f"error:{exc}"
            continue
        if not looks_like_challenge(html):
            print(f"  Cloudflare cleared on {label}", flush=True)
            return html, "ok"
        if time.time() - last_note >= 30:
            left = int(deadline - time.time())
            print(f"  still waiting for Cloudflare click ({left}s left)", flush=True)
            last_note = time.time()
    return html, "blocked"


def warmup(page, attempts: int = 1) -> tuple[bool, str]:
    """Open PQ home once and wait. Never reload during a Cloudflare check."""
    try:
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        html = page.content()
        html, status = wait_out_challenge(page, html, "homepage")
        if status != "ok":
            print(f"  warmup still {status}", flush=True)
            return False, status
        if _looks_like_pq_home(html) or not looks_like_challenge(html):
            title = ""
            try:
                title = page.title() or ""
            except Exception:
                pass
            print(f"  warmup ok title={title!r}", flush=True)
            return True, "ok"
        return False, "not homepage"
    except Exception as exc:
        print(f"  warmup error: {exc}", flush=True)
        return False, f"error:{exc}"


def fetch_page(page, url: str, delay: float, attempts: int = CF_STOP_AFTER, use_cache: bool = True) -> dict:
    cached, meta = read_cache(url) if use_cache else (None, None)
    if cached:
        if looks_like_pedigree_page(cached) and not looks_like_challenge(cached):
            return {
                "ok": True,
                "html": cached,
                "source": "cache_live",
                "reason": "",
                "from_cache": True,
            }
        if looks_like_not_found(cached) and not looks_like_challenge(cached):
            return {
                "ok": False,
                "html": cached,
                "source": "cache_live",
                "reason": "404",
                "from_cache": True,
            }

    last = "empty"
    html = ""
    time.sleep(delay + random.uniform(0.0, 0.4))
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        html = page.content()
        html, status = wait_out_challenge(page, html, url)
        if browser_closed(status):
            return {
                "ok": False,
                "html": html,
                "source": "live_headed",
                "reason": status,
                "from_cache": False,
            }
        if looks_like_challenge(html):
            return {
                "ok": False,
                "html": html,
                "source": "live_headed",
                "reason": "blocked",
                "from_cache": False,
            }
        try:
            page.wait_for_selector("td.f, td.m, a.nounderline", timeout=4000)
        except Exception:
            pass
        html = page.content()
    except Exception as exc:
        last = f"error:{exc}"
        print(f"  fetch error {url}: {exc}", flush=True)
        return {
            "ok": False,
            "html": html,
            "source": "live_headed",
            "reason": last,
            "from_cache": False,
        }
    if looks_like_pedigree_page(html):
        write_cache(url, html, {"source": "live_headed", "status": 200})
        return {
            "ok": True,
            "html": html,
            "source": "live_headed",
            "reason": "",
            "from_cache": False,
        }
    if looks_like_not_found(html):
        write_cache(url, html, {"source": "live_headed", "status": 404})
        return {
            "ok": False,
            "html": html,
            "source": "live_headed",
            "reason": "404",
            "from_cache": False,
        }
    return {
        "ok": False,
        "html": html,
        "source": "live_headed",
        "reason": last or "not a pedigree page",
        "from_cache": False,
    }


def resolve_horse(page, name: str, year: str, country: str, delay: float, use_cache: bool = True) -> dict:
    slug = horse_slug(name)
    matches = []
    last_reason = "404"
    consecutive_misses = 0
    for n in range(1, HOMONYM_MAX + 1):
        url = horse_url(slug_with_suffix(slug, n))
        result = fetch_page(page, url, delay=delay, use_cache=use_cache)
        if not result.get("ok"):
            last_reason = result.get("reason") or "404"
            if last_reason == "blocked":
                return {
                    "ok": False,
                    "reason": "blocked",
                    "detail": f"slug={slug}",
                    "tree": None,
                    "meta": {},
                }
            if n == 1:
                return {
                    "ok": False,
                    "reason": last_reason,
                    "detail": f"slug={slug}",
                    "tree": None,
                    "meta": {},
                }
            consecutive_misses += 1
            if consecutive_misses >= 2:
                break
            continue
        consecutive_misses = 0
        try:
            tree, meta = parse_pedigree_html(result["html"], generations=5)
        except ValueError as exc:
            return {
                "ok": False,
                "reason": "parse error",
                "detail": str(exc),
                "tree": None,
                "meta": {},
            }
        pq_year = meta.get("year")
        pq_country = meta.get("country")
        if year and pq_year and not years_match(pq_year, year):
            last_reason = "year mismatch"
            continue
        if not countries_compatible(pq_country, country):
            last_reason = "year mismatch"
            continue
        matches.append({"tree": tree, "meta": meta, "url": url, "source": result.get("source")})
        if n == 1 and year and pq_year and years_match(pq_year, year):
            break

    if not matches:
        return {"ok": False, "reason": last_reason, "detail": f"slug={slug}", "tree": None, "meta": {}}
    if len(matches) > 1:
        return {
            "ok": False,
            "reason": "ambiguous",
            "detail": f"{len(matches)} PQ horses matched year/country",
            "tree": None,
            "meta": {},
        }
    hit = matches[0]
    return {
        "ok": True,
        "reason": "",
        "detail": hit.get("source") or "",
        "tree": hit["tree"],
        "meta": hit["meta"],
        "url": hit["url"],
    }


def persist_new(session_added: dict, progress: dict) -> int:
    """flock via dbio: reload disk, insert session keys only, save."""
    if not session_added:
        save_progress(progress)
        return 0
    pedigree_map = dict(session_added)
    before = set(pedigree_map)
    save_pedigree_map(pedigree_map)
    save_session_added(session_added)
    save_progress(progress)
    return sum(1 for k in before if k in pedigree_map)


def run_smoke() -> tuple[int, object, object, object]:
    print("SMOKE: launching headed persistent Chrome…", flush=True)
    pw, context, page = launch_chrome("smoke")
    try:
        ok, reason = warmup(page, attempts=CF_STOP_AFTER)
        if not ok:
            print(f"  homepage warmup did not clear CF ({reason}); trying Frammento next", flush=True)
        failures = []
        passes = []
        for case in SMOKE_LIVE:
            print(f"SMOKE fetch {case['label']} {case['pq_url']}", flush=True)
            result = fetch_page(page, case["pq_url"], delay=1.0, attempts=CF_STOP_AFTER)
            if result.get("reason") == "blocked":
                print(
                    f"SMOKE STOP: Cloudflare still blocking headed Chrome after "
                    f"{CF_STOP_AFTER} tries on {case['label']}",
                    flush=True,
                )
                return 2, pw, context, page
            html = result.get("html") or ""
            if not result.get("ok") or not html:
                failures.append(f"{case['label']}: {result.get('reason') or 'no HTML'}")
                continue
            try:
                tree, meta = parse_pedigree_html(html, generations=5)
            except ValueError as exc:
                failures.append(f"{case['label']}: parse error {exc}")
                continue
            sire = (node_at(tree, "Sire") or {}).get("Horse")
            dam = (node_at(tree, "Dam") or {}).get("Horse")
            gs = (node_at(tree, "Sire.Sire") or {}).get("Horse")
            print(
                f"  {case['label']}: {tree.get('Horse')} "
                f"country={meta.get('country')} sire={sire} dam={dam} via {result.get('source')}",
                flush=True,
            )
            if case["expect_year"] and meta.get("year") != case["expect_year"]:
                failures.append(
                    f"{case['label']} year: got {meta.get('year')} expected {case['expect_year']}"
                )
            if case["expect_country"] and meta.get("country") != case["expect_country"]:
                failures.append(
                    f"{case['label']} country: got {meta.get('country')} expected {case['expect_country']}"
                )
            if not names_compat(sire, case["expect_sire"]):
                failures.append(f"{case['label']} sire: got {sire!r} expected {case['expect_sire']}")
            if not names_compat(dam, case["expect_dam"]):
                failures.append(f"{case['label']} dam: got {dam!r} expected {case['expect_dam']}")
            if not names_compat(gs, case["expect_grandsire"]):
                failures.append(
                    f"{case['label']} grandsire: got {gs!r} expected {case['expect_grandsire']}"
                )
            if not any(case["label"] in f for f in failures):
                passes.append(case["label"])
        print("SMOKE PASSES:", ", ".join(passes) or "(none)", flush=True)
        if failures:
            print("SMOKE FAIL", flush=True)
            for e in failures:
                print(" ", e, flush=True)
            return 1, pw, context, page
        print("SMOKE PASS (live headed Chrome works)", flush=True)
        return 0, pw, context, page
    except Exception:
        context.close()
        pw.stop()
        raise


def grind_worker(
    queue: list[dict],
    delay: float,
    save_every: int,
    profile_name: str,
    result_q: Queue,
    reuse_browser: tuple | None = None,
) -> None:
    session_added = load_session_added()
    progress = load_progress()
    existing = existing_identity_set()
    session_ids = existing_name_years(session_added, clean_horse_name)
    miss_keys = load_live_miss_keys()
    added_this = 0
    missed_this = 0
    skipped = 0
    processed = 0
    cf_blocks = 0
    last_names: list[str] = list(progress.get("last_names") or [])
    by_reason = dict(progress.get("by_reason") or {})
    t0 = time.time()
    own_browser = reuse_browser is None
    if reuse_browser:
        pw, context, page = reuse_browser
    else:
        print(f"[{profile_name}] launching headed Chrome…", flush=True)
        pw, context, page = launch_chrome(profile_name)
        ok, reason = warmup(page)
        if not ok:
            print(f"[{profile_name}] homepage warmup still {reason}; continuing to queue", flush=True)

    def persist(force: bool = False) -> None:
        if not force and (added_this == 0 or added_this % save_every != 0):
            return
        progress.update(
            {
                "added": progress.get("added", 0),
                "missed": progress.get("missed", 0),
                "remaining": max(len(queue) - processed, 0),
                "cursor": processed,
                "by_reason": by_reason,
                "cf_blocks": progress.get("cf_blocks", 0),
                "last_names": last_names[-12:],
            }
        )
        persist_new(session_added, progress)
        print(
            f"  [{profile_name}] saved added={added_this} missed={missed_this} "
            f"session_keys={len(session_added)} last={progress.get('last_added')}",
            flush=True,
        )

    try:
        for horse in queue:
            processed += 1
            if processed % 8 == 0:
                existing = existing_identity_set()
            key = horse["clean_key"]
            pair = (key, str(horse["year"]))
            if pair in existing or pair in session_ids:
                skipped += 1
                continue
            if (key, horse["year"]) in miss_keys:
                skipped += 1
                continue
            resolved = resolve_horse(page, horse["name"], horse["year"], horse["country"], delay)
            reason = (resolved.get("reason") or "").strip()
            if reason == "blocked":
                cf_blocks += 1
                progress["cf_blocks"] = progress.get("cf_blocks", 0) + 1
                print(f"~ CF block {key} ({horse['year']}) #{cf_blocks}", flush=True)
                if cf_blocks >= CF_STOP_AFTER:
                    print(
                        f"STOP: {CF_STOP_AFTER} Cloudflare blocks on live headed Chrome. "
                        "Not falling back to Wayback.",
                        flush=True,
                    )
                    persist(force=True)
                    result_q.put(
                        {
                            "added": added_this,
                            "missed": missed_this,
                            "skipped": skipped,
                            "cf_blocks": cf_blocks,
                            "last_names": last_names[-12:],
                            "stop": "cf_blocked",
                        }
                    )
                    return
                continue
            if not resolved.get("ok"):
                missed_this += 1
                progress["missed"] = progress.get("missed", 0) + 1
                by_reason[reason or "404"] = by_reason.get(reason or "404", 0) + 1
                append_miss(
                    {
                        "name": horse["name"],
                        "year": horse["year"],
                        "country": horse["country"],
                        "clean_key": key,
                        "reason": reason or "404",
                        "detail": resolved.get("detail") or "",
                    }
                )
                miss_keys.add((key, horse["year"]))
                print(f"- miss {key} ({horse['year']}) {reason}", flush=True)
                continue
            # Reload immediately before insert so we never overwrite Wayback keys.
            existing = existing_identity_set()
            if pair in existing:
                skipped += 1
                continue
            store_key = storage_key_for(key, horse["year"], {**load_pedigree_map(), **session_added}, clean_horse_name)
            session_added[store_key] = resolved["tree"]
            existing.add(pair)
            session_ids.add(pair)
            added_this += 1
            progress["added"] = progress.get("added", 0) + 1
            label = f"{key} ({horse['year']})"
            progress["last_added"] = label
            last_names.append(label)
            print(
                f"+ {label} {resolved['tree'].get('Horse')} via {resolved.get('detail')}",
                flush=True,
            )
            if added_this % save_every == 0:
                persist(force=True)
                elapsed = max(time.time() - t0, 0.001)
                rate = (added_this + missed_this) / (elapsed / 60.0)
                print(f"  rate={rate:.1f}/min elapsed={elapsed:.0f}s", flush=True)
        persist(force=True)
        result_q.put(
            {
                "added": added_this,
                "missed": missed_this,
                "skipped": skipped,
                "cf_blocks": cf_blocks,
                "last_names": last_names[-12:],
                "stop": "",
            }
        )
    except KeyboardInterrupt:
        print("\nInterrupted — saving…", flush=True)
        persist(force=True)
        result_q.put(
            {
                "added": added_this,
                "missed": missed_this,
                "skipped": skipped,
                "cf_blocks": cf_blocks,
                "last_names": last_names[-12:],
                "stop": "interrupt",
            }
        )
    finally:
        if own_browser:
            try:
                context.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass


def import_reverse(args, reuse_browser: tuple | None = None) -> int:
    backup = backup_database_once()
    print(f"Backup: {backup}", flush=True)
    existing = existing_identity_set()
    missing = reverse_missing(existing)
    print(
        f"Unique Place 1/2/3 missing: {len(missing)} (Z→A). "
        f"already_in_db≈{len(existing)} delay={args.delay}s "
        f"concurrency={args.concurrency}",
        flush=True,
    )
    queue = missing
    if args.offset:
        queue = queue[args.offset :]
    if args.limit and args.limit > 0:
        queue = queue[: args.limit]
    print(f"This live run queue: {len(queue)} (reverse, first={queue[0]['clean_key'] if queue else '—'})", flush=True)
    if not queue:
        print("Nothing to fetch", flush=True)
        return 0

    result_q: Queue = Queue()
    n = max(1, min(int(args.concurrency), 2))
    if n == 1 or reuse_browser is not None:
        grind_worker(queue, args.delay, args.save_every, "headed1", result_q, reuse_browser)
        results = [result_q.get()]
    else:
        shards = [queue[i::n] for i in range(n)]
        procs = [
            Process(
                target=grind_worker,
                args=(shard, args.delay, args.save_every, f"headed{i + 1}", result_q, None),
            )
            for i, shard in enumerate(shards)
            if shard
        ]
        for proc in procs:
            proc.start()
        results = [result_q.get() for _ in procs]
        for proc in procs:
            proc.join()

    added = sum(r.get("added", 0) for r in results)
    missed = sum(r.get("missed", 0) for r in results)
    skipped = sum(r.get("skipped", 0) for r in results)
    cf_blocks = sum(r.get("cf_blocks", 0) for r in results)
    last_names = []
    for r in results:
        last_names.extend(r.get("last_names") or [])
    stops = [r.get("stop") for r in results if r.get("stop")]
    print(
        f"LIVE DONE added={added} missed={missed} skipped={skipped} "
        f"cf_blocks={cf_blocks} last_names={last_names[-8:]} stop={stops or 'ok'}",
        flush=True,
    )
    return 2 if any(s in {"warmup_blocked", "cf_blocked"} for s in stops) else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Live headed-Chrome PQ importer (reverse queue)")
    p.add_argument("--smoke", action="store_true", help="Only smoke-test Frammento + 2 live pages")
    p.add_argument("--limit", type=int, default=0, help="Max horses to attempt from the reverse queue")
    p.add_argument("--offset", type=int, default=0, help="Skip this many reverse-queue horses first")
    p.add_argument("--save-every", type=int, default=25, help="Incremental DB save interval")
    p.add_argument("--delay", type=float, default=1.0, help="Base seconds between page fetches")
    p.add_argument("--concurrency", type=int, default=1, help="Headed Chrome workers (1–2)")
    args = p.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_BASE.mkdir(parents=True, exist_ok=True)

    if args.smoke:
        code, pw, context, page = run_smoke()
        try:
            context.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass
        return code

    print("Pre-grind smoke (Frammento + 2 live pages)…", flush=True)
    code, pw, context, page = run_smoke()
    if code != 0:
        try:
            context.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass
        print("Not starting reverse grind — live headed Chrome did not pass smoke.", flush=True)
        return code
    # Reuse the warmed smoke browser for concurrency=1.
    if max(1, min(int(args.concurrency), 2)) == 1:
        try:
            return import_reverse(args, reuse_browser=(pw, context, page))
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass
    try:
        context.close()
    except Exception:
        pass
    try:
        pw.stop()
    except Exception:
        pass
    return import_reverse(args, reuse_browser=None)


if __name__ == "__main__":
    raise SystemExit(main())
