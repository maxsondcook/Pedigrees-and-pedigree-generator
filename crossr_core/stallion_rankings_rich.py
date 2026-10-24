"""Rich BloodHorse stallion ranking history from data/stallion_rankings.csv.

Surfaces AEI, CI, earnings, runners, and every other published metric column
for the stallion profile STALLION RANKINGS panel.
"""
from __future__ import annotations

import os
import re
import sqlite3

import main
from crossr_core import sample_db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# BloodHorse SQLite list/table → UI list id + label.
_DB_LIST_META = {
    ("General", ""): ("leading_sire", "Leading Sire Rankings"),
    ("Lifetime AEI", ""): ("leading_sires_by_aei", "Leading Sires by AEI"),
    ("First-Crop", ""): ("leading_first_crop_sires", "Leading First Crop Sires"),
    ("Second-Crop", ""): ("leading_second_crop_sires", "Leading Second-Crop Sires"),
    ("Third-Crop", ""): ("leading_third_crop_sires", "Leading Third-Crop Sires"),
    ("Two-Year-Old", ""): ("leading_two_year_old_sires", "Leading Two-Year-Old Sires"),
    ("Turf", ""): ("leading_turf_sires", "Leading Turf Sires"),
    ("Broodmare", ""): ("leading_broodmare_sires", "Leading Broodmare Sires"),
    ("International", "Summary"): ("leading_international_sires", "Leading International Sires"),
    ("International", "North America"): (
        "leading_international_sires_north_america",
        "Leading International Sires — North America",
    ),
    ("International", "Europe & Dubai"): (
        "leading_international_sires_europe_and_dubai",
        "Leading International Sires — Europe & Dubai",
    ),
    ("International", "Japan & Hong Kong"): (
        "leading_international_sires_japan_and_hong_kong",
        "Leading International Sires — Japan & Hong Kong",
    ),
    ("International First-Crop", "Summary"): (
        "leading_international_first_crop_sires",
        "Leading International First-Crop Sires",
    ),
    ("International First-Crop", "North America"): (
        "leading_international_first_crop_sires_north_america",
        "Leading International First-Crop Sires — North America",
    ),
    ("International First-Crop", "Europe & Dubai"): (
        "leading_international_first_crop_sires_europe_and_dubai",
        "Leading International First-Crop Sires — Europe & Dubai",
    ),
    ("International First-Crop", "Japan & Hong Kong"): (
        "leading_international_first_crop_sires_japan_and_hong_kong",
        "Leading International First-Crop Sires — Japan & Hong Kong",
    ),
    ("International Second-Crop", "Summary"): (
        "leading_international_2nd_crop_sires",
        "Leading International 2nd-Crop Sires",
    ),
    ("International Second-Crop", "North America"): (
        "leading_international_2nd_crop_sires_north_america",
        "Leading International 2nd-Crop Sires — North America",
    ),
    ("International Second-Crop", "Europe & Dubai"): (
        "leading_international_2nd_crop_sires_europe_and_dubai",
        "Leading International 2nd-Crop Sires — Europe & Dubai",
    ),
    ("International Second-Crop", "Japan & Hong Kong"): (
        "leading_international_2nd_crop_sires_japan_and_hong_kong",
        "Leading International 2nd-Crop Sires — Japan & Hong Kong",
    ),
    ("International Third-Crop", "Summary"): (
        "leading_international_3rd_crop_sires",
        "Leading International 3rd-Crop Sires",
    ),
    ("International Third-Crop", "North America"): (
        "leading_international_3rd_crop_sires_north_america",
        "Leading International 3rd-Crop Sires — North America",
    ),
    ("International Third-Crop", "Europe & Dubai"): (
        "leading_international_3rd_crop_sires_europe_and_dubai",
        "Leading International 3rd-Crop Sires — Europe & Dubai",
    ),
    ("International Third-Crop", "Japan & Hong Kong"): (
        "leading_international_3rd_crop_sires_japan_and_hong_kong",
        "Leading International 3rd-Crop Sires — Japan & Hong Kong",
    ),
    ("International Two-Year-Old", "Summary"): (
        "leading_international_two_year_old_sires",
        "Leading International Two-Year-Old Sires",
    ),
    ("International Two-Year-Old", "North America"): (
        "leading_international_two_year_old_sires_north_america",
        "Leading International Two-Year-Old Sires — North America",
    ),
    ("International Two-Year-Old", "Europe & Dubai"): (
        "leading_international_two_year_old_sires_europe_and_dubai",
        "Leading International Two-Year-Old Sires — Europe & Dubai",
    ),
    ("International Two-Year-Old", "Japan & Hong Kong"): (
        "leading_international_two_year_old_sires_japan_and_hong_kong",
        "Leading International Two-Year-Old Sires — Japan & Hong Kong",
    ),
}

_RANKING_METRIC_COLUMNS = [
    ("year", "Year", "number"),
    ("rank", "Rank", "number"),
    ("aei", "AEI", "number"),
    ("comparable_index", "CI", "number"),
    ("year_earnings", "Earnings", "money"),
    ("runners", "Rnrs", "number"),
    ("winners", "Wnrs", "number"),
    ("repeat_winners", "Rpt Wnrs", "number"),
    ("stakes_winners", "BT SWrs", "number"),
    ("stakes_wins", "BT SWs", "number"),
    ("graded_stakes_winners", "GSWrs", "number"),
    ("grade1_stakes_winners", "G1SWrs", "number"),
    ("stakes_horses", "BT SHs", "number"),
    ("chief_earner", "Chief Earner", "text"),
    ("chief_earner_earnings", "Chief Earner $", "money"),
    ("stud_fee", "Stud Fee", "money"),
    ("farm", "Farm", "text"),
    ("dams", "Dams", "number"),
    ("cumulative_stakes_winners", "Cum. SWrs", "number"),
    ("cumulative_foals", "Cum. Foals", "number"),
    ("current_2yos", "Current 2YOs", "number"),
    ("yearling_average", "Yrlg Avg", "money"),
    ("crops", "Crops", "number"),
    ("average_crop_size", "Avg Crop", "number"),
    ("foals", "Foals", "number"),
    ("lifetime_yearlings_sold", "Lt Yrlgs Sold", "number"),
    ("lifetime_yearling_average", "Lt Yrlg Avg", "money"),
    ("yearling_window", "Yrlg Window", "text"),
    ("window_yearlings_sold", "Win Yrlgs Sold", "number"),
    ("window_yearling_average", "Win Yrlg Avg", "money"),
    ("all_surfaces_runners", "All Rnrs", "number"),
    ("all_surfaces_winners", "All Wnrs", "number"),
    ("all_surfaces_stakes_winners", "All SWrs", "number"),
    ("turf_runners", "Turf Rnrs", "number"),
    ("turf_winners", "Turf Wnrs", "number"),
    ("turf_stakes_winners", "Turf SWrs", "number"),
    ("north_america_earnings", "NA Earn", "money"),
    ("europe_dubai_earnings", "EU/Dubai Earn", "money"),
    ("japan_hong_kong_earnings", "JPN/HK Earn", "money"),
    ("region_earnings", "Region Earn", "money"),
    ("international_stakes_winners", "Intl SWrs", "number"),
    ("international_stakes_horses", "Intl SHs", "number"),
    ("earnings_share", "Earn Share", "text"),
    ("stakes_winners_percent", "SWrs %", "text"),
    ("graded_stakes_winners_percent", "GSWrs %", "text"),
    ("grade1_stakes_winners_percent", "G1SWrs %", "text"),
]

_SKIP_NUM_KEYS = {
    "chief_earner",
    "farm",
    "yearling_window",
    "earnings_share",
    "stakes_winners_percent",
    "graded_stakes_winners_percent",
    "grade1_stakes_winners_percent",
}


def _db_path():
    return str(sample_db.csv_path("stallion_rankings"))


def _conn():
    return sample_db.rankings_connection()


def _intish(val):
    if val is None or val == "":
        return None
    digits = re.sub(r"[^\d]", "", str(val))
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _blank(val):
    if val is None:
        return True
    text = str(val).strip()
    return text == "" or text.upper() in {"N/A", "NA", "-", "—", "NONE"}


def parse_ranking_number(val):
    """Parse published ranking cell to float for sort/filter."""
    if _blank(val):
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    text = str(val).strip()
    paren = re.search(r"\(\s*\$?\s*([\d,]+(?:\.\d+)?)\s*\)\s*$", text)
    if paren:
        try:
            return float(paren.group(1).replace(",", ""))
        except ValueError:
            pass
    cleaned = re.sub(r"[,$%\s]", "", text.replace("—", "-")).lstrip("$")
    if not cleaned or cleaned in {"-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _rank_list_id(label):
    slug = label.lower().replace("&", " and ").replace("—", " ").replace("–", " ")
    return re.sub(r"[^a-z0-9]+", "_", slug).strip("_")


def rich_rankings_from_db(stallion_name, entered_stud=None):
    """Full ranking history for one stallion: lists, rows, columns."""
    conn = _conn()
    if conn is None:
        return {"lists": [], "rows": {}, "columns": {}}

    key = main.clean_horse_name(stallion_name)
    if not key:
        return {"lists": [], "rows": {}, "columns": {}}

    start = _intish(entered_stud)
    if start and start <= 1900:
        start = None

    try:
        raw_rows = conn.execute(
            """
            SELECT *
            FROM stallion_rankings
            WHERE upper(stallion) = upper(?)
               OR upper(stallion) LIKE upper(?) || ' (%'
            ORDER BY year DESC, list, table_name
            """,
            (key, key),
        ).fetchall()
    except sqlite3.Error:
        return {"lists": [], "rows": {}, "columns": {}}

    buckets = {}
    for raw in raw_rows:
        row = dict(raw)
        year = _intish(row.get("year"))
        if not year:
            continue
        if start and year < start:
            continue
        list_name = (row.get("list") or "").strip()
        table_name = (row.get("table_name") or "").strip()
        meta = _DB_LIST_META.get((list_name, table_name))
        if not meta:
            label = list_name if not table_name else f"{list_name} — {table_name}"
            meta = (_rank_list_id(label), label)
        list_id, label = meta
        rank = _intish(row.get("rank"))
        if not rank:
            continue

        out = {
            "year": year,
            "rank": rank,
            "list": list_name,
            "table_name": table_name or None,
        }
        earnings_num = parse_ranking_number(row.get("year_earnings"))
        if earnings_num is not None:
            out["earnings"] = int(earnings_num) if earnings_num == int(earnings_num) else earnings_num

        for col_key, _lab, _kind in _RANKING_METRIC_COLUMNS:
            if col_key in ("year", "rank"):
                continue
            val = row.get(col_key)
            if _blank(val):
                continue
            if isinstance(val, str):
                val = val.strip()
            out[col_key] = val
            if col_key not in _SKIP_NUM_KEYS:
                num = parse_ranking_number(val)
                if num is not None:
                    out[f"{col_key}_num"] = num

        fee_num = parse_ranking_number(row.get("stud_fee"))
        if fee_num is not None:
            out["stud_fee_num"] = fee_num

        bucket = buckets.setdefault(list_id, {"label": label, "rows": [], "seen_years": set()})
        if year in bucket["seen_years"]:
            continue
        bucket["seen_years"].add(year)
        bucket["rows"].append(out)

    preferred = [meta[0] for meta in _DB_LIST_META.values()]
    lists = []
    rows = {}
    columns = {}
    seen = set()
    for list_id in preferred + [k for k in buckets if k not in preferred]:
        if list_id in seen or list_id not in buckets:
            continue
        seen.add(list_id)
        bucket = buckets[list_id]
        ranked = bucket["rows"]
        if not ranked:
            continue
        present = {"year", "rank"}
        for r in ranked:
            for col_key, _, _ in _RANKING_METRIC_COLUMNS:
                if col_key in ("year", "rank"):
                    continue
                if not _blank(r.get(col_key)):
                    present.add(col_key)
        col_defs = [
            {"key": k, "label": lab, "type": kind}
            for k, lab, kind in _RANKING_METRIC_COLUMNS
            if k in present
        ]
        item = {"id": list_id, "label": bucket["label"], "group": "bloodhorse", "rich": True}
        if list_id == "leading_sire":
            item["metric"] = "earnings"
            item["metric_label"] = "Total Progeny Earnings"
        elif list_id == "leading_sires_by_aei":
            item["metric"] = "aei"
            item["metric_label"] = "AEI"
        lists.append(item)
        rows[list_id] = ranked
        columns[list_id] = col_defs

    return {"lists": lists, "rows": rows, "columns": columns}
