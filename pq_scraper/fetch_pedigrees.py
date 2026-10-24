#!/usr/bin/env python3
"""Import 5-generation Pedigree Query trees for GSW horses, then incomplete ancestors.

Usage:
  python3 pq_scraper/fetch_pedigrees.py --smoke
  python3 pq_scraper/fetch_pedigrees.py --resume --retry-misses --queue auto --source live
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import clean_horse_name  # noqa: E402
from graded_stakes import load_stakes_data  # noqa: E402

from pq_scraper.client import (  # noqa: E402
    DEFAULT_DELAY,
    HOMONYM_MAX,
    RateLimiter,
    countries_compatible,
    fetch_url,
    horse_slug,
    horse_url,
    slug_with_suffix,
    write_cache,
    years_match,
)
from pq_scraper.dbio import (  # noqa: E402
    backup_database_once,
    existing_name_years,
    load_pedigree_map,
    save_pedigree_map,
    storage_key_for,
)
from pq_scraper.parser import (  # noqa: E402
    horse_year,
    node_at,
    parse_pedigree_html,
)

SCRAPER_DIR = Path(__file__).resolve().parent
FIXTURES = SCRAPER_DIR / "fixtures"
PROGRESS_PATH = SCRAPER_DIR / "progress.json"
MISSES_PATH = SCRAPER_DIR / "misses.csv"
RETRY_PATH = SCRAPER_DIR / "rate_limited_retry.csv"
MISS_FIELDS = ["name", "year", "country", "clean_key", "reason", "detail"]
TERMINAL_REASONS = {"404", "ambiguous", "year mismatch", "parse error"}
RETRYABLE_REASONS = {"rate limited", "rate_limited", "blocked", "unavailable"}
HEARTBEAT_SECONDS = 20

SMOKE_CASES = [
    {
        "label": "Frammento",
        "fixture": "frammento.html",
        "pq_url": "https://www.pedigreequery.com/frammento",
        "expect_year": "2012",
        "expect_country": "USA",
        "expect_sire": "MIDSHIPMAN",
        "expect_dam": "GINGER BAY",
        "expect_grandsire": "UNBRIDLEDS SONG",
        "db_key": None,
    },
    {
        "label": "American Pharoah",
        "fixture": "american_pharoah.html",
        "pq_url": "https://www.pedigreequery.com/american+pharoah",
        "expect_year": "2012",
        "expect_country": "USA",
        "expect_sire": "PIONEEROF THE NILE",
        "expect_dam": "LITTLEPRINCESSEMMA",
        "expect_grandsire": "EMPIRE MAKER",
        "db_key": "AMERICAN PHAROAH",
    },
    {
        "label": "Winx",
        "fixture": "winx.html",
        "pq_url": "https://www.pedigreequery.com/winx",
        "expect_year": "2011",
        "expect_country": "AUS",
        "expect_sire": "STREET CRY",
        "expect_dam": "VEGAS SHOWGIRL",
        "expect_grandsire": "MACHIAVELLIAN",
        "db_key": None,
    },
    {
        "label": "Flightline",
        "fixture": "flightline.html",
        "pq_url": "https://www.pedigreequery.com/flightline",
        "expect_year": "2018",
        "expect_country": "USA",
        "expect_sire": "TAPIT",
        "expect_dam": "FEATHERED",
        "expect_grandsire": "PULPIT",
        "db_key": "FLIGHTLINE",
        "optional": True,
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_progress() -> dict:
    if PROGRESS_PATH.is_file():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "started_at": _now(),
        "updated_at": _now(),
        "skipped_already_in_db": 0,
        "added": 0,
        "missed": 0,
        "remaining": 0,
        "cursor": 0,
        "by_reason": {},
        "last_added": "",
    }


def save_progress(progress: dict) -> None:
    progress["updated_at"] = _now()
    progress["heartbeat_at"] = progress.get("heartbeat_at") or progress["updated_at"]
    PROGRESS_PATH.write_text(json.dumps(progress, indent=2), encoding="utf-8")


def heartbeat(progress: dict, **fields) -> None:
    progress.update(fields)
    progress["heartbeat_at"] = _now()
    save_progress(progress)


def load_miss_keys() -> set[tuple[str, str]]:
    keys = set()
    if not MISSES_PATH.is_file():
        return keys
    with MISSES_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keys.add((row.get("clean_key") or "", row.get("year") or ""))
    return keys


def append_csv(path: Path, row: dict) -> None:
    new_file = not path.is_file()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MISS_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in MISS_FIELDS})


def append_miss(row: dict) -> None:
    append_csv(MISSES_PATH, row)


def append_retry(row: dict) -> None:
    append_csv(RETRY_PATH, row)


def load_retry_keys() -> list[tuple[str, str]]:
    keys = []
    seen = set()
    if not RETRY_PATH.is_file():
        return keys
    with RETRY_PATH.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            pair = (row.get("clean_key") or "", row.get("year") or "")
            if pair not in seen:
                seen.add(pair)
                keys.append(pair)
    return keys


def rewrite_misses_without_rate_limits() -> int:
    """Move rate-limited rows out of misses.csv into rate_limited_retry.csv. Return count moved."""
    if not MISSES_PATH.is_file():
        return 0
    keep = []
    moved = []
    with MISSES_PATH.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            reason = (row.get("reason") or "").strip().lower()
            if reason in {"rate limited", "rate_limited", "blocked"}:
                moved.append(row)
            else:
                keep.append(row)
    with MISSES_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MISS_FIELDS)
        writer.writeheader()
        for row in keep:
            writer.writerow({k: row.get(k, "") for k in MISS_FIELDS})
    existing = set(load_retry_keys())
    added = 0
    for row in moved:
        pair = (row.get("clean_key") or "", row.get("year") or "")
        if pair in existing:
            continue
        append_retry({k: row.get(k, "") for k in MISS_FIELDS})
        existing.add(pair)
        added += 1
    return added


def rewrite_homonym_misses(pedigree_map: dict) -> int:
    """Drop terminal misses for a name already in the DB under a different year."""
    if not MISSES_PATH.is_file():
        return 0
    ident = existing_name_years(pedigree_map, clean_horse_name)
    names_in_db = {name for name, _year in ident}
    keep = []
    dropped = 0
    with MISSES_PATH.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            name = row.get("clean_key") or ""
            year = str(row.get("year") or "")
            if name in names_in_db and (name, year) not in ident:
                dropped += 1
                continue
            keep.append(row)
    if not dropped:
        return 0
    with MISSES_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MISS_FIELDS)
        writer.writeheader()
        for row in keep:
            writer.writerow({k: row.get(k, "") for k in MISS_FIELDS})
    return dropped


def _horse_from_record(rec: dict, place_n: int | None = None) -> dict | None:
    name = str(rec.get("Horse Name") or "").strip()
    if not name or name.upper() in ("N/A", "NAN", "NONE"):
        return None
    year = str(rec.get("Foaling Year") or rec.get("Year Foaled") or "").strip()
    if year.upper() in ("N/A", "NAN", "NONE"):
        year = ""
    country = str(rec.get("Horse Country Suffix") or "").strip()
    key = clean_horse_name(name)
    if not key:
        return None
    return {
        "name": name,
        "year": year,
        "country": country,
        "clean_key": key,
        "place": place_n,
    }


def unique_placed() -> list[dict]:
    """Unique Place 1/2/3 horses from the IFHA CSV (name + foaling year)."""
    records = load_stakes_data(winners_only=False)
    seen = set()
    out = []
    for rec in records:
        place = rec.get("Place")
        try:
            place_n = int(place)
        except (TypeError, ValueError):
            continue
        if place_n not in (1, 2, 3):
            continue
        horse = _horse_from_record(rec, place_n)
        if not horse:
            continue
        dedupe = (horse["clean_key"], horse["year"])
        if dedupe in seen:
            continue
        seen.add(dedupe)
        out.append(horse)
    return out


def unique_gsw_csv() -> list[dict]:
    """Every named horse in graded_stakes_winners.csv (name + foaling year)."""
    records = load_stakes_data(winners_only=False)
    seen = set()
    out = []
    for rec in records:
        place = rec.get("Place")
        try:
            place_n = int(place)
        except (TypeError, ValueError):
            place_n = None
        horse = _horse_from_record(rec, place_n)
        if not horse:
            continue
        dedupe = (horse["clean_key"], horse["year"])
        if dedupe in seen:
            continue
        seen.add(dedupe)
        out.append(horse)
    return out


def unique_winners() -> list[dict]:
    return unique_placed()


def load_queue_horses(queue_name: str) -> tuple[list[dict], str]:
    if queue_name == "placed_123":
        return unique_placed(), "Unique 1st/2nd/3rd (name+year)"
    if queue_name == "ancestors":
        from pq_scraper.ancestors import incomplete_ancestor_queue
        from pq_scraper.dbio import existing_name_years, load_pedigree_map

        pedigree_map = load_pedigree_map()
        existing = existing_name_years(pedigree_map, clean_horse_name)
        return (
            incomplete_ancestor_queue(pedigree_map, clean_horse_name, existing),
            "Incomplete ancestor slots (5-gen)",
        )
    return unique_gsw_csv(), "Unique GSW-CSV horses (name+year)"


def names_compat(a: str | None, b: str | None) -> bool:
    ca = clean_horse_name(a or "")
    cb = clean_horse_name(b or "")
    if ca == cb:
        return True
    # PQ often strips apostrophes in display ("UNBRIDLEDS SONG" vs "UNBRIDLED'S SONG")
    def collapse(s: str) -> str:
        return s.replace(" ", "")

    if collapse(ca) == collapse(cb):
        return True
    if ca.replace("S ", " ") == cb or cb.replace("S ", " ") == ca:
        return True
    return False


def smoke_compare_db(tree: dict, db_tree: dict, label: str) -> list[str]:
    errors = []
    checks = [
        ("sire", "Sire"),
        ("dam", "Dam"),
        ("grandsire", "Sire.Sire"),
    ]
    for what, path in checks:
        pq_node = node_at(tree, path)
        db_node = node_at(db_tree, path)
        pq_h = (pq_node or {}).get("Horse")
        db_h = (db_node or {}).get("Horse")
        if not names_compat(pq_h, db_h):
            errors.append(f"{label} {what} mismatch: PQ={pq_h!r} DB={db_h!r}")
        py, dy = horse_year(pq_h), horse_year(db_h)
        if py and dy and py != dy:
            errors.append(f"{label} {what} year mismatch: PQ={py} DB={dy}")
    return errors


def run_smoke(allow_network: bool) -> int:
    from pq_scraper.parser import parse_name_year

    unit_errors = []
    samples = [
        ("MIDSHIPMAN (USA) ch. 2006", "", "MIDSHIPMAN", "2006", "USA"),
        ("A.P. INDY (USA) dkb/br. 1989 [IC]", "", "A.P. INDY", "1989", "USA"),
        ("MR. PROSPECTOR (USA)", "b. 1970 [BC]", "MR. PROSPECTOR", "1970", "USA"),
        ("LITTLEPRINCESSEMMA (USA) dkb/br. 2006", "", "LITTLEPRINCESSEMMA", "2006", "USA"),
        ("UNBRIDLEDS SONG (USA) gr. 1993", "", "UNBRIDLEDS SONG", "1993", "USA"),
        ("TRI JET (USA) dkb/br. 1969", "", "TRI JET", "1969", "USA"),
    ]
    for text, extra, exp_name, exp_year, exp_cc in samples:
        name, year, cc = parse_name_year(text, extra)
        if name.upper() != exp_name or year != exp_year or cc != exp_cc:
            unit_errors.append(
                f"parse_name_year({text!r}): got {(name, year, cc)} expected {(exp_name, exp_year, exp_cc)}"
            )
    if unit_errors:
        print("SMOKE FAIL (unit)")
        for e in unit_errors:
            print(" ", e)
        return 1

    db_map = load_pedigree_map()
    failures = []
    passes = []
    for case in SMOKE_CASES:
        html = None
        fixture = FIXTURES / case["fixture"]
        if fixture.is_file():
            html = fixture.read_text(encoding="utf-8", errors="replace")
        elif allow_network:
            print(f"  fetching {case['label']} (no fixture)...")
            result = fetch_url(case["pq_url"], allow_live=True, allow_wayback=True)
            html = result.get("html") if result.get("ok") else None
        if not html:
            if case.get("optional"):
                print(f"SMOKE SKIP {case['label']}: no HTML (live PQ blocked / not archived)")
                continue
            failures.append(f"{case['label']}: missing fixture/HTML")
            continue
        try:
            tree, meta = parse_pedigree_html(html, generations=5)
        except ValueError as exc:
            failures.append(f"{case['label']}: parse error {exc}")
            continue
        print(
            f"  {case['label']}: {tree.get('Horse')} country={meta.get('country')} "
            f"sire={node_at(tree, 'Sire') and node_at(tree, 'Sire').get('Horse')} "
            f"dam={node_at(tree, 'Dam') and node_at(tree, 'Dam').get('Horse')}"
        )
        if case["expect_year"] and meta.get("year") != case["expect_year"]:
            failures.append(
                f"{case['label']} year: got {meta.get('year')} expected {case['expect_year']}"
            )
        if case["expect_country"] and meta.get("country") != case["expect_country"]:
            failures.append(
                f"{case['label']} country: got {meta.get('country')} expected {case['expect_country']}"
            )
        sire = (node_at(tree, "Sire") or {}).get("Horse")
        dam = (node_at(tree, "Dam") or {}).get("Horse")
        gs = (node_at(tree, "Sire.Sire") or {}).get("Horse")
        if not names_compat(sire, case["expect_sire"]):
            failures.append(f"{case['label']} sire: got {sire!r} expected {case['expect_sire']}")
        if not names_compat(dam, case["expect_dam"]):
            failures.append(f"{case['label']} dam: got {dam!r} expected {case['expect_dam']}")
        if not names_compat(gs, case["expect_grandsire"]):
            failures.append(
                f"{case['label']} grandsire: got {gs!r} expected {case['expect_grandsire']}"
            )
        db_key = case.get("db_key")
        if db_key:
            db_tree = db_map.get(db_key) or db_map.get(clean_horse_name(db_key))
            if not db_tree:
                failures.append(f"{case['label']}: not in pedigree DB as {db_key}")
            else:
                failures.extend(smoke_compare_db(tree, db_tree, case["label"]))
        if not any(case["label"] in f for f in failures):
            passes.append(case["label"])

    print("SMOKE PASSES:", ", ".join(passes) or "(none)")
    if failures:
        print("SMOKE FAIL")
        for e in failures:
            print(" ", e)
        return 1
    print("SMOKE PASS")
    return 0


def resolve_horse(
    name: str,
    year: str,
    country: str,
    limiter: RateLimiter,
    allow_live: bool,
    allow_wayback: bool,
    use_cache: bool = True,
) -> dict:
    slug = horse_slug(name)
    matches = []
    last_reason = "404"
    consecutive_misses = 0
    for n in range(1, HOMONYM_MAX + 1):
        url = horse_url(slug_with_suffix(slug, n))
        result = fetch_url(
            url,
            limiter=limiter,
            use_cache=use_cache,
            allow_live=allow_live,
            allow_wayback=allow_wayback,
        )
        if not result.get("ok"):
            last_reason = result.get("reason") or "404"
            # Canonical slug has no PQ page at all — missing, not a homonym list.
            if n == 1:
                return {"ok": False, "reason": last_reason, "detail": f"slug={slug}", "tree": None, "meta": {}}
            consecutive_misses += 1
            if consecutive_misses >= 2:
                break
            continue
        consecutive_misses = 0
        try:
            tree, meta = parse_pedigree_html(result["html"], generations=5)
        except ValueError as exc:
            last_reason = "parse error"
            return {"ok": False, "reason": "parse error", "detail": str(exc), "tree": None, "meta": {}}
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


def _prepare_queue(args, pedigree_map: dict, existing_ids: set[tuple[str, str]]) -> tuple[list[dict], str, set, set]:
    """Return (queue, label, skip_pairs, retry_404_pairs)."""
    queue_name = getattr(args, "queue", "gsw-csv") or "gsw-csv"
    retry_misses = bool(getattr(args, "retry_misses", False))
    skip_pairs: set[tuple[str, str]] = set()
    retry_404_pairs: set[tuple[str, str]] = set()
    if MISSES_PATH.is_file():
        with MISSES_PATH.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                reason = (row.get("reason") or "").strip()
                if reason not in TERMINAL_REASONS:
                    continue
                pair = (row.get("clean_key") or "", str(row.get("year") or ""))
                if retry_misses and reason == "404":
                    retry_404_pairs.add(pair)
                    continue
                skip_pairs.add(pair)

    if queue_name == "auto":
        gsw, gsw_label = load_queue_horses("gsw-csv")
        missing = [h for h in gsw if (h["clean_key"], h["year"]) not in existing_ids]
        fetchable = [
            h
            for h in missing
            if (h["clean_key"], str(h["year"])) not in skip_pairs
        ]
        if fetchable:
            return fetchable, f"{gsw_label} (auto GSW phase)", skip_pairs, retry_404_pairs
        ancestors, anc_label = load_queue_horses("ancestors")
        fetchable_anc = [
            h
            for h in ancestors
            if (h["clean_key"], str(h["year"])) not in skip_pairs
        ]
        return fetchable_anc, f"{anc_label} (auto ancestor phase)", skip_pairs, retry_404_pairs

    if queue_name == "ancestors":
        horses, label = load_queue_horses("ancestors")
        fetchable = [
            h
            for h in horses
            if (h["clean_key"], str(h["year"])) not in skip_pairs
        ]
        return fetchable, label, skip_pairs, retry_404_pairs

    horses, label = load_queue_horses(queue_name)
    missing = [h for h in horses if (h["clean_key"], h["year"]) not in existing_ids]
    fetchable = [
        h for h in missing if (h["clean_key"], str(h["year"])) not in skip_pairs
    ]
    return fetchable, label, skip_pairs, retry_404_pairs


def import_live(args) -> int:
    """Primary path: headed Chrome against live Pedigree Query."""
    from pq_scraper.ancestors import tree_is_incomplete
    from pq_scraper.fetch_live import CF_STOP_AFTER, browser_closed, launch_chrome, resolve_horse, warmup

    backup = backup_database_once()
    print(f"Backup: {backup}", flush=True)
    pedigree_map = load_pedigree_map()
    existing_ids = existing_name_years(pedigree_map, clean_horse_name)
    queue, label, skip_pairs, retry_404_pairs = _prepare_queue(args, pedigree_map, existing_ids)
    if args.offset:
        queue = queue[args.offset :]
    if args.limit and args.limit > 0:
        queue = queue[: args.limit]
    overwrite_keys: set[str] = set()
    print(
        f"{label}: {len(queue)} to-fetch "
        f"(skip_terminal={len(skip_pairs)} retry_404={len(retry_404_pairs)}) "
        f"delay={args.delay}s save_every={args.save_every}",
        flush=True,
    )
    progress = load_progress()
    progress["started_at"] = progress.get("started_at") or _now()
    progress["source"] = "live_headed_chrome"
    progress["queue"] = getattr(args, "queue", "gsw-csv")
    progress["phase"] = label
    progress["remaining"] = len(queue)
    progress["stop"] = ""
    heartbeat(progress, last_attempt="", last_error="")

    if not queue:
        print("Nothing to fetch on live Chrome.", flush=True)
        progress["phase"] = "done"
        progress["remaining"] = 0
        heartbeat(progress)
        return 0

    print("Launching headed persistent Chrome…", flush=True)
    print("Leave the Chrome window open. If you see “Just a moment…”, complete the check.", flush=True)
    pw, context, page = launch_chrome("gsw")

    def relaunch(why: str) -> None:
        nonlocal pw, context, page
        print(f"  Chrome closed ({why}); relaunching…", flush=True)
        try:
            context.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass
        pw, context, page = launch_chrome("gsw")
        warmup(page)

    added_this = 0
    missed_this = 0
    processed = 0
    cf_blocks = 0
    by_reason = dict(progress.get("by_reason") or {})
    t0 = time.time()
    last_hb = 0.0

    def persist(force: bool = False) -> None:
        if not force and added_this and added_this % args.save_every != 0:
            return
        save_pedigree_map(pedigree_map, overwrite_keys=overwrite_keys)
        existing_ids.update(existing_name_years(pedigree_map, clean_horse_name))
        progress.update(
            {
                "added": progress.get("added", 0),
                "missed": progress.get("missed", 0),
                "remaining": max(len(queue) - processed, 0),
                "cursor": processed,
                "by_reason": by_reason,
                "cf_blocks": cf_blocks,
            }
        )
        heartbeat(progress)

    try:
        ok, reason = warmup(page)
        print(f"  Chrome warmup: {reason}", flush=True)
        if browser_closed(reason):
            relaunch(reason)
            ok, reason = warmup(page)
        if not ok and reason == "blocked":
            print("STOP: Cloudflare was not cleared. Click the check and rerun.", flush=True)
            progress["stop"] = "cf_blocked"
            heartbeat(progress, last_error="cf_blocked")
            return 2
        page.wait_for_timeout(2500)

        for horse in queue:
            processed += 1
            key = horse["clean_key"]
            year = str(horse["year"] or "")
            pair = (key, year)
            progress["last_attempt"] = f"{key} ({year})"
            if time.time() - last_hb >= HEARTBEAT_SECONDS:
                heartbeat(progress)
                last_hb = time.time()
            if pair in existing_ids and getattr(args, "queue", "") != "ancestors":
                if "auto ancestor" not in label.lower():
                    continue
            use_cache = pair not in retry_404_pairs
            resolved = resolve_horse(
                page,
                horse["name"],
                horse["year"],
                horse["country"],
                delay=args.delay,
                use_cache=use_cache,
            )
            reason = (resolved.get("reason") or "").strip()
            if browser_closed(reason):
                relaunch(reason)
                resolved = resolve_horse(
                    page,
                    horse["name"],
                    horse["year"],
                    horse["country"],
                    delay=args.delay,
                    use_cache=use_cache,
                )
                reason = (resolved.get("reason") or "").strip()
            if reason == "blocked":
                cf_blocks += 1
                print(f"~ CF block {key} ({year}) #{cf_blocks}", flush=True)
                heartbeat(progress, last_error=f"cf_block {key}")
                if cf_blocks >= CF_STOP_AFTER:
                    print(
                        f"STOP: {CF_STOP_AFTER} Cloudflare blocks on live headed Chrome.",
                        flush=True,
                    )
                    progress["stop"] = "cf_blocked"
                    persist(force=True)
                    return 2
                continue
            if not resolved.get("ok"):
                if reason in RETRYABLE_REASONS or browser_closed(reason):
                    append_retry(
                        {
                            "name": horse["name"],
                            "year": horse["year"],
                            "country": horse["country"],
                            "clean_key": key,
                            "reason": reason,
                            "detail": resolved.get("detail") or "",
                        }
                    )
                    print(f"~ retry-later {key} ({year}) {reason}", flush=True)
                    continue
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
                print(f"- miss {key} ({year}) {reason}", flush=True)
                continue
            store_key = storage_key_for(key, horse["year"], pedigree_map, clean_horse_name)
            if store_key in pedigree_map and tree_is_incomplete(pedigree_map[store_key]):
                overwrite_keys.add(store_key)
            pedigree_map[store_key] = resolved["tree"]
            existing_ids.add(pair)
            added_this += 1
            progress["added"] = progress.get("added", 0) + 1
            progress["last_added"] = f"{key} ({year})"
            print(
                f"+ {key} ({year}) {resolved['tree'].get('Horse')} via {resolved.get('detail')}",
                flush=True,
            )
            if added_this % args.save_every == 0:
                persist(force=True)
                elapsed = max(time.time() - t0, 0.001)
                rate = (added_this + missed_this) / (elapsed / 60.0)
                print(f"  saved added={added_this} missed={missed_this} {rate:.1f}/min", flush=True)

        persist(force=True)
        still = max(len(queue) - added_this - missed_this, 0)
        progress["remaining"] = still
        progress["phase"] = "done" if still == 0 else label
        heartbeat(progress)
        elapsed = max(time.time() - t0, 0.001)
        rate = (added_this + missed_this) / (elapsed / 60.0)
        print(
            f"LIVE DONE added={added_this} missed={missed_this} "
            f"remaining={progress['remaining']} rate={rate:.1f}/min",
            flush=True,
        )
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted — saving…", flush=True)
        persist(force=True)
        return 0
    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


def import_batch(args) -> int:
    backup = backup_database_once()
    print(f"Backup: {backup}")

    pedigree_map = load_pedigree_map()
    existing_ids = existing_name_years(pedigree_map, clean_horse_name)
    queue_name = getattr(args, "queue", "gsw-csv") or "gsw-csv"
    placed, queue_label = load_queue_horses(queue_name)
    already = [w for w in placed if (w["clean_key"], w["year"]) in existing_ids]
    missing = [w for w in placed if (w["clean_key"], w["year"]) not in existing_ids]
    print(
        f"{queue_label}: {len(placed)}; "
        f"already in DB: {len(already)}; to-fetch: {len(missing)}"
    )

    requeued = rewrite_misses_without_rate_limits()
    print(f"Requeued rate-limited rows: {requeued}")
    homonym_requeued = rewrite_homonym_misses(pedigree_map)
    print(f"Requeued other-year homonyms: {homonym_requeued}")

    progress = load_progress()
    progress["started_at"] = progress.get("started_at") or _now()
    progress["queue"] = queue_name
    progress["skipped_already_in_db"] = len(already)
    reasons = dict(progress.get("by_reason") or {})
    if "rate limited" in reasons:
        reasons.pop("rate limited", None)
        progress["by_reason"] = reasons
    progress["by_reason"] = reasons
    retry_misses = bool(getattr(args, "retry_misses", False))
    terminal_n = 0
    skip_pairs = set()
    retry_404_pairs = set()
    if MISSES_PATH.is_file():
        with MISSES_PATH.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                reason = (row.get("reason") or "").strip()
                if reason not in TERMINAL_REASONS:
                    continue
                terminal_n += 1
                pair = (row.get("clean_key") or "", str(row.get("year") or ""))
                if retry_misses and reason == "404":
                    retry_404_pairs.add(pair)
                    continue
                skip_pairs.add(pair)
    progress["missed"] = terminal_n
    miss_keys = skip_pairs
    miss_bytes_at_start = MISSES_PATH.stat().st_size if MISSES_PATH.is_file() else 0
    print(f"Terminal miss pairs loaded: {len(miss_keys)} (from misses.csv)")
    if retry_misses:
        retry_still_missing = {
            p for p in retry_404_pairs if p not in existing_ids
        }
        print(
            f"Retrying 404 miss pairs still missing from DB: {len(retry_still_missing)} "
            f"(cache bypassed)"
        )

    retry_pairs = load_retry_keys()
    retry_set = set(retry_pairs)
    by_key = {(h["clean_key"], h["year"]): h for h in missing}
    front = [by_key[p] for p in retry_pairs if p in by_key]
    rest = [h for h in missing if (h["clean_key"], h["year"]) not in retry_set]
    queue = front + rest
    start = 0
    if args.offset:
        queue = queue[args.offset :]
        start += args.offset
    if args.limit and args.limit > 0:
        queue = queue[: args.limit]
    skip_miss_n = sum(1 for h in queue if (h["clean_key"], str(h["year"])) in miss_keys)
    will_fetch = len(queue) - skip_miss_n
    print(
        f"This run queue: {len(queue)} ({len(front)} retry-first) "
        f"skip_miss={skip_miss_n} will_fetch={will_fetch} "
        f"concurrency={args.concurrency} delay={args.delay}s"
    )

    # Probe live PQ once. Cloudflare challenge means the origin is down for us —
    # fall back to Wayback at the same high throughput rather than recording 30k misses.
    if not args.wayback_only and not args.wayback:
        from pq_scraper.client import horse_url as _hurl
        from pq_scraper.parser import looks_like_challenge, looks_like_pedigree_page

        probe = fetch_url(
            "https://www.pedigreequery.com/frammento",
            limiter=RateLimiter(0.1),
            use_cache=False,
            allow_live=True,
            allow_wayback=False,
        )
        html = probe.get("html") or ""
        if looks_like_pedigree_page(html) and not looks_like_challenge(html):
            print("Live Pedigree Query: OK")
        else:
            print("Live Pedigree Query: Cloudflare-blocked; skipping live, using Wayback with 1s backoff")
            args.wayback = True
            args.wayback_only = True

    from pq_scraper.client import WAYBACK_CIRCUIT, wayback_paused

    paused, until = wayback_paused()
    if (args.wayback or args.wayback_only) and paused:
        print(f"Wayback is paused until {until}. Not starting an IA grind.", flush=True)
        heartbeat(progress, last_error=f"wayback paused until {until}", source="wayback")
        return 0
    if not WAYBACK_CIRCUIT.allow():
        print(
            f"Wayback circuit is open for {WAYBACK_CIRCUIT.blocked_for():.0f}s. "
            "Not starting an IA grind.",
            flush=True,
        )
        heartbeat(progress, last_error="wayback circuit open", source="wayback")
        return 0

    limiter = RateLimiter(args.delay)
    save_lock = threading.Lock()
    added_this = 0
    missed_this = 0
    processed = 0
    last_hb = 0.0
    by_reason = dict(progress.get("by_reason") or {})

    def bump_reason(reason: str) -> None:
        by_reason[reason] = by_reason.get(reason, 0) + 1

    def persist(force: bool = False) -> None:
        if not force and added_this and added_this % args.save_every != 0:
            return
        save_pedigree_map(pedigree_map)
        existing_ids.update(existing_name_years(pedigree_map, clean_horse_name))
        remaining = max(len(missing) - (start + processed), 0)
        progress.update(
            {
                "added": progress.get("added", 0),
                "missed": progress.get("missed", 0),
                "remaining": remaining,
                "cursor": start + processed,
                "by_reason": by_reason,
            }
        )
        save_progress(progress)

    def handle_one(horse: dict) -> dict:
        key = horse["clean_key"]
        if (key, str(horse["year"])) in existing_ids:
            return {"status": "skip_db", "horse": horse}
        if (key, str(horse["year"])) in miss_keys:
            return {"status": "skip_miss", "horse": horse}
        resolved = resolve_horse(
            horse["name"],
            horse["year"],
            horse["country"],
            limiter,
            allow_live=not args.wayback_only,
            allow_wayback=args.wayback,
            use_cache=(key, str(horse["year"])) not in retry_404_pairs,
        )
        return {"status": "ok" if resolved["ok"] else "miss", "horse": horse, "resolved": resolved}

    def apply_result(result: dict) -> None:
        nonlocal added_this, missed_this, processed, last_hb
        processed += 1
        horse = result["horse"]
        key = horse["clean_key"]
        progress["last_attempt"] = f"{key} ({horse['year']})"
        if time.time() - last_hb >= HEARTBEAT_SECONDS:
            heartbeat(progress)
            last_hb = time.time()
        if result["status"] in ("skip_db", "skip_miss"):
            return
        resolved = result["resolved"]
        reason = (resolved.get("reason") or "").strip()
        retryable = reason in RETRYABLE_REASONS
        if not resolved["ok"]:
            row = {
                "name": horse["name"],
                "year": horse["year"],
                "country": horse["country"],
                "clean_key": key,
                "reason": reason or "404",
                "detail": resolved.get("detail") or "",
            }
            if retryable:
                append_retry(row)
                print(f"~ retry-later {key} ({horse['year']}) {reason}")
                return
            missed_this += 1
            progress["missed"] = progress.get("missed", 0) + 1
            bump_reason(reason or "404")
            append_miss(row)
            miss_keys.add((key, horse["year"]))
            return
        if (key, str(horse["year"])) in existing_ids:
            return
        store_key = storage_key_for(key, horse["year"], pedigree_map, clean_horse_name)
        pedigree_map[store_key] = resolved["tree"]
        existing_ids.add((key, str(horse["year"])))
        added_this += 1
        progress["added"] = progress.get("added", 0) + 1
        progress["last_added"] = f"{key} ({horse['year']})"
        print(
            f"+ {key} ({horse['year']}) "
            f"{resolved['tree'].get('Horse')} via {resolved.get('detail')}"
        )
        if added_this % args.save_every == 0:
            persist(force=True)
            elapsed = max(time.time() - t0, 0.001)
            rate = (added_this + missed_this) / (elapsed / 60.0)
            print(
                f"  saved ({len(pedigree_map)} keys, added this run {added_this}, "
                f"terminal-miss {missed_this}, {rate:.0f}/min)"
            )

    workers = 1 if args.wayback or args.wayback_only else max(1, min(args.concurrency, 8))
    t0 = time.time()
    CHUNK = 60
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i in range(0, len(queue), CHUNK):
                raw = queue[i : i + CHUNK]
                chunk = [
                    h
                    for h in raw
                    if (h["clean_key"], str(h["year"])) not in existing_ids
                    and (h["clean_key"], str(h["year"])) not in miss_keys
                ]
                processed += len(raw) - len(chunk)
                if not chunk:
                    continue
                futs = [pool.submit(handle_one, h) for h in chunk]
                for fut in as_completed(futs):
                    with save_lock:
                        apply_result(fut.result())
                elapsed_now = max(time.time() - t0, 0.001)
                if elapsed_now < 25 and missed_this >= 80:
                    print(
                        "ABORT: too many instant 404s "
                        f"(added={added_this} missed={missed_this} in {elapsed_now:.1f}s). "
                        "Likely no network or bad cache — not writing this as real misses.",
                        flush=True,
                    )
                    if MISSES_PATH.is_file():
                        with MISSES_PATH.open("r+b") as mf:
                            mf.truncate(miss_bytes_at_start)
                    raise SystemExit(3)
    except KeyboardInterrupt:
        print("\nInterrupted — saving...")
    persist(force=True)
    still = [w for w in missing if (w["clean_key"], w["year"]) not in existing_ids]
    elapsed = max(time.time() - t0, 0.001)
    rate = (added_this + missed_this) / (elapsed / 60.0)
    progress["remaining"] = len(still)
    progress["cursor"] = start + processed
    progress["horses_per_minute"] = round(rate, 1)
    save_progress(progress)
    print(
        f"Done. added={added_this} missed={missed_this} "
        f"skipped_already_in_db={len(already)} remaining={len(still)} "
        f"db_keys={len(pedigree_map)} "
        f"rate={rate:.1f} horses/min ({elapsed:.0f}s)"
    )
    print(f"Miss reasons: {by_reason}")
    print(
        "Resume with: python3 pq_scraper/fetch_pedigrees.py --resume "
        "--retry-misses --queue auto --source live"
    )
    return 0


def seed_cache_from_fixtures() -> None:
    mapping = {
        "frammento.html": "https://www.pedigreequery.com/frammento",
        "american_pharoah.html": "https://www.pedigreequery.com/american+pharoah",
        "winx.html": "https://www.pedigreequery.com/winx",
        "flightline.html": "https://www.pedigreequery.com/flightline",
    }
    for fname, url in mapping.items():
        path = FIXTURES / fname
        if path.is_file():
            write_cache(url, path.read_text(encoding="utf-8", errors="replace"), {"source": "fixture"})


def main() -> int:
    p = argparse.ArgumentParser(description="Import PQ 5-generation pedigrees for GSW winners")
    p.add_argument("--smoke", action="store_true", help="Parser smoke-test vs fixtures/DB")
    p.add_argument("--limit", type=int, default=0, help="Max new horses to attempt this run")
    p.add_argument("--offset", type=int, default=0, help="Skip this many missing horses first")
    p.add_argument("--resume", action="store_true", help="Continue from progress.json / skip prior misses")
    p.add_argument(
        "--retry-misses",
        action="store_true",
        help="Retry 404 rows in misses.csv that are still missing from the DB (bypass URL cache)",
    )
    p.add_argument(
        "--queue",
        choices=("auto", "gsw-csv", "placed_123", "ancestors"),
        default="auto",
        help="auto = GSW horses then incomplete ancestors",
    )
    p.add_argument(
        "--source",
        choices=("live", "wayback"),
        default="live",
        help="live = headed Chrome (default); wayback = polite IA fallback",
    )
    p.add_argument("--save-every", type=int, default=10, help="Incremental DB save interval")
    p.add_argument("--delay", type=float, default=1.5, help="Seconds between network fetches")
    p.add_argument("--concurrency", type=int, default=1, help="Parallel fetches (Wayback max 1)")
    p.add_argument("--wayback-only", action="store_true", help="Force Wayback source")
    p.add_argument("--wayback", action="store_true", help="Enable Wayback (paused until cooldown file expires)")
    p.add_argument("--live-only", action="store_true", help="Deprecated: live is the default")
    p.add_argument("--skip-smoke", action="store_true", help="Skip Frammento probe on live Chrome")
    p.add_argument("--seed-cache", action="store_true", help="Copy fixtures into URL cache")
    args = p.parse_args()
    if args.wayback_only:
        args.wayback = True
        args.source = "wayback"
    if args.live_only:
        args.source = "live"

    if args.seed_cache or args.smoke:
        seed_cache_from_fixtures()
    if args.smoke:
        return run_smoke(allow_network=True)
    if args.source == "live":
        if not getattr(args, "retry_misses", False):
            args.retry_misses = True
        return import_live(args)
    return import_batch(args)


if __name__ == "__main__":
    raise SystemExit(main())
