#!/usr/bin/env python3
"""Import PQ pedigrees fetched via the Cursor IDE browser (in-page fetch).

CDP cookie export is denied; the IDE tab's same-origin fetch() carries
HttpOnly Cloudflare clearance. This script:
  --dump-batch N   write the next reverse-queue URLs (Z→A)
  --import FILE    parse extracted JSON and flock-save every 25 new keys
"""

from __future__ import annotations

import argparse
import json
import re
import sys
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
from pq_scraper.fetch_live import (  # noqa: E402
    MISSES_PATH,
    PROGRESS_PATH,
    SESSION_PATH,
    TERMINAL_REASONS,
    append_miss,
    existing_identity_set,
    load_live_miss_keys,
    load_progress,
    load_session_added,
    persist_new,
    reverse_missing,
    save_progress,
    save_session_added,
)
from pq_scraper.parser import parse_pedigree_html  # noqa: E402

SCRAPER_DIR = Path(__file__).resolve().parent
BATCH_PATH = SCRAPER_DIR / "ide_batch.json"
FOLLOWUP_PATH = SCRAPER_DIR / "ide_followup.json"


_TAG_RE = re.compile(r"<[^>]+>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _clean_blob(blob: str) -> str:
    text = (blob or "").split("<!--", 1)[0]
    text = _TAG_RE.sub(" ", text)
    return " ".join(text.split())


def reconstruct_html(extracted: dict) -> str:
    if extracted.get("challenge"):
        return "<html><title>Just a moment</title>cloudflare cf-mitigated</html>"
    if extracted.get("notfound") and not extracted.get("pedigree"):
        return "<html>no matching horses</html>"
    subj = extracted.get("subject") or {}
    name = subj.get("name") or "UNKNOWN"
    blob = _clean_blob(subj.get("blob") or "")
    parts = [f'<b><a class="nounderline">{name}</a></b> {blob}']
    for cell in extracted.get("cells") or []:
        cls = cell.get("class") or cell.get("c") or "m"
        rs = int(cell.get("rowspan") or cell.get("r") or 0)
        rs_attr = f" rowspan={rs}" if rs else ""
        hrefs = "".join(f'<a href="{h}">x</a>' for h in (cell.get("hrefs") or []))
        text = cell.get("text") or cell.get("t") or ""
        parts.append(f'<td class="{cls}"{rs_attr}>{hrefs}{text}</td>')
    return "".join(parts)


def parse_extracted(extracted: dict) -> tuple[dict | None, dict, str]:
    if extracted.get("challenge") or extracted.get("stop") in {"cf", "error"}:
        return None, {}, "blocked"
    if int(extracted.get("status") or 0) in {429, 403}:
        return None, {}, "429"
    html = reconstruct_html(extracted)
    try:
        tree, meta = parse_pedigree_html(html, generations=5)
    except ValueError as exc:
        reason = str(exc)
        if reason == "not found":
            reason = "404"
        elif reason in {"no ancestor cells", "not a pedigree page"}:
            reason = "parse error"
        return None, {}, reason
    return tree, meta, ""


def dump_batch(limit: int, include_followups: bool = True) -> dict:
    existing = existing_identity_set()
    session = load_session_added()
    existing |= existing_name_years(session, clean_horse_name)
    miss_keys = load_live_miss_keys()
    followups = []
    if include_followups and FOLLOWUP_PATH.is_file():
        try:
            followups = json.loads(FOLLOWUP_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            followups = []
    follow_keys = {f.get("clean_key") for f in followups}
    missing = reverse_missing(existing)
    queue = []
    for horse in missing:
        key = horse["clean_key"]
        if (key, horse["year"]) in existing or key in follow_keys:
            continue
        if (key, horse["year"]) in miss_keys:
            continue
        queue.append(horse)
        if len(queue) >= limit:
            break
    items = []
    for horse in queue:
        slug = horse_slug(horse["name"])
        items.append(
            {
                "clean_key": horse["clean_key"],
                "name": horse["name"],
                "year": horse["year"],
                "country": horse["country"],
                "slug": slug,
                "n": 1,
                "url": horse_url(slug),
            }
        )
    items = [it for it in items if it["clean_key"] not in follow_keys]
    leftover_followups = followups[3:]
    followups = followups[:3]
    payload = {"items": followups + items, "remaining_est": len(missing)}
    BATCH_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    FOLLOWUP_PATH.write_text(json.dumps(leftover_followups, indent=2), encoding="utf-8")
    return payload


def _next_suffix_item(item: dict, reason: str) -> dict | None:
    if reason == "429":
        nxt = dict(item)
        nxt["prev_reason"] = "429"
        slug = slug_with_suffix(horse_slug(item["name"]), int(item.get("n") or 1))
        nxt["slug"] = slug
        nxt["url"] = horse_url(slug)
        return nxt
    n = int(item.get("n") or 1) + 1
    if n > HOMONYM_MAX:
        return None
    if reason not in {"year mismatch", "year/country mismatch", "404"} and n > 2:
        return None
    slug = slug_with_suffix(horse_slug(item["name"]), n)
    nxt = dict(item)
    nxt["n"] = n
    nxt["slug"] = slug
    nxt["url"] = horse_url(slug)
    nxt["prev_reason"] = reason
    return nxt


def import_extracted(path: Path, save_every: int = 25) -> dict:
    backup_database_once()
    raw = json.loads(path.read_text(encoding="utf-8"))
    results = raw if isinstance(raw, list) else raw.get("results") or raw.get("items") or []
    session_added = load_session_added()
    progress = load_progress()
    progress["source"] = "ide_browser_inpage_fetch"
    progress["queue"] = "placed_123_reverse"
    existing = existing_identity_set()
    miss_keys = load_live_miss_keys()
    by_reason = dict(progress.get("by_reason") or {})
    last_names = list(progress.get("last_names") or [])
    added = 0
    missed = 0
    skipped = 0
    blocked = 0
    followups: list[dict] = []
    pending_matches: dict[str, list] = {}

    # First pass: parse every fetched URL
    parsed_rows = []
    for extracted in results:
        horse = extracted.get("horse") or {}
        key = horse.get("clean_key") or extracted.get("clean_key") or ""
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
                    "detail": f"ide n<={max_n}",
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

        # If we only fetched n=1 and it matched, good. If n=1 matched year, no need
        # for more suffixes. If we still have unused suffix slots and only one fetch
        # that didn't uniquely confirm... already handled.
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
    merged = held + followups
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
    }
    print("IMPORT", json.dumps(summary), flush=True)
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description="IDE-browser PQ reverse-queue importer")
    p.add_argument("--dump-batch", type=int, default=0, help="Write next N reverse-queue URLs")
    p.add_argument("--import-file", type=str, default="", help="Extracted JSON from IDE fetch")
    p.add_argument("--save-every", type=int, default=25)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()

    if args.self_test:
        fixture = Path(__file__).resolve().parent / "cache_ide" / "frammento.html"
        html = fixture.read_text(encoding="utf-8")
        tree, meta = parse_pedigree_html(html, generations=5)
        assert tree["Horse"].startswith("FRAMMENTO"), tree
        assert meta.get("year") == "2012", meta
        print("SELF-TEST PASS", tree["Horse"], meta.get("country"))
        return 0

    if args.dump_batch:
        payload = dump_batch(args.dump_batch)
        print(
            f"DUMP n={len(payload['items'])} remaining_est={payload['remaining_est']} "
            f"first={payload['items'][0]['clean_key'] if payload['items'] else '—'}",
            flush=True,
        )
        return 0

    if args.import_file:
        import_extracted(Path(args.import_file), save_every=args.save_every)
        return 0

    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
