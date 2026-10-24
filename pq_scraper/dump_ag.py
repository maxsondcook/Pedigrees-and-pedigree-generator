#!/usr/bin/env python3
"""Dump / import A–G Pedigree Query keys for the IDE live importer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pq_scraper.client import HOMONYM_MAX, countries_compatible, horse_slug, horse_url, years_match
from main import clean_horse_name
from pq_scraper.dbio import backup_database_once, existing_name_years, load_pedigree_map, storage_key_for
from pq_scraper.fetch_ide import _next_suffix_item, parse_extracted
from pq_scraper.fetch_live import (
    append_miss,
    existing_identity_set,
    load_live_miss_keys,
    load_progress,
    load_session_added,
    persist_new,
)
from pq_scraper.fetch_pedigrees import unique_placed

SCRAPER_DIR = Path(__file__).resolve().parent
BATCH_PATH = SCRAPER_DIR / "ide_ag_batch.json"
FOLLOWUP_PATH = SCRAPER_DIR / "ide_ag_followup.json"
LETTERS = tuple("ABCDEFG")


def _letter_ok(key: str) -> bool:
    k = (key or "").strip().upper()
    return bool(k) and k[0] in LETTERS


def missing_ag(existing=None) -> list[dict]:
    existing = existing if existing is not None else existing_identity_set()
    session = load_session_added()
    existing = set(existing) | existing_name_years(session, clean_horse_name)
    miss_keys = load_live_miss_keys()
    followups = []
    if FOLLOWUP_PATH.is_file():
        try:
            followups = json.loads(FOLLOWUP_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            followups = []
    follow_keys = {f.get("clean_key") for f in followups}
    missing = []
    for horse in unique_placed():
        key = horse["clean_key"]
        if not _letter_ok(key):
            continue
        if (key, horse["year"]) in existing or key in follow_keys:
            continue
        if (key, horse["year"]) in miss_keys:
            continue
        missing.append(horse)
    missing.sort(key=lambda h: (h["clean_key"], h["year"]))
    return missing


def dump_batch(limit: int) -> dict:
    existing = existing_identity_set()
    session = load_session_added()
    existing |= existing_name_years(session, clean_horse_name)
    followups = []
    if FOLLOWUP_PATH.is_file():
        try:
            followups = json.loads(FOLLOWUP_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            followups = []
    follow_keys = {f.get("clean_key") for f in followups}
    queue = []
    all_missing = missing_ag(existing)
    for horse in all_missing:
        key = horse["clean_key"]
        if key in follow_keys:
            continue
        slug = horse_slug(horse["name"])
        queue.append(
            {
                "clean_key": key,
                "name": horse["name"],
                "year": horse["year"],
                "country": horse["country"],
                "slug": slug,
                "n": 1,
                "url": horse_url(slug),
            }
        )
        if len(queue) >= limit:
            break
    leftover = followups[limit:]
    take_follow = followups[:limit]
    remaining_slots = max(0, limit - len(take_follow))
    items = take_follow + queue[:remaining_slots]
    FOLLOWUP_PATH.write_text(json.dumps(leftover, indent=2), encoding="utf-8")
    payload = {
        "items": items,
        "remaining_est": len(all_missing) + len(followups),
        "slice": "A-G",
    }
    BATCH_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def import_extracted(path: Path, save_every: int = 25) -> dict:
    backup_database_once()
    raw = json.loads(path.read_text(encoding="utf-8"))
    results = raw if isinstance(raw, list) else raw.get("results") or raw.get("items") or []
    session_added = load_session_added()
    progress = load_progress()
    progress["source"] = "ide_browser_inpage_fetch_ag"
    progress["queue"] = "placed_123_ag"
    existing = existing_identity_set()
    miss_keys = load_live_miss_keys()
    by_reason = dict(progress.get("by_reason") or {})
    last_names = list(progress.get("last_names") or [])
    added = 0
    missed = 0
    skipped = 0
    blocked = 0
    followups: list[dict] = []

    parsed_rows = []
    for extracted in results:
        horse = extracted.get("horse") or {}
        key = horse.get("clean_key") or extracted.get("clean_key") or ""
        if not _letter_ok(key):
            skipped += 1
            continue
        year = str(horse.get("year") or extracted.get("year") or "")
        country = horse.get("country") or extracted.get("country") or ""
        name = horse.get("name") or extracted.get("name") or key
        n = int(horse.get("n") or extracted.get("n") or 1)
        url = extracted.get("url") or ""
        parsed_rows.append(
            {
                "key": key,
                "year": year,
                "country": country,
                "name": name,
                "n": n,
                "url": url,
                "extracted": extracted,
            }
        )

    grouped: dict[str, list] = {}
    for row in parsed_rows:
        grouped.setdefault(row["key"], []).append(row)

    for key, rows in grouped.items():
        if not key:
            continue
        year = rows[0]["year"]
        if (key, year) in existing or (key, year) in existing_name_years(session_added, clean_horse_name):
            skipped += 1
            continue
        country = rows[0]["country"]
        name = rows[0]["name"]
        if (key, year) in miss_keys:
            skipped += 1
            continue

        matches = []
        last_reason = "404"
        saw_block = False
        max_n = max(r["n"] for r in rows)
        for row in sorted(rows, key=lambda r: r["n"]):
            extracted = row["extracted"]
            tree, meta, err = parse_extracted(extracted)
            if extracted.get("challenge") or err == "blocked" or err == "cloudflare challenge":
                last_reason = "blocked"
                saw_block = True
                break
            if tree is None:
                last_reason = err or "404"
                continue
            pq_year = meta.get("year")
            pq_country = meta.get("country")
            if year and pq_year and not years_match(pq_year, year):
                last_reason = "year mismatch"
                continue
            if not countries_compatible(pq_country, country):
                last_reason = "year mismatch"
                continue
            matches.append({"tree": tree, "meta": meta, "url": row["url"]})
            if row["n"] == 1 and year and pq_year and years_match(pq_year, year):
                break

        if saw_block:
            blocked += 1
            progress["cf_blocks"] = progress.get("cf_blocks", 0) + 1
            print(f"~ CF block {key} ({year})", flush=True)
            continue

        if not matches:
            want_retry = (
                last_reason == "429"
                or (last_reason == "year mismatch" and max_n < HOMONYM_MAX)
                or (last_reason == "404" and max_n >= 2 and max_n < HOMONYM_MAX)
            )
            if want_retry:
                nxt = _next_suffix_item(
                    {"clean_key": key, "name": name, "year": year, "country": country, "n": max_n},
                    last_reason,
                )
                if nxt:
                    followups.append(nxt)
                    print(f"? retry {key} ({year}) {nxt['url']}", flush=True)
                    continue
            missed += 1
            progress["missed"] = progress.get("missed", 0) + 1
            by_reason[last_reason or "404"] = by_reason.get(last_reason or "404", 0) + 1
            append_miss(
                {
                    "name": name,
                    "year": year,
                    "country": country,
                    "clean_key": key,
                    "reason": last_reason or "404",
                    "detail": f"ide_ag n<={max_n}",
                }
            )
            miss_keys.add((key, year))
            print(f"- miss {key} ({year}) {last_reason}", flush=True)
            continue

        if len(matches) > 1:
            missed += 1
            progress["missed"] = progress.get("missed", 0) + 1
            by_reason["ambiguous"] = by_reason.get("ambiguous", 0) + 1
            append_miss(
                {
                    "name": name,
                    "year": year,
                    "country": country,
                    "clean_key": key,
                    "reason": "ambiguous",
                    "detail": f"{len(matches)} PQ horses matched year/country",
                }
            )
            miss_keys.add((key, year))
            print(f"- miss {key} ({year}) ambiguous", flush=True)
            continue

        existing = existing_identity_set()
        if (key, year) in existing:
            skipped += 1
            continue
        store_key = storage_key_for(key, year, {**load_pedigree_map(), **session_added}, clean_horse_name)
        session_added[store_key] = matches[0]["tree"]
        existing.add((key, year))
        added += 1
        progress["added"] = progress.get("added", 0) + 1
        label = f"{key} ({year})"
        progress["last_added"] = label
        last_names.append(label)
        print(f"+ {label} {matches[0]['tree'].get('Horse')}", flush=True)
        if added % save_every == 0:
            progress.update({"by_reason": by_reason, "last_names": last_names[-12:]})
            persist_new(session_added, progress)
            print(f"  saved added_this={added} session_keys={len(session_added)}", flush=True)

    progress.update({"by_reason": by_reason, "last_names": last_names[-12:]})
    persist_new(session_added, progress)
    held = []
    if FOLLOWUP_PATH.is_file():
        try:
            held = json.loads(FOLLOWUP_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            held = []
    imported_keys = {row["key"] for row in parsed_rows}
    held = [h for h in held if h.get("clean_key") not in imported_keys]
    merged = followups + held
    seen_f = set()
    uniq = []
    for item in merged:
        k = (item.get("clean_key"), item.get("n"), item.get("url"))
        if k in seen_f:
            continue
        seen_f.add(k)
        uniq.append(item)
    FOLLOWUP_PATH.write_text(json.dumps(uniq, indent=2), encoding="utf-8")
    summary = {
        "added": added,
        "missed": missed,
        "skipped": skipped,
        "blocked": blocked,
        "followups": len(followups),
        "session_keys": len(session_added),
        "last_added": progress.get("last_added"),
        "last_names": last_names[-12:],
    }
    print("IMPORT", json.dumps(summary), flush=True)
    return summary


def count_remaining() -> dict:
    existing = existing_identity_set() | existing_name_years(load_session_added(), clean_horse_name)
    miss_keys = load_live_miss_keys()
    total = 0
    remaining = 0
    by_letter = {ch: 0 for ch in LETTERS}
    for horse in unique_placed():
        key = horse["clean_key"]
        if not _letter_ok(key):
            continue
        total += 1
        if (key, horse["year"]) in existing:
            continue
        if (key, horse["year"]) in miss_keys:
            continue
        remaining += 1
        by_letter[key[0]] += 1
    return {"slice_total": total, "remaining": remaining, "by_letter": by_letter}


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dump-batch", type=int, default=0)
    p.add_argument("--import-file", type=str, default="")
    p.add_argument("--count", action="store_true")
    p.add_argument("--save-every", type=int, default=25)
    args = p.parse_args()
    if args.count:
        print(json.dumps(count_remaining(), indent=2))
    elif args.dump_batch:
        payload = dump_batch(args.dump_batch)
        print(
            f"DUMP n={len(payload['items'])} remaining_est={payload['remaining_est']} "
            f"first={payload['items'][0]['clean_key'] if payload['items'] else '—'}",
            flush=True,
        )
    elif args.import_file:
        import_extracted(Path(args.import_file), save_every=args.save_every)
    else:
        p.print_help()
        raise SystemExit(2)
