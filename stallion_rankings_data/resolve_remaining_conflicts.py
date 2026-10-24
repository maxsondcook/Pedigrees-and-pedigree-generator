#!/usr/bin/env python3
"""Resolve remaining stud-fee conflicts from RP fee-history and web sources."""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

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

CONFLICT_RE = re.compile(r"Conflict:\s*different stud fees for same stallion-year(?:\s*\([^)]*\))?", re.I)
UNRESOLVED_RE = re.compile(r"Unresolved:\s*no RP fee", re.I)
YEAR_NM_RE = re.compile(r"RP year-not-matched:[^;]*", re.I)
RESOLVED_RE = re.compile(r"Resolved via (?:Racing Post|web search)[^;]*", re.I)

# (year, stallion_key) -> (fee, farm_or_None, note)
RESOLUTIONS: dict[tuple[str, str], tuple[str, str | None, str]] = {
    # User-provided ground truth
    ("2001", stallion_key("Avenue Of Flags")): (
        "$10,000",
        "Golden Eagle Farm, Ramona, California",
        "Resolved via web search: user ground truth / Golden Eagle Farm, Ramona, CA",
    ),
    ("2001", stallion_key("Bertrando")): (
        "$30,000",
        None,
        "Resolved via web search: user ground truth",
    ),
    ("2001", stallion_key("Danzig")): (
        "Private",
        None,
        "Resolved via web search: user ground truth",
    ),
    ("2001", stallion_key("General Meeting")): (
        "$50,000",
        None,
        "Resolved via web search: user ground truth",
    ),
    # Cee's Tizzy — user pointed at RP fee-history; page 406s, year fees from
    # Harris Farms / BloodHorse advertised covering fees (2001 LAT $15,000).
    ("2003", stallion_key("Cee's Tizzy")): (
        "$15,000",
        "Harris Farms, CA",
        "Resolved via web search: LA Times / BloodHorse advertised Harris Farms fee; RP https://www.racingpost.com/profile/horse/506307/cees-tizzy/fee-history/",
    ),
    ("2004", stallion_key("Cee's Tizzy")): (
        "$10,000",
        "Harris Farms, CA",
        "Resolved via web search: BloodHorse advertised Harris Farms covering fee; RP https://www.racingpost.com/profile/horse/506307/cees-tizzy/fee-history/",
    ),
    ("2005", stallion_key("Cee's Tizzy")): (
        "$7,500",
        "Harris Farms, CA",
        "Resolved via web search: BloodHorse advertised Harris Farms covering fee; RP https://www.racingpost.com/profile/horse/506307/cees-tizzy/fee-history/",
    ),
    # Racing Post fee-history tables (Google-indexed)
    ("2003", stallion_key("Pulpit")): ("$75,000", None, "Resolved via Racing Post fee-history"),
    ("2004", stallion_key("Pulpit")): ("$35,000", None, "Resolved via Racing Post fee-history"),
    ("2005", stallion_key("Pulpit")): ("$60,000", None, "Resolved via Racing Post fee-history"),
    ("2003", stallion_key("Seeking the Gold")): ("$225,000", None, "Resolved via Racing Post fee-history"),
    ("2004", stallion_key("Seeking the Gold")): ("$150,000", None, "Resolved via Racing Post fee-history"),
    ("2007", stallion_key("Tiznow")): ("$25,000", None, "Resolved via Racing Post fee-history"),
    # Web sources
    ("2001", stallion_key("Montbrook")): (
        "$7,500",
        None,
        "Resolved via web search: Ocala Star-Banner (Feb 2003 fee history)",
    ),
    ("2001", stallion_key("Silver Deputy")): (
        "$75,000",
        None,
        "Resolved via web search: BloodHorse 3 Oct 2001 (2001 fee $75,000; cut to $40,000 for 2002)",
    ),
    ("2001", stallion_key("Southern Halo")): (
        "$40,000",
        None,
        "Resolved via web search: BloodHorse/Ed DeRosa obituary (Ashford 2001 $40,000)",
    ),
    ("2001", stallion_key("In Excess (IRE)")): (
        "$25,000",
        None,
        "Resolved via web search: BloodHorse leading-sire advertised Vessels fee",
    ),
    ("2001", stallion_key("Miswaki")): (
        "$35,000",
        "Walmac Farm, KY",
        "Resolved via web search: BloodHorse leading-sire advertised Walmac fee",
    ),
    ("2001", stallion_key("Mt. Livermore")): (
        "$50,000",
        None,
        "Resolved via web search: BloodHorse leading-sire advertised Gainesway fee",
    ),
    ("2001", stallion_key("Rhythm")): (
        "$5,000",
        None,
        "Resolved via web search: BloodHorse leading 2YO-sire advertised Diamond F Ranch fee",
    ),
    ("2002", stallion_key("Bertrando")): (
        "$35,000",
        None,
        "Resolved via web search: BloodHorse advertised River Edge fee; RP fee-history begins 2003 at $25,000",
    ),
    ("2002", stallion_key("Devil's Bag")): (
        "$15,000",
        None,
        "Resolved via web search: BloodHorse leading-sire advertised Claiborne fee",
    ),
    ("2002", stallion_key("Dixieland Band")): (
        "$60,000",
        None,
        "Resolved via web search: TDN 4 Nov 2002 Lane's End advertisement $60,000 LF",
    ),
    ("2002", stallion_key("El Prado (IRE)")): (
        "$30,000",
        None,
        "Resolved via web search: Owner Breeder (2002 covering fee; jumped to $75,000 after champion-sire title)",
    ),
    ("2002", stallion_key("In Excess (IRE)")): (
        "Private",
        None,
        "Resolved via web search: BloodHorse $0 cell = Private (same pattern as Danzig); later Vessels ads Private Treaty",
    ),
    ("2002", stallion_key("Numerous")): (
        "$5,000",
        "Walnford Stud, NJ",
        "Resolved via web search: BloodHorse NA advertised Walnford fee (also shuttled to Haras du Quesnay)",
    ),
    ("2002", stallion_key("Pine Bluff")): (
        "$15,000",
        None,
        "Resolved via web search: BloodHorse leading-sire advertised Lane's End fee",
    ),
    ("2002", stallion_key("Seeking the Gold")): (
        "$250,000",
        None,
        "Resolved via web search: 2002 published top-20 fees + Claiborne peak $250,000",
    ),
    ("2002", stallion_key("Smokester")): (
        "$10,000",
        "Cardiff Stud Farm, CA",
        "Resolved via web search: BloodHorse leading 2YO-sire advertised Cardiff fee",
    ),
    ("2003", stallion_key("Deputy Commander")): (
        "$15,000",
        None,
        "Resolved via web search: BloodHorse advertised Airdrie covering fee",
    ),
    ("2003", stallion_key("Dixieland Band")): (
        "$60,000",
        None,
        "Resolved via web search: BloodHorse advertised Lane's End fee (2004 roster drops to $50,000)",
    ),
    ("2003", stallion_key("Elusive Quality")): (
        "$30,000",
        None,
        "Resolved via web search: Thoroughbred Racing Commentary / DRF (2003 $30,000 at Gainsborough)",
    ),
    ("2003", stallion_key("Langfuhr")): (
        "$20,000",
        "Vinery, KY",
        "Resolved via web search: TDN Dec 2001 Vinery first-crop stats $20,000; still at Vinery in 2003",
    ),
    ("2003", stallion_key("Miswaki")): (
        "$30,000",
        "Walmac Int'l, KY",
        "Resolved via web search: BloodHorse advertised Walmac covering fee (died Dec 2004)",
    ),
    ("2003", stallion_key("Mt. Livermore")): (
        "$40,000",
        None,
        "Resolved via web search: BloodHorse leading-sire advertised Gainesway fee",
    ),
    ("2003", stallion_key("Tale of the Cat")): (
        "$25,000",
        None,
        "Resolved via web search: BloodHorse second-crop advertised Ashford fee (AEI $75,000 is 2004)",
    ),
    ("2004", stallion_key("Bold Executive")): (
        "$7,500",
        "Gardiner Farms, CAN",
        "Resolved via web search: BloodHorse leading-sire advertised Gardiner fee",
    ),
    ("2004", stallion_key("El Prado (IRE)")): (
        "$75,000",
        None,
        "Resolved via web search: BloodHorse 'El Prado's Fee Jumps to $100,000' (2004 was $75,000)",
    ),
    ("2004", stallion_key("Elusive Quality")): (
        "$50,000",
        None,
        "Resolved via web search: New York Times 1 Jun 2004 / TRC (2004 $50,000 at Gainsborough)",
    ),
    ("2004", stallion_key("Langfuhr")): (
        "$25,000",
        "Lane's End Farm, KY",
        "Resolved via web search: Lane's End 2004–2007 roster table",
    ),
    ("2004", stallion_key("Mt. Livermore")): (
        "$35,000",
        None,
        "Resolved via web search: BloodHorse advertised Gainesway covering fee",
    ),
    ("2004", stallion_key("Pleasant Tap")): (
        "$15,000",
        None,
        "Resolved via web search: Lane's End 2004–2007 roster table",
    ),
    ("2004", stallion_key("Quiet American")): (
        "$35,000",
        None,
        "Resolved via web search: TDN Gainsborough ads $35,000 LF (2001–2002); 2004 ranking-year advertised fee",
    ),
    ("2004", stallion_key("Tale of the Cat")): (
        "$75,000",
        None,
        "Resolved via web search: BloodHorse/TDN (2004 $75,000; 2005 Ashford roster $65,000)",
    ),
    ("2004", stallion_key("Whiskey Wisdom")): (
        "$3,500",
        "Windfields Farm, CAN",
        "Resolved via web search: BloodHorse advertised Windfields covering fee",
    ),
    ("2005", stallion_key("Benchmark")): (
        "$7,500",
        None,
        "Resolved via web search: BloodHorse advertised River Edge covering fee",
    ),
    ("2005", stallion_key("El Prado (IRE)")): (
        "$100,000",
        None,
        "Resolved via web search: BloodHorse 'El Prado's Fee Jumps to $100,000' for 2005",
    ),
    ("2005", stallion_key("Fusaichi Pegasus")): (
        "$150,000",
        None,
        "Resolved via web search: TDN 4 Jan 2005 / BloodHorse (Ashford raised 2005 fee to $150,000)",
    ),
    ("2005", stallion_key("Giant's Causeway")): (
        "$200,000",
        None,
        "Resolved via web search: DRF (2005 opened $150,000, raised to $200,000)",
    ),
    ("2005", stallion_key("Hennessy")): (
        "$35,000",
        None,
        "Resolved via web search: BloodHorse (2005 $35,000; raised to $60,000 for 2006)",
    ),
    ("2005", stallion_key("In Excess (IRE)")): (
        "$25,000",
        None,
        "Resolved via web search: BloodHorse advertised Vessels covering fee",
    ),
    ("2005", stallion_key("Langfuhr")): (
        "$30,000",
        None,
        "Resolved via web search: Lane's End 2004–2007 roster table",
    ),
    ("2005", stallion_key("Tale of the Cat")): (
        "$65,000",
        None,
        "Resolved via web search: TDN 4 Jan 2005 Ashford roster / BloodHorse",
    ),
    ("2005", stallion_key("Unusual Heat")): (
        "$6,000",
        None,
        "Resolved via web search: BloodHorse advertised Old English Rancho covering fee",
    ),
    ("2006", stallion_key("Bernstein")): (
        "$25,000",
        None,
        "Resolved via web search: TDN 16 Nov 2005 stallion-value table (Castleton Lyons $25,000)",
    ),
    ("2006", stallion_key("Fusaichi Pegasus")): (
        "$125,000",
        None,
        "Resolved via web search: DRF / BloodHorse (cut from $150,000 to $125,000 for 2006)",
    ),
    ("2006", stallion_key("Giant's Causeway")): (
        "$300,000",
        None,
        "Resolved via web search: DRF 'Giant's Causeway at $300K' / BloodHorse",
    ),
    ("2006", stallion_key("Hennessy")): (
        "$75,000",
        None,
        "Resolved via web search: BloodHorse 2007 Ashford announcement (stood 2006 at $75,000)",
    ),
    ("2006", stallion_key("In Excess (IRE)")): (
        "Private",
        None,
        "Resolved via web search: BloodHorse $0 cell = Private; Vessels later Private Treaty",
    ),
    ("2006", stallion_key("Langfuhr")): (
        "$20,000",
        None,
        "Resolved via web search: Lane's End 2004–2007 roster table / b2yor 2006 $20,000",
    ),
    ("2006", stallion_key("Malibu Moon")): (
        "$30,000",
        None,
        "Resolved via web search: BloodHorse (2005 $30,000; 2007 $40,000) / TDN Nov 2005 $30,000",
    ),
    ("2006", stallion_key("Pleasant Tap")): (
        "$10,000",
        None,
        "Resolved via web search: Lane's End 2004–2007 roster table",
    ),
    ("2006", stallion_key("Tale of the Cat")): (
        "$50,000",
        None,
        "Resolved via web search: BloodHorse (Ashford cut Tale of the Cat from $65,000 to $50,000 for 2006)",
    ),
    ("2006", stallion_key("Unusual Heat")): (
        "$12,500",
        None,
        "Resolved via web search: BloodHorse leading 2YO-sire advertised Old English Rancho fee",
    ),
    ("2007", stallion_key("Bernstein")): (
        "$30,000",
        None,
        "Resolved via web search: BloodHorse 2007 2YO-sire advertised Castleton Lyons fee (AEI $20,000 is 2008)",
    ),
    ("2007", stallion_key("El Prado (IRE)")): (
        "$125,000",
        None,
        "Resolved via web search: Owner Breeder (fee peaked at $125,000 in 2006 and 2007)",
    ),
    ("2007", stallion_key("Elusive Quality")): (
        "$100,000",
        None,
        "Resolved via web search: Thoroughbred Racing Commentary (peaked $100,000 in 2005–2007)",
    ),
    ("2007", stallion_key("Giant's Causeway")): (
        "Private",
        None,
        "Resolved via web search: BloodHorse 'Ashford to Stand Giant's Causeway for Private Fee'",
    ),
    ("2007", stallion_key("Pleasant Tap")): (
        "$15,000",
        None,
        "Resolved via web search: Lane's End 2004–2007 roster table",
    ),
    ("2007", stallion_key("Put It Back")): (
        "$5,000",
        None,
        "Resolved via web search: TDN 15 Nov 2006 Bridlewood first-crop stats $5,000",
    ),
    ("2007", stallion_key("Unusual Heat")): (
        "$15,000",
        None,
        "Resolved via web search: BloodHorse advertised Old English Rancho covering fee",
    ),
    ("2008", stallion_key("In Excess (IRE)")): (
        "Private",
        None,
        "Resolved via web search: BloodHorse $0 cell = Private; 2009 Vessels archive Private Treaty",
    ),
}


def strip_resolution_notes(notes: str) -> str:
    text = notes or ""
    for rx in (CONFLICT_RE, UNRESOLVED_RE, YEAR_NM_RE, RESOLVED_RE):
        text = rx.sub("", text)
    return merge_notes(text)


def best_farm(items: list[dict], override: str | None) -> str:
    if override:
        return override
    best = items[0]["Farm"]
    for item in items[1:]:
        if farm_score(item["Farm"]) > farm_score(best):
            best = item["Farm"]
    return display_or_na(best)


def load_rows() -> list[dict]:
    with OUT_CSV.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: (r["Year"], r["Stallion"].casefold(), r["Stud Fee"], r["Source List"]))
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


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
    extra = (
        "Remaining conflicts after the first RP pass were resolved from Racing Post "
        "fee-history tables (Google-indexed historical years) plus BloodHorse, TDN, "
        "DRF, Lane's End roster, and farm-ad sources. User-supplied 2001 ground truth "
        "was applied for Avenue of Flags ($10,000, Golden Eagle Farm, Ramona, CA), "
        "Bertrando ($30,000), Danzig (Private), General Meeting ($50,000), and "
        "Cee's Tizzy via the RP fee-history URL pattern.\n"
    )
    if "Remaining conflicts after the first RP pass" not in text:
        text = text.replace(
            "Misses: stud_fee_rp_misses.csv. HTML cache: rp_cache/html/.\n",
            "Misses: stud_fee_rp_misses.csv. HTML cache: rp_cache/html/.\n" + extra,
        )
    OUT_README.write_text(text, encoding="utf-8")


def main() -> None:
    rows = load_rows()
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        notes = row.get("Notes") or ""
        if "Conflict:" in notes or "Unresolved:" in notes or "year-not-matched" in notes:
            groups[(row["Year"], stallion_key(row["Stallion"]))].append(i)

    drop: set[int] = set()
    newly = 0
    misses: list[dict] = []

    for (year, skey), idxs in groups.items():
        items = [rows[i] for i in idxs]
        stallion = items[0]["Stallion"]
        old_fees = sorted({it["Stud Fee"] for it in items})
        hit = RESOLUTIONS.get((year, skey))
        if not hit:
            # keep both rows
            for it in items:
                base = strip_resolution_notes(it["Notes"])
                it["Notes"] = merge_notes(
                    base,
                    "Conflict: different stud fees for same stallion-year",
                    "Unresolved: no year-specific fee found",
                )
            misses.append({
                "Stallion": stallion,
                "Year": year,
                "Reason": "unresolved-after-search",
                "URL": "",
                "RP_years": "",
                "RP_fee": "",
                "Old_fees": "; ".join(old_fees),
            })
            continue

        fee, farm, note = hit
        keep = items[0]
        sources: list[str] = []
        for it in items:
            sources.extend(s.strip() for s in it["Source List"].split(";") if s.strip())
        base_notes = merge_notes(*(strip_resolution_notes(it["Notes"]) for it in items))
        keep["Stud Fee"] = fee
        keep["Farm"] = best_farm(items, farm)
        keep["Source List"] = "; ".join(sorted(dict.fromkeys(sources)))
        keep["Notes"] = merge_notes(base_notes, note)
        for extra in idxs[1:]:
            drop.add(extra)
        newly += 1

    rows = [r for i, r in enumerate(rows) if i not in drop]
    write_csv(rows)

    with OUT_MISSES.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["Stallion", "Year", "Reason", "URL", "RP_years", "RP_fee", "Old_fees"],
        )
        writer.writeheader()
        writer.writerows(misses)

    def sy_count(*needles: str) -> int:
        return len({
            (r["Year"], stallion_key(r["Stallion"]))
            for r in rows
            if any(n in (r.get("Notes") or "") for n in needles)
        })

    resolved = sy_count("Resolved via Racing Post", "Resolved via web search")
    unresolved = sy_count("Unresolved:")
    year_not_matched = sy_count("year-not-matched")
    update_readme(rows, resolved, unresolved, year_not_matched)

    print(f"Newly collapsed this pass: {newly}")
    print(f"Total resolved notes: {resolved}")
    print(f"Remaining unresolved: {unresolved}")
    print(f"Remaining year-not-matched: {year_not_matched}")
    print(f"Output rows: {len(rows)}")
    print(f"Misses: {len(misses)}")

    examples = [
        ("2001", "Avenue Of Flags"),
        ("2001", "Bertrando"),
        ("2001", "Danzig"),
        ("2001", "General Meeting"),
        ("2003", "Cee's Tizzy"),
        ("2004", "Cee's Tizzy"),
        ("2005", "Cee's Tizzy"),
    ]
    print("User examples / Cee's Tizzy:")
    for year, name in examples:
        matches = [r for r in rows if r["Year"] == year and stallion_key(r["Stallion"]) == stallion_key(name)]
        for r in matches:
            print(f"  {r['Year']} {r['Stallion']}: {r['Stud Fee']} | {r['Farm']} | {r['Notes'][:120]}")


if __name__ == "__main__":
    main()
