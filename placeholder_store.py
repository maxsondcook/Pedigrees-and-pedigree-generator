"""Read and write the placeholderdatabase CSVs that mirror schema.sql.

The sales hub and the Python engines use this module. Set CROSSR_DATA=postgres
and DATABASE_URL to read the same tables from Postgres instead of the CSVs.
"""

from __future__ import annotations

import csv
import json
import os
import re
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "placeholderdatabase"

TABLES = {
    "industry_roles": ["role_name", "description"],
    "accounts": ["account_id", "display_name", "email", "industry_role", "created_at"],
    "clients": ["client_id", "account_id", "client_name"],
    "client_preferences": [
        "preference_id", "client_id", "sex", "foaled", "surface",
        "min_stud_fee", "max_stud_fee", "sire_name", "requires_producer_note",
    ],
    "horses": [
        "horse_id", "name", "name_key", "display_name", "foaling_year", "sex",
        "color", "country", "sire_name", "dam_name", "class_label", "height", "conformation",
    ],
    "pedigree_lines": [
        "line_id", "subject_name", "subject_key", "line_side", "generation",
        "relation", "ancestor_name", "ancestor_year", "class_label",
    ],
    "sales": [
        "sale_id", "sale_company", "sale_title", "sale_year", "sale_kind",
        "month_index", "source_file",
    ],
    "sale_results": [
        "result_id", "sale_title", "sale_year", "hip", "horse_name", "sex", "sire",
        "dam", "sire_of_dam", "birth_year", "price_num", "price_raw", "is_rna",
        "is_out", "purchaser", "consignor", "color", "foaled", "sold_as", "source_file",
    ],
    "catalog_hips": [
        "hip_id", "sale_title", "sale_year", "hip", "horse_name", "sex", "color",
        "sire", "dam", "sire_of_dam", "year_of_birth", "foaled", "sold_as",
        "covering_sire", "consignor", "notes", "cross_success", "dam_success_racer",
        "dam_success_producer", "racing_success", "starred", "source_file",
    ],
    "stallion_stats": [
        "stallion_name", "farm", "year_born", "stud_duty_year", "stud_fee", "status",
        "surface", "height", "conformation", "major_wins", "career_highlight",
        "race_record", "progeny_racing_statistics", "progeny_earnings_statistics",
        "legacy_progeny_stats", "sire_rank", "mares_bred_2025",
    ],
    "broodmare_sire_stats": [
        "rank", "stallion", "lineage", "dams", "rnrs", "wnrs", "chief_earner",
        "chief_earners_earnings", "earnings_2026", "cum_swrs", "aei", "comp_index", "cum_foals",
    ],
    "mares_bred": [
        "stallion", "mares_bred_2025", "state_prov",
        "live_foal_percentage_for_2025_foals", "live_foal_percentage_for_2024_foals", "region",
    ],
    "graded_stakes_winners": [
        "race_name", "race_year", "horse_name", "foaling_year", "sex", "country",
        "track", "race_date", "distance", "age", "purse", "grade",
    ],
    "notes": ["note_id", "account_id", "sale_title", "hip", "body", "source", "updated_at"],
    "hypothetical_matings": ["mating_key", "horse_name", "sire_name", "dam_name", "pedigree_json"],
}

_LOCK = threading.Lock()
_CACHE: dict[str, list[dict]] = {}


def name_key(name: str) -> str:
    """Same normalization main.clean_horse_name uses for pedigree lookups."""
    if not name or not isinstance(name, str):
        return ""
    cleaned = re.sub(r"\(.*?\)", "", name)
    cleaned = cleaned.replace(".", "").replace("'", "").replace(",", "").replace("’", "")
    return " ".join(cleaned.split()).strip().upper()


def broodmare_clean_horse_name(name: str) -> str:
    """Normalization historically exported by broodmare_sire_data.clean_horse_name."""
    if not name or not isinstance(name, str):
        return ""
    cleaned = re.sub(r"\(.*?\)", "", name)
    cleaned = cleaned.replace(".", "")
    return " ".join(cleaned.split()).strip().lower()


def use_postgres() -> bool:
    return os.environ.get("CROSSR_DATA", "csv").strip().lower() == "postgres" and bool(os.environ.get("DATABASE_URL"))


def _csv_path(table: str) -> Path:
    if table not in TABLES:
        raise KeyError(f"Unknown table {table}")
    return DATA_DIR / f"{table}.csv"


def _load_csv(table: str) -> list[dict]:
    path = _csv_path(table)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for raw in reader:
            row = {column: (raw.get(column) or "") for column in TABLES[table]}
            rows.append(row)
        return rows


def _load_postgres(table: str) -> list[dict]:
    import psycopg
    columns = TABLES[table]
    sql = f"SELECT {', '.join(columns)} FROM {table}"
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            fetched = cur.fetchall()
    rows = []
    for record in fetched:
        row = {}
        for column, value in zip(columns, record):
            if value is None:
                row[column] = ""
            elif isinstance(value, (dict, list)):
                row[column] = json.dumps(value)
            else:
                row[column] = str(value)
        rows.append(row)
    return rows


def load_table(table: str, refresh: bool = False) -> list[dict]:
    with _LOCK:
        if refresh or table not in _CACHE:
            _CACHE[table] = _load_postgres(table) if use_postgres() else _load_csv(table)
        return list(_CACHE[table])


def write_table(table: str, rows: list[dict]) -> None:
    """Persist rows. Postgres writes when CROSSR_DATA=postgres; otherwise the CSV."""
    columns = TABLES[table]
    normalized = [{column: "" if row.get(column) is None else str(row.get(column)) for column in columns} for row in rows]
    with _LOCK:
        if use_postgres():
            import psycopg
            with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"DELETE FROM {table}")
                    if normalized:
                        placeholders = ", ".join(["%s"] * len(columns))
                        cur.executemany(
                            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                            [tuple(row[column] if row[column] != "" else None for column in columns) for row in normalized],
                        )
                conn.commit()
        else:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            path = _csv_path(table)
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
                writer.writeheader()
                writer.writerows(normalized)
        _CACHE[table] = normalized


def _json_obj(text: str):
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def load_stallion_profiles() -> dict:
    """Rebuild the stallion profile dictionary the stats engine displays."""
    profiles = {}
    for row in load_table("stallion_stats"):
        name = row.get("stallion_name") or ""
        if not name:
            continue
        fee_text = row.get("stud_fee") or "0"
        year_text = row.get("year_born") or "0"
        stud_text = row.get("stud_duty_year") or "0"
        try:
            fee = int(float(fee_text))
        except ValueError:
            fee = 0
        try:
            year_born = int(float(year_text))
        except ValueError:
            year_born = 0
        try:
            stud_year = int(float(stud_text))
        except ValueError:
            stud_year = 0
        profile = {
            "Farm": row.get("farm") or "",
            "Year Born": year_born,
            "Stud Duty Year": stud_year,
            "Stud Fee": fee,
            "Status": row.get("status") or "active",
            "Surface": row.get("surface") or "",
            "Height": row.get("height") or "N/A",
            "Conformation & Physical Profile": row.get("conformation") or "",
            "Major Wins": row.get("major_wins") or "",
            "Career Highlight": row.get("career_highlight") or "",
            "Race Record": _json_obj(row.get("race_record") or ""),
        }
        racing = _json_obj(row.get("progeny_racing_statistics") or "")
        earnings = _json_obj(row.get("progeny_earnings_statistics") or "")
        legacy = _json_obj(row.get("legacy_progeny_stats") or "")
        if racing:
            profile["Progeny Racing Statistics"] = racing
        if earnings:
            profile["Progeny Earnings Statistics"] = earnings
        if legacy:
            profile["Legacy Progeny Stats"] = legacy
        profiles[name] = profile
    return profiles


def save_stallion_profiles(master_profiles: dict) -> None:
    """Write profile cards back to stallion_stats. Preserves rank and mares-bred columns."""
    existing = {row["stallion_name"]: row for row in load_table("stallion_stats")}
    rows = []
    for name, data in master_profiles.items():
        prior = existing.get(name, {})
        rows.append({
            "stallion_name": name,
            "farm": data.get("Farm", ""),
            "year_born": data.get("Year Born", ""),
            "stud_duty_year": data.get("Stud Duty Year", ""),
            "stud_fee": data.get("Stud Fee", 0),
            "status": data.get("Status", "active"),
            "surface": data.get("Surface", ""),
            "height": data.get("Height", "N/A"),
            "conformation": data.get("Conformation & Physical Profile", ""),
            "major_wins": data.get("Major Wins", ""),
            "career_highlight": data.get("Career Highlight", ""),
            "race_record": json.dumps(data.get("Race Record", {})),
            "progeny_racing_statistics": json.dumps(data.get("Progeny Racing Statistics", {})) if "Progeny Racing Statistics" in data else "",
            "progeny_earnings_statistics": json.dumps(data.get("Progeny Earnings Statistics", {})) if "Progeny Earnings Statistics" in data else "",
            "legacy_progeny_stats": json.dumps(data.get("Legacy Progeny Stats", {})) if "Legacy Progeny Stats" in data else "",
            "sire_rank": prior.get("sire_rank", ""),
            "mares_bred_2025": prior.get("mares_bred_2025", ""),
        })
    write_table("stallion_stats", rows)


def load_broodmare_sire_rows() -> list[dict]:
    rows = []
    for row in load_table("broodmare_sire_stats"):
        def as_int(value):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return 0

        def as_float(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        rows.append({
            "rank": as_int(row.get("rank")),
            "stallion": row.get("stallion") or "",
            "lineage": row.get("lineage") or "",
            "dams": as_int(row.get("dams")),
            "rnrs": as_int(row.get("rnrs")),
            "wnrs": as_int(row.get("wnrs")),
            "chief_earner": row.get("chief_earner") or "",
            "chief_earners_earnings": as_int(row.get("chief_earners_earnings")),
            "earnings_2026": as_int(row.get("earnings_2026")),
            "cum_swrs": as_int(row.get("cum_swrs")),
            "aei": as_float(row.get("aei")),
            "comp_index": as_float(row.get("comp_index")),
            "cum_foals": as_int(row.get("cum_foals")),
        })
    rows.sort(key=lambda item: item["rank"])
    return rows


def load_broodmare_database() -> dict:
    """Dict shape hypomating_engine expects from BROODMARE_DATABASE."""
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
    for row in load_table("mares_bred"):
        if name_key(row.get("stallion") or "") == clean_search:
            return row
    return None


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
