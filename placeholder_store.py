"""Compatibility facade over the 8 sample CSVs (crossr_core.sample_db).

Runtime horse/sales/race/rank/fee facts come only from data/*.csv.
Account/client/notes rows are optional app-state CSVs under
placeholderdatabase/ (not breeding facts) — empty if missing.
"""

from __future__ import annotations

import csv
import json
import os
import threading
from pathlib import Path

from crossr_core import sample_db

ROOT = Path(__file__).resolve().parent
APP_STATE_DIR = ROOT / "placeholderdatabase"

# App-state only (not sample DB facts). Kept so auth/notes keep working.
APP_TABLES = {
    "industry_roles": ["role_name", "description"],
    "accounts": ["account_id", "display_name", "email", "industry_role", "created_at"],
    "clients": ["client_id", "account_id", "client_name"],
    "client_preferences": [
        "preference_id", "client_id", "sex", "foaled", "surface",
        "min_stud_fee", "max_stud_fee", "sire_name", "requires_producer_note",
    ],
    "notes": ["note_id", "account_id", "sale_title", "hip", "body", "source", "updated_at"],
    "hypothetical_matings": ["mating_key", "horse_name", "sire_name", "dam_name", "pedigree_json"],
}

_LOCK = threading.Lock()
_APP_CACHE: dict[str, list[dict]] = {}

name_key = sample_db.name_key
broodmare_clean_horse_name = sample_db.broodmare_clean_horse_name


def use_postgres() -> bool:
    return False


def _load_app_csv(table: str) -> list[dict]:
    columns = APP_TABLES[table]
    path = APP_STATE_DIR / f"{table}.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [{col: (raw.get(col) or "") for col in columns} for raw in csv.DictReader(handle)]


def load_table(table: str, refresh: bool = False) -> list[dict]:
    """Load a logical table. Fact tables are projected from the 8 sample CSVs."""
    if table in APP_TABLES:
        with _LOCK:
            if refresh or table not in _APP_CACHE:
                _APP_CACHE[table] = _load_app_csv(table)
            return list(_APP_CACHE[table])

    if table == "graded_stakes_winners":
        return [
            {
                "race_name": r.get("Race Name") or "",
                "race_year": r.get("Race Year") or "",
                "horse_name": r.get("Horse Name") or "",
                "foaling_year": r.get("Foaling Year") or r.get("Year Foaled") or "",
                "sex": r.get("Sex") or "",
                "country": r.get("Country") or "",
                "track": r.get("Track") or "",
                "race_date": r.get("Date") or "",
                "distance": r.get("Distance") or "",
                "age": r.get("Age") or "",
                "purse": r.get("Purse") or "",
                "grade": r.get("Grade") or r.get("Group") or "",
            }
            for r in sample_db.graded_stakes_winners()
        ]

    if table == "sale_results":
        rows = []
        for i, lot in enumerate(sample_db.load_table("sales_lots"), start=1):
            rows.append({
                "result_id": str(i),
                "sale_title": lot.get("catalog_title") or "",
                "sale_year": lot.get("catalog_year") or "",
                "hip": lot.get("hip") or "",
                "horse_name": lot.get("name") or "",
                "sex": lot.get("sex") or "",
                "sire": lot.get("sire") or "",
                "dam": lot.get("dam") or "",
                "sire_of_dam": lot.get("damsire") or "",
                "birth_year": lot.get("birth_year") or "",
                "price_num": lot.get("price_num") or "",
                "price_raw": lot.get("price_raw") or "",
                "is_rna": lot.get("is_rna") or "",
                "is_out": lot.get("is_out") or "",
                "purchaser": lot.get("purchaser") or "",
                "consignor": lot.get("consignor") or "",
                "color": lot.get("color") or "",
                "foaled": lot.get("foaled_location") or "",
                "sold_as": "",
                "source_file": lot.get("source_file") or "",
            })
        return rows

    if table == "sales":
        seen = {}
        for lot in sample_db.load_table("sales_lots"):
            key = (lot.get("catalog_year") or "", lot.get("catalog_title") or "")
            if key in seen or not key[1]:
                continue
            seen[key] = {
                "sale_id": str(len(seen) + 1),
                "sale_company": "",
                "sale_title": key[1],
                "sale_year": key[0],
                "sale_kind": "",
                "month_index": "",
                "source_file": lot.get("source_file") or "",
            }
        return list(seen.values())

    if table == "catalog_hips":
        rows = []
        for i, lot in enumerate(sample_db.load_table("sales_lots"), start=1):
            rows.append({
                "hip_id": str(i),
                "sale_title": lot.get("catalog_title") or "",
                "sale_year": lot.get("catalog_year") or "",
                "hip": lot.get("hip") or "",
                "horse_name": lot.get("name") or "",
                "sex": lot.get("sex") or "",
                "color": lot.get("color") or "",
                "sire": lot.get("sire") or "",
                "dam": lot.get("dam") or "",
                "sire_of_dam": lot.get("damsire") or "",
                "year_of_birth": lot.get("birth_year") or "",
                "foaled": lot.get("foaled_location") or "",
                "sold_as": "",
                "covering_sire": "",
                "consignor": lot.get("consignor") or "",
                "notes": "",
                "cross_success": "",
                "dam_success_racer": "",
                "dam_success_producer": "",
                "racing_success": "",
                "starred": "",
                "source_file": lot.get("source_file") or "",
            })
        return rows

    if table == "stallion_stats":
        rows = []
        for name, profile in sample_db.stallion_roster_from_fees().items():
            rows.append({
                "stallion_name": name,
                "farm": profile.get("Farm") or "",
                "year_born": profile.get("Year Born") or "",
                "stud_duty_year": profile.get("Stud Duty Year") or "",
                "stud_fee": profile.get("Stud Fee") or "",
                "status": profile.get("Status") or "active",
                "surface": profile.get("Surface") or "",
                "height": profile.get("Height") or "N/A",
                "conformation": profile.get("Conformation & Physical Profile") or "",
                "major_wins": profile.get("Major Wins") or "",
                "career_highlight": profile.get("Career Highlight") or "",
                "race_record": json.dumps(profile.get("Race Record") or {}),
                "progeny_racing_statistics": "",
                "progeny_earnings_statistics": "",
                "legacy_progeny_stats": "",
                "sire_rank": profile.get("sire_rank") or "",
                "mares_bred_2025": profile.get("mares_bred_2025") or "",
            })
        return rows

    if table == "broodmare_sire_stats":
        return [
            {
                "rank": entry.get("rank") or "",
                "stallion": entry.get("stallion") or "",
                "lineage": entry.get("lineage") or "",
                "dams": entry.get("dams") or "",
                "rnrs": entry.get("rnrs") or "",
                "wnrs": entry.get("wnrs") or "",
                "chief_earner": entry.get("chief_earner") or "",
                "chief_earners_earnings": entry.get("chief_earners_earnings") or "",
                "earnings_2026": entry.get("earnings_2026") or "",
                "cum_swrs": entry.get("cum_swrs") or "",
                "aei": entry.get("aei") or "",
                "comp_index": entry.get("comp_index") or "",
                "cum_foals": entry.get("cum_foals") or "",
            }
            for entry in sample_db.broodmare_sire_rows()
        ]

    if table == "mares_bred":
        rows = []
        for row in sample_db.load_table("breeding_seasons"):
            rows.append({
                "stallion": row.get("stallion") or "",
                "mares_bred_2025": row.get("mares_bred") or "",
                "state_prov": row.get("state") or "",
                "live_foal_percentage_for_2025_foals": row.get("live_foal_pct") or "",
                "live_foal_percentage_for_2024_foals": "",
                "region": "",
                "breeding_year": row.get("breeding_year") or "",
                "live_foals": row.get("live_foals") or "",
            })
        return rows

    if table == "horses":
        rows = []
        for row in sample_db.load_table("race_horses"):
            rows.append({
                "horse_id": row.get("id") or "",
                "name": row.get("display_name") or row.get("name_key") or "",
                "name_key": row.get("name_key") or "",
                "display_name": row.get("display_name") or "",
                "foaling_year": row.get("foal_year") or "",
                "sex": row.get("sex") or "",
                "color": row.get("color") or "",
                "country": row.get("foaled_in") or "",
                "sire_name": row.get("sire") or "",
                "dam_name": row.get("dam") or "",
                "class_label": row.get("best_class") or "",
                "height": "",
                "conformation": "",
            })
        return rows

    if table == "pedigree_lines":
        # Pedigrees live in pedigrees_database.py — no CSV mirror at runtime.
        return []

    raise KeyError(f"Unknown table {table}")


def write_table(table: str, rows: list[dict]) -> None:
    """App-state writes only. Fact tables are owned by scripts/pipeline/run.py."""
    if table not in APP_TABLES:
        raise RuntimeError(
            f"Refusing to write fact table {table!r}; use scripts/pipeline/run.py → data/{table}.csv"
        )
    columns = APP_TABLES[table]
    APP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = APP_STATE_DIR / f"{table}.csv"
    tmp = path.with_suffix(path.suffix + ".tmp")
    normalized = [{col: "" if row.get(col) is None else str(row.get(col)) for col in columns} for row in rows]
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(normalized)
    os.replace(tmp, path)
    with _LOCK:
        _APP_CACHE[table] = normalized


def _json_obj(text: str):
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def load_stallion_profiles() -> dict:
    return sample_db.stallion_roster_from_fees()


def save_stallion_profiles(master_profiles: dict) -> None:
    """No-op for legacy callers. Stud cards derive from data/stud_fees.csv."""
    return None


def load_broodmare_sire_rows() -> list[dict]:
    return sample_db.broodmare_sire_rows()


def load_graded_stakes_records() -> list[dict]:
    return sample_db.graded_stakes_winners()


def load_broodmare_database() -> dict:
    database = {}
    for entry in load_broodmare_sire_rows():
        key = broodmare_clean_horse_name(entry["stallion"])
        if not key:
            continue
        database[key] = {
            "Stallion": entry["stallion"],
            "Rank": entry["rank"],
            "Lineage": entry["lineage"],
            "Dams": str(entry["dams"]),
            "Runners": str(entry["rnrs"]),
            "Winners": str(entry["wnrs"]),
            "Chief Earner": entry["chief_earner"],
            "Chief Earner Earnings": entry["chief_earners_earnings"],
            "2026 Earnings": entry["earnings_2026"],
            "AEI": entry["aei"],
            "Comp Index": entry["comp_index"],
        }
    return database


def mares_bred_for(clean_search: str) -> dict | None:
    key = name_key(clean_search)
    best = None
    best_year = -1
    for row in sample_db.load_table("breeding_seasons"):
        if name_key(row.get("stallion") or "") != key:
            continue
        try:
            year = int(str(row.get("breeding_year") or "").strip())
        except ValueError:
            year = 0
        if year >= best_year:
            best_year = year
            best = {
                "stallion": row.get("stallion") or "",
                "mares_bred_2025": row.get("mares_bred") or "",
                "state_prov": row.get("state") or "",
                "live_foal_percentage_for_2025_foals": row.get("live_foal_pct") or "",
                "live_foal_percentage_for_2024_foals": "",
                "region": "",
            }
    return best


def sale_results_matching(sale_title: str) -> list[dict]:
    needle = (sale_title or "").strip().lower()
    if not needle:
        return []
    rows = load_table("sale_results")
    exact = [row for row in rows if (row.get("sale_title") or "").strip().lower() == needle]
    if exact:
        return exact
    return [row for row in rows if needle in (row.get("sale_title") or "").lower()]


def stallion_index() -> dict:
    index = {}
    for row in load_table("stallion_stats"):
        index[name_key(row.get("stallion_name") or "")] = row
    return index


def next_id(table: str, column: str) -> int:
    highest = 0
    for row in load_table(table):
        try:
            highest = max(highest, int(float(row.get(column) or 0)))
        except ValueError:
            continue
    return highest + 1
