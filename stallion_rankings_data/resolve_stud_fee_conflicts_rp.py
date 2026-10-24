#!/usr/bin/env python3
"""Resolve conflicting stud fees via Racing Post fee-history pages.

Also treats Private as a real stud fee (not N/A) in the existing CSV.
"""

from __future__ import annotations

import csv
import json
import random
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path("/Users/maxsoncook/Desktop/stallion_rankings_data")
sys.path.insert(0, str(ROOT))
from build_stud_fee_database import (  # noqa: E402
    COLUMNS,
    NA,
    display_or_na,
    farm_score,
    merge_notes,
    stallion_key,
)

OUT_CSV = ROOT / "stud_fee_database.csv"
OUT_README = ROOT / "stud_fee_database_README.txt"
OUT_MISSES = ROOT / "stud_fee_rp_misses.csv"
CACHE_DIR = ROOT / "rp_cache"
HTML_DIR = CACHE_DIR / "html"
URL_MAP = CACHE_DIR / "stallion_urls.json"
FEE_TABLES = CACHE_DIR / "rp_fee_tables.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}

CURRENCY = {
    "USD": lambda n: f"${n:,}",
    "CAD": lambda n: f"${n:,} (CAN)",
    "GBP": lambda n: f"{n:,} (Pounds)",
    "EUR": lambda n: f"{n:,} (Euros)",
}

CONFLICT_RE = re.compile(r"Conflict:\s*different stud fees for same stallion-year(?:\s*\([^)]*\))?", re.I)
UNRESOLVED_RE = re.compile(r"Unresolved:\s*no RP fee", re.I)
YEAR_NM_RE = re.compile(r"RP year-not-matched:[^;]*", re.I)
RESOLVED_RE = re.compile(r"Resolved via Racing Post:[^;]*", re.I)


def strip_resolution_notes(notes: str) -> str:
    text = notes or ""
    for rx in (CONFLICT_RE, UNRESOLVED_RE, YEAR_NM_RE, RESOLVED_RE):
        text = rx.sub("", text)
    return merge_notes(text)


def load_rows() -> list[dict]:
    with OUT_CSV.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: (r["Year"], r["Stallion"].casefold(), r["Stud Fee"], r["Source List"]))
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fix_private_rows(rows: list[dict]) -> int:
    """Move source 'Private' from Notes into Stud Fee."""
    changed = 0
    for row in rows:
        notes = [p.strip() for p in re.split(r"\s*;\s*", row.get("Notes") or "") if p.strip()]
        private_bits = [n for n in notes if re.fullmatch(r"private(?:\s+fee)?", n, re.I)]
        if not private_bits:
            continue
        if row["Stud Fee"] in {NA, "", "N/A"} or re.fullmatch(r"private(?:\s+fee)?", row["Stud Fee"], re.I):
            row["Stud Fee"] = "Private"
            leftover = [n for n in notes if n not in private_bits]
            row["Notes"] = "; ".join(leftover)
            changed += 1
    return changed


def name_key(name: str) -> str:
    key = stallion_key(name)
    key = re.sub(r"\b(ire|usa|gb|fr|can|jpn|aus|nz|ger|ity|saf)\b", "", key)
    return re.sub(r"\s+", " ", key).strip()


def names_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    ka, kb = name_key(a), name_key(b)
    if ka == kb:
        return True
    return ka.replace(" ", "") == kb.replace(" ", "")


def format_rp_fee(entry: dict) -> str | None:
    if entry.get("isPrivate") or str(entry.get("studFee") or "").casefold() == "private":
        return "Private"
    amount = entry.get("studFee")
    if amount in (None, "", NA):
        return None
    cur = (entry.get("currencyCode") or "USD").upper()
    try:
        number = int(str(amount).replace(",", "").replace(" ", ""))
    except ValueError:
        text = str(amount).strip()
        return "Private" if text.casefold() == "private" else text
    fmt = CURRENCY.get(cur)
    if fmt:
        return fmt(number)
    return f"{number:,} ({cur})"


def cache_path(url: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", url.lower()).strip("_")
    return HTML_DIR / f"{slug}.html"


COOKIE_JAR = CACHE_DIR / "rp_cookies.txt"


def _curl(url: str, extra: list[str] | None = None) -> tuple[int, str]:
    cmd = [
        "curl", "-sS", "--compressed", "-w", "\n%{http_code}",
        "-A", HEADERS["User-Agent"],
        "-H", f"Accept: {HEADERS['Accept']}",
        "-H", f"Accept-Language: {HEADERS['Accept-Language']}",
        "-H", "Upgrade-Insecure-Requests: 1",
        "-c", str(COOKIE_JAR),
        "-b", str(COOKIE_JAR),
        "--max-time", "45",
    ]
    if extra:
        cmd.extend(extra)
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    body = proc.stdout or ""
    if "\n" not in body:
        return 0, body
    text, _, code = body.rpartition("\n")
    try:
        return int(code.strip() or "0"), text
    except ValueError:
        return 0, body


def warmup_rp() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _curl("https://www.racingpost.com/", extra=["-H", "Referer: https://www.racingpost.com/"])
    time.sleep(1.2)


def fetch_html(url: str) -> tuple[str | None, str]:
    path = cache_path(url)
    if path.exists() and path.stat().st_size > 2000:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "Sorry, our website is currently not available" not in text and "__NEXT_DATA__" in text:
            return text, "cache"
    time.sleep(random.uniform(0.7, 1.1))
    extra = ["-H", "Referer: https://www.racingpost.com/"]
    code, text = _curl(url, extra=extra)
    if code == 200 and "__NEXT_DATA__" in text and "Sorry, our website is currently not available" not in text:
        path.write_text(text, encoding="utf-8")
        return text, "fetched"
    return None, f"http-{code}" if code else "blocked-or-empty"


def load_fee_tables() -> dict[str, dict]:
    if not FEE_TABLES.exists():
        return {}
    raw = json.loads(FEE_TABLES.read_text(encoding="utf-8"))
    out = {}
    for name, payload in raw.items():
        if name.startswith("_") or not isinstance(payload, dict):
            continue
        out[name_key(name)] = payload
    return out


def format_table_fee(entry: dict) -> str | None:
    if entry.get("private") or entry.get("isPrivate"):
        return "Private"
    fake = {
        "isPrivate": False,
        "studFee": entry.get("fee"),
        "currencyCode": entry.get("currency") or "USD",
    }
    return format_rp_fee(fake)


def parse_fee_history(html: str) -> tuple[str, list[dict]]:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return "", []
    data = json.loads(script.string)
    profile = data.get("props", {}).get("pageProps", {}).get("initialState", {}).get("horseProfile", {})
    overview = ((profile.get("overview") or {}).get("data") or {})
    horse_name = overview.get("horseName") or ""
    rows = ((profile.get("feeHistory") or {}).get("data") or []) or []
    return horse_name, rows


def best_farm(items: list[dict]) -> str:
    best = items[0]["Farm"]
    for item in items[1:]:
        if farm_score(item["Farm"]) > farm_score(best):
            best = item["Farm"]
    return display_or_na(best)


def load_url_map() -> dict[str, str]:
    if not URL_MAP.exists():
        return {}
    raw = json.loads(URL_MAP.read_text(encoding="utf-8"))
    return {name_key(k): v for k, v in raw.items()}


def update_readme(rows: list[dict], resolved: int, unresolved: int, year_not_matched: int) -> None:
    text = OUT_README.read_text(encoding="utf-8")
    years = sorted({r["Year"] for r in rows})
    unique_sy = len({(r["Year"], stallion_key(r["Stallion"])) for r in rows})
    na_fees = sum(1 for r in rows if r["Stud Fee"] == NA)
    private_fees = sum(1 for r in rows if r["Stud Fee"].casefold() == "private")
    conflict_rows = sum(1 for r in rows if "Conflict:" in (r.get("Notes") or ""))
    conflict_groups = len(
        {(r["Year"], stallion_key(r["Stallion"])) for r in rows if "Conflict:" in (r.get("Notes") or "")}
    )
    counts = f"""Counts
------
  Output rows:              {len(rows):,}
  Unique stallion-years:    {unique_sy:,}
  Years covered:            {years[0]}–{years[-1]} ({len(years)} years)
  N/A stud fees:            {na_fees:,}
  Private stud fees:        {private_fees:,}
  Conflict groups:          {conflict_groups:,}  (same stallion+year, different fees)
  Conflict rows:            {conflict_rows:,}
  Conflicts resolved (RP):  {resolved:,}
  Unresolved (no RP fee):   {unresolved:,}
  RP year-not-matched:      {year_not_matched:,}"""
    text = re.sub(r"Counts\n------\n(?:  .+\n)+", counts + "\n", text, count=1)
    old_private = (
        "  Private / Pensioned / Retired / To Be Announced  ->  fee N/A, status in Notes,\n"
        "  farm kept when a farm/state remained."
    )
    new_private = (
        "  Private / private fee       ->  Stud Fee=Private, farm kept when present\n"
        "  Pensioned / Retired / To Be Announced  ->  fee N/A, status in Notes,\n"
        "  farm kept when a farm/state remained."
    )
    text = text.replace(old_private, new_private)
    note = (
        "\nFee conflicts were checked against Racing Post stallion fee-history pages.\n"
        "A year-specific RP fee collapses the two conflict rows into one. Private on\n"
        "Racing Post is stored as Stud Fee=Private. If RP has a page but no fee for\n"
        "that covering year, both rows stay and Notes say year-not-matched. If RP has\n"
        "no page or no fee at all, both rows stay tagged Unresolved: no RP fee.\n"
        "Misses: stud_fee_rp_misses.csv. HTML cache: rp_cache/html/.\n"
    )
    if "Fee conflicts were checked against Racing Post" not in text:
        text = text.replace("Missing values are N/A. Encoding is UTF-8 with BOM.\n",
                            "Missing values are N/A. Encoding is UTF-8 with BOM.\n" + note)
    OUT_README.write_text(text, encoding="utf-8")


def main() -> None:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    private_fixed = fix_private_rows(rows)

    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        if "Conflict:" in (row.get("Notes") or ""):
            groups[(row["Year"], stallion_key(row["Stallion"]))].append(i)

    url_map = load_url_map()
    fee_tables = load_fee_tables()
    warmup_rp()

    parsed_by_url: dict[str, tuple[str, list[dict], str]] = {}
    resolved = unresolved = year_not_matched = 0
    drop: set[int] = set()
    misses: list[dict] = []
    examples: list[dict] = []

    def apply_resolved(fee: str, source_url: str) -> None:
        nonlocal resolved
        keep = items[0]
        sources = []
        for it in items:
            sources.extend(s.strip() for s in it["Source List"].split(";") if s.strip())
        base_notes = merge_notes(*(strip_resolution_notes(it["Notes"]) for it in items))
        keep["Stud Fee"] = fee
        keep["Farm"] = best_farm(items)
        keep["Source List"] = "; ".join(sorted(dict.fromkeys(sources)))
        keep["Notes"] = merge_notes(base_notes, f"Resolved via Racing Post: {year} fee {fee}")
        for extra in idxs[1:]:
            drop.add(extra)
        resolved += 1
        if len(examples) < 5:
            examples.append({"stallion": stallion, "year": year, "old": old_fees, "new": fee})

    for (year, skey), idxs in groups.items():
        items = [rows[i] for i in idxs]
        stallion = items[0]["Stallion"]
        old_fees = sorted({it["Stud Fee"] for it in items})
        nkey = name_key(stallion)
        url = url_map.get(nkey) or (fee_tables.get(nkey) or {}).get("url")
        table = fee_tables.get(nkey) or {}
        table_years = {int(y): e for y, e in (table.get("years") or {}).items() if str(y).isdigit()}

        history: list[dict] = []
        horse_name = ""
        status = ""
        if url:
            need_live = not table_years
            cached = cache_path(url)
            have_cache = cached.exists() and cached.stat().st_size > 2000
            if url not in parsed_by_url:
                # Prefer cached HTML; only hit the live site if we still need a year.
                if have_cache or need_live:
                    html, status = fetch_html(url)
                    if html:
                        horse_name, history = parse_fee_history(html)
                        parsed_by_url[url] = (horse_name, history, status)
                    else:
                        parsed_by_url[url] = ("", [], status)
                else:
                    parsed_by_url[url] = ("", [], "table-fallback")
            horse_name, history, status = parsed_by_url[url]

        by_year: dict[int, dict] = {}
        for entry in history:
            ny = entry.get("nominationYear")
            if ny is None:
                continue
            by_year[int(ny)] = entry

        target = int(year)
        fee = None
        if target in by_year and (not horse_name or names_match(stallion, horse_name)):
            fee = format_rp_fee(by_year[target])
        elif target in table_years:
            fee = format_table_fee(table_years[target])

        if fee:
            apply_resolved(fee, url or "")
            continue

        known_years = sorted(set(by_year) | set(table_years))
        if known_years:
            # Page/table exists but not for this covering year — do not invent history.
            if target in by_year:
                latest_year = target
                latest_fee = format_rp_fee(by_year[target]) or "unknown"
            else:
                latest_year = max(known_years)
                if latest_year in by_year:
                    latest_fee = format_rp_fee(by_year[latest_year]) or "unknown"
                else:
                    latest_fee = format_table_fee(table_years[latest_year]) or "unknown"
            years_shown = ",".join(str(y) for y in known_years)
            note = (
                f"RP year-not-matched: page shows {latest_year} {latest_fee} "
                f"(years: {years_shown})"
            )
            for it in items:
                it["Notes"] = merge_notes(
                    strip_resolution_notes(it["Notes"]),
                    "Conflict: different stud fees for same stallion-year",
                    note,
                )
            year_not_matched += 1
            misses.append({
                "Stallion": stallion,
                "Year": year,
                "Reason": "year-not-matched",
                "URL": url or "",
                "RP_years": years_shown,
                "RP_fee": latest_fee,
                "Old_fees": "; ".join(old_fees),
            })
            continue

        unresolved += 1
        reason = "no RP page" if not url else (status or "no RP fee")
        for it in items:
            it["Notes"] = merge_notes(
                strip_resolution_notes(it["Notes"]),
                "Conflict: different stud fees for same stallion-year",
                "Unresolved: no RP fee",
            )
        misses.append({
            "Stallion": stallion,
            "Year": year,
            "Reason": reason,
            "URL": url or "",
            "RP_years": "",
            "RP_fee": "",
            "Old_fees": "; ".join(old_fees),
        })

    rows = [r for i, r in enumerate(rows) if i not in drop]
    write_csv(rows)

    with OUT_MISSES.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["Stallion", "Year", "Reason", "URL", "RP_years", "RP_fee", "Old_fees"],
        )
        writer.writeheader()
        writer.writerows(misses)

    def sy_count(needle: str) -> int:
        return len({
            (r["Year"], stallion_key(r["Stallion"]))
            for r in rows
            if needle in (r.get("Notes") or "")
        })

    resolved = sy_count("Resolved via Racing Post")
    unresolved = sy_count("Unresolved: no RP fee")
    year_not_matched = sy_count("RP year-not-matched")
    update_readme(rows, resolved, unresolved, year_not_matched)
    private_count = sum(1 for r in rows if r["Stud Fee"].casefold() == "private")
    print(f"Private rows fixed: {private_fixed}")
    print(f"Private stud fees: {private_count}")
    print(f"Conflicts resolved: {resolved}")
    print(f"Unresolved: {unresolved}")
    print(f"RP year-not-matched: {year_not_matched}")
    print(f"Output rows: {len(rows)}")
    print("Examples:")
    for ex in examples:
        print(f"  {ex['stallion']} {ex['year']}: {ex['old']} -> {ex['new']}")
    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_MISSES}")
    print(f"Wrote {OUT_README}")


if __name__ == "__main__":
    main()
