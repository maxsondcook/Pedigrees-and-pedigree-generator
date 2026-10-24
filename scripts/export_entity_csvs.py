#!/usr/bin/env python3
"""Export the live entities (except pedigrees) to one CSV each under data/.

Sources stay where they are. This writes the files you load into Railway.
Pedigrees stay in pedigrees_database.py. Stallion cards and
mares_bred_2025_by_stallion.py are not exported.

    python3 scripts/export_entity_csvs.py
"""

from __future__ import annotations

import csv
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))


def clean_horse_name(name: str) -> str:
    if not name or not isinstance(name, str):
        return ""
    cleaned = re.sub(r"\(.*?\)", "", name)
    cleaned = cleaned.replace(".", "").replace("'", "").replace(",", "")
    cleaned = " ".join(cleaned.split())
    return cleaned.strip().upper()


def cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def write_csv(path: Path, fieldnames: list[str], rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: cell(row.get(key) if isinstance(row, dict) else row[key]) for key in fieldnames})
            count += 1
    tmp.replace(path)
    print(f"{path.relative_to(ROOT)}: {count} rows")
    return count


def copy_stud_fees() -> None:
    source = ROOT / "stallion_rankings_data" / "stud_fee_database.csv"
    fieldnames = ["Year", "Stallion", "Stud Fee", "Farm", "Source List", "Notes"]
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    write_csv(DATA / "stud_fees.csv", fieldnames, rows)


def export_equibase() -> None:
    """Write race horses, seasons, and starts from equibase_results.db."""
    db_path = ROOT / "equibase_results.db"
    if not db_path.exists():
        print("equibase_results.db is missing; race CSVs were not written")
        return

    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        for table, filename in (
            ("horses", "race_horses.csv"),
            ("year_stats", "race_seasons.csv"),
            ("starts", "race_starts.csv"),
        ):
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            cursor = connection.execute(f"SELECT * FROM {table} ORDER BY id")

            def stream():
                for record in cursor:
                    yield {column: record[column] for column in columns}

            write_csv(DATA / filename, columns, stream())
    finally:
        connection.close()


def export_breeding_seasons() -> None:
    fieldnames = [
        "breeding_year",
        "stallion",
        "mares_bred",
        "reports_received",
        "live_foals",
        "live_foal_pct",
        "state",
        "source",
    ]
    rows_by_key: dict[tuple[int, str], dict] = {}
    folder = ROOT / "live_foal_statistics"
    for path in sorted(folder.glob("*.csv")):
        match = re.search(r"(\d{4}) Breeding Season", path.name)
        if not match:
            continue
        year = int(match.group(1))
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

    rows = [rows_by_key[key] for key in sorted(rows_by_key, key=lambda item: (item[0], item[1]))]
    write_csv(DATA / "breeding_seasons.csv", fieldnames, rows)


def export_rankings() -> None:
    builder_path = ROOT / "stallion_rankings_data" / "build_stallion_rankings_database.py"
    spec = importlib.util.spec_from_file_location("build_stallion_rankings_database", builder_path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    records = []
    problems = []
    for year in builder.YEAR_DIRS:
        folder = builder.ROOT / year
        if not folder.is_dir():
            problems.append(f"missing folder {year}")
            continue
        for path in sorted(folder.glob("*.csv")):
            try:
                records.extend(builder.load_file(path, year))
            except Exception as exc:
                problems.append(f"{path.name}: {exc}")
    write_csv(DATA / "stallion_rankings.csv", builder.COLUMNS, records)
    for problem in problems:
        print(f"  ranking skip: {problem}")


def export_graded_stakes() -> None:
    source = ROOT / "graded_stakes_winners.csv"
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for extra in ("Race Year", "Grade"):
            if extra not in fieldnames:
                fieldnames.append(extra)

        def stream():
            for record in reader:
                iso = (record.get("Date (ISO)") or "").strip()
                year = iso[:4] if len(iso) >= 4 and iso[:4].isdigit() else ""
                if not year:
                    found = re.search(r"\b((?:19|20)\d{2})\b", record.get("Date") or "")
                    year = found.group(1) if found else (record.get("Race Year") or "")
                record["Race Year"] = year
                record["Grade"] = (record.get("Group") or record.get("Grade") or "").strip()
                yield record

        write_csv(DATA / "graded_stakes.csv", fieldnames, stream())


def export_sales() -> None:
    import sales_history

    fieldnames = [
        "catalog_year",
        "catalog_title",
        "source_file",
        "hip",
        "name",
        "name_key",
        "sex",
        "sex_letter",
        "sire",
        "sire_key",
        "dam",
        "dam_key",
        "damsire",
        "damsire_key",
        "color",
        "consignor",
        "purchaser",
        "barn",
        "foaled_location",
        "birth_year",
        "price_raw",
        "price_num",
        "is_rna",
        "is_out",
        "is_fasig",
    ]
    sales_dir = ROOT / "sales_data"
    files = sorted(sales_dir.glob("*.csv"))

    def stream():
        for index, path in enumerate(files, start=1):
            year_match = re.search(r"\d{4}", path.name)
            catalog_year = year_match.group(0) if year_match else ""
            title = sales_history.clean_title(path.name)
            try:
                lots = sales_history.load_and_process_csv(path)
            except Exception as exc:
                print(f"  sales skip: {path.name}: {exc}")
                continue
            if index % 40 == 0 or index == len(files):
                print(f"  sales catalogs {index}/{len(files)}", flush=True)
            for lot in lots:
                yield {
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
                }

    write_csv(DATA / "sales_lots.csv", fieldnames, stream())


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    copy_stud_fees()
    export_equibase()
    export_breeding_seasons()
    export_rankings()
    export_graded_stakes()
    export_sales()
    leftover = DATA / "stallion_profiles.csv"
    if leftover.exists():
        leftover.unlink()


if __name__ == "__main__":
    main()
