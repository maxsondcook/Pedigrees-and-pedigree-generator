#!/usr/bin/env python3
"""Scrape staging → data/*.csv (the 8 sample tables).

Safe to run while :3000/:8000 are up: every write is tmp + os.replace, and
crossr_core.sample_db reloads on mtime change.

Usage:
    # Full rebuild from scraper staging (idempotent upsert / partition replace)
    python3 scripts/pipeline/run.py all

    # One table
    python3 scripts/pipeline/run.py stud_fees
    python3 scripts/pipeline/run.py race
    python3 scripts/pipeline/run.py breeding_seasons
    python3 scripts/pipeline/run.py stallion_rankings
    python3 scripts/pipeline/run.py graded_stakes
    python3 scripts/pipeline/run.py sales_lots

Scraper → CSV map is documented in docs (project store) and SCRAPER_MAP below.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crossr_core import sample_db  # noqa: E402

SCRAPER_MAP = {
    "stud_fees": [
        "fee_and_standing_location.py (Racing Post fees)",
        "stallion_rankings_data/build_stud_fee_database.py",
        "stallion_rankings_data/bloodhorse_sirelists/*",
    ],
    "race_horses": ["equibase_scraper → equibase_results.db staging → race_horses"],
    "race_seasons": ["equibase_scraper → equibase_results.db staging → race_seasons"],
    "race_starts": ["equibase_scraper → equibase_results.db staging → race_starts"],
    "breeding_seasons": ["live_foal_statistics/*.csv (Jockey Club breeding season dumps)"],
    "stallion_rankings": [
        "stallion_rankings_data/bloodhorse_sirelists/scrape_sirelists.py",
        "stallion_rankings_data/<year>/*.csv",
    ],
    "graded_stakes": [
        "ifha_scraper (IFHA graded/group stakes)",
        "graded_stakes.py helpers",
    ],
    "sales_lots": [
        "sales_data/*.csv catalog scrapes",
        "sales_history.py normalize",
    ],
    "pedigrees_database.py": ["pq_scraper (Pedigree Query)"],
}


def clean_horse_name(name: str) -> str:
    return sample_db.name_key(name)


def ingest_stud_fees() -> dict:
    """Upsert from stallion_rankings_data/stud_fee_database.csv and optional JSON."""
    fieldnames = sample_db.TABLES["stud_fees"]
    incoming: list[dict] = []
    csv_path = ROOT / "stallion_rankings_data" / "stud_fee_database.csv"
    if csv_path.exists():
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            for record in csv.DictReader(handle):
                incoming.append({k: record.get(k, "") for k in fieldnames})
    json_path = ROOT / "stud_fee_database.json"
    if json_path.exists():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        # Shapes vary: {stallion: {year: fee}} or list of rows
        if isinstance(payload, dict):
            for stallion, years in payload.items():
                if not isinstance(years, dict):
                    continue
                for year, fee in years.items():
                    incoming.append({
                        "Year": str(year),
                        "Stallion": stallion,
                        "Stud Fee": str(fee),
                        "Farm": "",
                        "Source List": "stud_fee_database.json",
                        "Notes": "",
                    })
    return sample_db.upsert_rows("stud_fees", incoming)


def ingest_race_from_equibase_db() -> dict:
    """Upsert horses/year_stats/starts from equibase_results.db staging (if present)."""
    db_path = ROOT / "equibase_results.db"
    # Also accept Going_to_delete staging during transition
    if not db_path.exists():
        alt = ROOT / "Going_to_delete" / "equibase_results.db"
        if alt.exists():
            db_path = alt
    if not db_path.exists():
        return {"skipped": "equibase_results.db missing"}

    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    out = {}
    try:
        mapping = (
            ("horses", "race_horses"),
            ("year_stats", "race_seasons"),
            ("starts", "race_starts"),
        )
        for sqlite_table, sample_table in mapping:
            try:
                columns = [row[1] for row in connection.execute(f"PRAGMA table_info({sqlite_table})")]
            except sqlite3.Error:
                out[sample_table] = {"skipped": f"no table {sqlite_table}"}
                continue
            wanted = sample_db.TABLES[sample_table]
            rows = []
            for record in connection.execute(f"SELECT * FROM {sqlite_table}"):
                raw = {column: record[column] for column in columns}
                rows.append({col: raw.get(col, "") for col in wanted})
            out[sample_table] = sample_db.upsert_rows(sample_table, rows)
    finally:
        connection.close()
    return out


def ingest_breeding_seasons() -> dict:
    fieldnames = sample_db.TABLES["breeding_seasons"]
    rows_by_key: dict[tuple, dict] = {}
    folder = ROOT / "live_foal_statistics"
    if not folder.is_dir():
        return {"skipped": "live_foal_statistics missing"}
    for path in sorted(folder.glob("*.csv")):
        match = re.search(r"(\d{4}) Breeding Season", path.name)
        if not match:
            continue
        year = match.group(1)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for record in csv.DictReader(handle):
                stallion = (record.get("Stallion") or "").strip()
                name = clean_horse_name(stallion)
                if not name:
                    continue
                rows_by_key[(year, name)] = {
                    "breeding_year": year,
                    "stallion": stallion,
                    "mares_bred": (record.get("Mares Bred") or "").strip(),
                    "reports_received": (record.get("Reports Received") or "").strip(),
                    "live_foals": (record.get("Live Foals") or "").strip(),
                    "live_foal_pct": (record.get("Live Foal %") or "").strip(),
                    "state": (record.get("State") or "").strip(),
                    "source": path.name,
                }
    return sample_db.upsert_rows("breeding_seasons", list(rows_by_key.values()))


def ingest_stallion_rankings() -> dict:
    builder_path = ROOT / "stallion_rankings_data" / "build_stallion_rankings_database.py"
    if not builder_path.exists():
        return {"skipped": "build_stallion_rankings_database.py missing"}
    spec = importlib.util.spec_from_file_location("build_stallion_rankings_database", builder_path)
    builder = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(builder)

    records = []
    for year in builder.YEAR_DIRS:
        folder = builder.ROOT / year
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.csv")):
            try:
                records.extend(builder.load_file(path, year))
            except Exception as exc:
                print(f"  ranking skip {path.name}: {exc}")
    # Full replace is correct: ranking dumps are complete year/list snapshots
    return {"total": sample_db.atomic_write_table("stallion_rankings", records), "rows": len(records)}


def ingest_graded_stakes() -> dict:
    """Prefer IFHA normalized export; fall back to root graded_stakes_winners.csv staging."""
    fieldnames = sample_db.TABLES["graded_stakes"]
    incoming: list[dict] = []

    ifha_csv = ROOT / "ifha_scraper" / "ifha_graded_stakes_2003_2026.csv"
    root_csv = ROOT / "Going_to_delete" / "graded_stakes_winners.csv"
    legacy_csv = ROOT / "graded_stakes_winners.csv"
    source = ifha_csv if ifha_csv.exists() else (root_csv if root_csv.exists() else legacy_csv)
    if not source.exists():
        return {"skipped": "no graded stakes staging CSV"}

    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            iso = (record.get("Date (ISO)") or "").strip()
            year = iso[:4] if len(iso) >= 4 and iso[:4].isdigit() else ""
            if not year:
                found = re.search(r"\b((?:19|20)\d{2})\b", record.get("Date") or "")
                year = found.group(1) if found else (record.get("Race Year") or "")
            row = {col: record.get(col, "") for col in fieldnames}
            row["Race Year"] = year
            row["Grade"] = (record.get("Group") or record.get("Grade") or "").strip()
            # Map Place: winners-only dumps have no Place → treat as 1
            if not str(row.get("Place") or "").strip():
                row["Place"] = "1"
            if not row.get("race_id"):
                row["race_id"] = "|".join([
                    row.get("Race Name", ""),
                    row.get("Date (ISO)") or row.get("Date") or "",
                    row.get("Track", ""),
                ])
            incoming.append(row)
    return sample_db.upsert_rows("graded_stakes", incoming)


def sales_rows(path: Path) -> list[dict]:
    """sales_lots rows for one catalog CSV in sales_data/."""
    import sales_history

    year_match = re.search(r"\d{4}", path.name)
    catalog_year = year_match.group(0) if year_match else ""
    title = sales_history.clean_title(path.name)
    rows = []
    for lot in sales_history.load_and_process_csv(path):
        rows.append({
            "catalog_year": catalog_year,
            "catalog_title": title,
            "source_file": path.name,
            "hip": lot.get("hip"),
            "name": lot.get("name"),
            "name_key": sales_history.clean_search_string(lot.get("name")),
            "sex": lot.get("sex"),
            "sex_letter": lot.get("sex_letter"),
            "sire": lot.get("sire"),
            "sire_key": sales_history.clean_search_string(lot.get("sire")),
            "dam": lot.get("dam"),
            "dam_key": sales_history.clean_search_string(lot.get("dam")),
            "damsire": lot.get("damsire"),
            "damsire_key": sales_history.clean_search_string(lot.get("damsire")),
            "color": lot.get("color"),
            "consignor": lot.get("consignor"),
            "purchaser": lot.get("purchaser"),
            "barn": lot.get("barn"),
            "foaled_location": lot.get("foaled_location"),
            "birth_year": lot.get("birth_year"),
            "price_raw": lot.get("price_raw"),
            "price_num": lot.get("price_num"),
            "is_rna": lot.get("is_rna"),
            "is_out": lot.get("is_out"),
            "is_fasig": lot.get("is_fasig"),
        })
    return rows


def ingest_sales_lots() -> dict:
    sales_dir = ROOT / "sales_data"
    if not sales_dir.is_dir():
        return {"skipped": "sales_data missing"}
    incoming = []
    for path in sorted(sales_dir.glob("*.csv")):
        try:
            incoming.extend(sales_rows(path))
        except Exception as exc:
            print(f"  sales skip {path.name}: {exc}")
            continue
    # Partition-replace by source_file would be ideal per catalog; full upsert is safe/idempotent
    return sample_db.upsert_rows("sales_lots", incoming)


COMMANDS = {
    "stud_fees": ingest_stud_fees,
    "race": ingest_race_from_equibase_db,
    "breeding_seasons": ingest_breeding_seasons,
    "stallion_rankings": ingest_stallion_rankings,
    "graded_stakes": ingest_graded_stakes,
    "sales_lots": ingest_sales_lots,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge scraper staging into the 8 sample CSVs")
    parser.add_argument(
        "target",
        nargs="?",
        default="all",
        choices=["all", *COMMANDS.keys(), "map"],
        help="Which sample table group to refresh",
    )
    args = parser.parse_args()
    if args.target == "map":
        for table, scrapers in SCRAPER_MAP.items():
            print(f"{table}:")
            for s in scrapers:
                print(f"  - {s}")
        return

    sample_db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    targets = list(COMMANDS) if args.target == "all" else [args.target]
    for name in targets:
        print(f"==> {name}", flush=True)
        result = COMMANDS[name]()
        print(f"    {result}", flush=True)
    print("done")


if __name__ == "__main__":
    main()
