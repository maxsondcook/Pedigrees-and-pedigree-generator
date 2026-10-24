#!/usr/bin/env python3
"""Build stallion_rankings.db from BloodHorse year-ranking CSVs (2001–2026).

One row per published ranking. Every source column is an attribute of the
Stallion Rankings entity. Published text is kept as printed, including
"-", "N/A", and fee suffixes such as "$250,000M".
"""

from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DB = ROOT / "stallion_rankings.db"
YEAR_DIRS = [str(year) for year in range(2001, 2027)]

COLUMNS = [
    "year",
    "list",
    "table_name",
    "rank",
    "stallion",
    "sire",
    "foaling_year",
    "country",
    "stallion_raw",
    "source_file",
    "stud_fee",
    "stud_fee_season",
    "farm",
    "stud_fee_raw",
    "runners",
    "winners",
    "repeat_winners",
    "stakes_winners",
    "stakes_winners_percent",
    "stakes_winners_raw",
    "stakes_wins",
    "graded_stakes_winners",
    "graded_stakes_winners_percent",
    "graded_stakes_winners_raw",
    "grade1_stakes_winners",
    "grade1_stakes_winners_percent",
    "grade1_stakes_winners_raw",
    "stakes_horses",
    "current_2yos",
    "yearling_average",
    "chief_earner",
    "chief_earner_earnings",
    "chief_earner_raw",
    "year_earnings",
    "earnings_share",
    "dams",
    "cumulative_stakes_winners",
    "cumulative_foals",
    "aei",
    "comparable_index",
    "all_surfaces_runners",
    "all_surfaces_winners",
    "all_surfaces_stakes_winners",
    "turf_runners",
    "turf_winners",
    "turf_stakes_winners",
    "north_america_earnings",
    "europe_dubai_earnings",
    "japan_hong_kong_earnings",
    "region_earnings",
    "international_stakes_winners",
    "international_stakes_horses",
    "crops",
    "average_crop_size",
    "crops_raw",
    "foals",
    "foals_basis",
    "lifetime_yearlings_sold",
    "lifetime_yearling_average",
    "lifetime_yearlings_raw",
    "yearling_window",
    "window_yearlings_sold",
    "window_yearling_average",
    "window_yearlings_raw",
]

AEI_STALLION_RE = re.compile(
    r"^(?P<name>.+?)"
    r"(?:\s+\((?P<cc>[A-Za-z]{2,3})\))?"
    r"\s+\((?P<yy>\d{2}),\s*(?P<sire>[^)]+)\)"
    r"(?:,\s*(?P<farm>.+))?$"
)
FEE_SEASON_RE = re.compile(
    r"(?:'(?P<short>\d{2})|(?P<full>\d{4}))\s+Stud Fee",
    re.I,
)
WINDOW_RE = re.compile(r"(\d{4}[–-]\d{4})")
YEAR_EARNINGS_RE = re.compile(r"^\d{2} Earnings$")

REGION_SUFFIXES = (
    ("northamerica", "North America"),
    ("europeanddubai", "Europe & Dubai"),
    ("europedubai", "Europe & Dubai"),
    ("japanandhongkong", "Japan & Hong Kong"),
    ("japanhongkong", "Japan & Hong Kong"),
)


def norm_header(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\n", " ")).strip()


def compact_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def nonempty(value: str | None) -> str | None:
    if value is None:
        return None
    if not str(value).strip():
        return None
    return value


def title_if_all_caps(name: str) -> str:
    letters = [char for char in name if char.isalpha()]
    if not letters or not all(char.isupper() for char in letters):
        return name
    parts = []
    for token in name.split(" "):
        if re.fullmatch(r"\([A-Z]{2,3}\)", token):
            parts.append(token)
        elif re.fullmatch(r"[A-Z]\.(?:[A-Z]\.)+", token):
            parts.append(token)
        elif "." in token:
            parts.append(".".join(part.capitalize() if part else "" for part in token.split(".")))
        else:
            parts.append(token.capitalize() if token else token)
    return " ".join(parts)


def foaling_from_two_digits(yy: str) -> str:
    year = int(yy)
    return str(2000 + year if year <= 30 else 1900 + year)


def classify_file(filename: str, year: str) -> tuple[str, str]:
    title = filename[len(year):] if filename.startswith(year) else filename
    title = title[: -len(".csv")] if title.endswith(".csv") else title
    title = re.sub(r"^StallionRankings\s*-\s*", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    key = compact_name(title)
    table = ""
    for suffix, region in REGION_SUFFIXES:
        if key.endswith(suffix):
            key = key[: -len(suffix)]
            table = region
            break

    if key.startswith("leadinginternational"):
        rest = key[len("leadinginternational"):]
        if rest in {"sires", ""}:
            list_name = "International"
        elif "first" in rest:
            list_name = "International First-Crop"
        elif "2nd" in rest or "second" in rest:
            list_name = "International Second-Crop"
        elif "3rd" in rest or "third" in rest:
            list_name = "International Third-Crop"
        elif "twoyear" in rest:
            list_name = "International Two-Year-Old"
        else:
            raise ValueError(f"Unrecognized international list in {filename}")
        return list_name, table or "Summary"

    names = {
        "leadingbroodmaresires": "Broodmare",
        "leadingfirstcropsires": "First-Crop",
        "leadingsecondcropsires": "Second-Crop",
        "leadingthirdcropsires": "Third-Crop",
        "leadingtwoyearoldsires": "Two-Year-Old",
        "leadingturfsires": "Turf",
        "leadingsirerankings": "General",
        "leadingsiresbyaei": "Lifetime AEI",
    }
    if key not in names:
        raise ValueError(f"Unrecognized ranking file {filename}")
    if table:
        raise ValueError(f"North American list has a region suffix: {filename}")
    return names[key], ""


def header_kind(header: str) -> str:
    if header in {"#", "Rank"}:
        return "rank"
    if header == "Country":
        return "country"
    if header.lower().startswith("stallion"):
        return "stallion"
    if re.search(r"stud fee", header, re.I):
        return "stud_fee"
    if header == "Current 2YOs":
        return "current_2yos"
    if header == "Rnrs":
        return "runners"
    if header == "Runners":
        return "runners"
    if header == "Wnrs":
        return "wnrs"
    if header == "BT Wnrs":
        return "bt_wnrs"
    if header == "Winners":
        return "winners"
    if header == "Rpt. Wnrs":
        return "repeat_winners"
    if header in {"SWrs", "BT SWrs"}:
        return "swrs"
    if header == "SWnrs":
        return "swnrs"
    if header == "BT SWs":
        return "stakes_wins"
    if header == "GSWrs":
        return "graded_stakes_winners"
    if header == "G1SWrs":
        return "grade1_stakes_winners"
    if header in {"SHs", "BT SHs"}:
        return "stakes_horses"
    if header == "Yearling Average":
        return "yearling_average"
    if header in {"Chief Earner (Earnings)", "Chief Earner, Earnings"}:
        return "chief"
    if YEAR_EARNINGS_RE.match(header):
        return "year_earnings"
    if header == "(%)":
        return "percent"
    if header == "Dams":
        return "dams"
    if header == "Cum. SWrs":
        return "cumulative_stakes_winners"
    if header == "Cum. Foals":
        return "cumulative_foals"
    if header in {"AEI", "AE Index"}:
        return "aei"
    if header in {"Comp Index", "CI"}:
        return "comparable_index"
    if header == "Crops":
        return "crops"
    if header == "Foals":
        return "foals"
    if header == "Avg.":
        return "avg"
    if header == "Sold":
        return "sold"
    if header == "Earnings":
        return "earnings"
    if header == "Crops / Avg Size":
        return "crops_combo"
    if header in {"Named Foals", "N.H. Named Foals"}:
        return "foals_basis"
    if header == "Lifetime Yearlings Sold / Average":
        return "lifetime_yearlings"
    if "Yearlings Sold / Average" in header:
        return "window_yearlings"
    if header == "Stakes Winners":
        return "stakes_combo"
    if header == "Graded Stakes Winners":
        return "graded_combo"
    if header == "Grade 1 Stakes Winners":
        return "grade1_combo"
    raise ValueError(f"Unmapped header {header!r}")


def fee_season(header: str) -> str | None:
    match = FEE_SEASON_RE.search(header)
    if not match:
        return None
    if match.group("full"):
        return match.group("full")
    return str(2000 + int(match.group("short")))


def window_label(header: str) -> str:
    match = WINDOW_RE.search(header)
    if not match:
        raise ValueError(f"Yearling window header has no year range: {header!r}")
    return match.group(1)


def parse_modern_stallion(cell: str) -> tuple[str | None, str | None, str | None]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in cell.splitlines() if line.strip()]
    if not lines:
        return None, None, None
    if len(lines) == 1:
        return lines[0], None, None
    match = re.fullmatch(r"(.+),\s*(\d{4})", lines[1])
    if not match or len(lines) != 2:
        raise ValueError(f"Unparsed stallion cell {cell!r}")
    return lines[0], match.group(1).strip(), match.group(2)


def parse_aei_stallion(cell: str) -> tuple[str | None, str | None, str | None, str | None]:
    text = re.sub(r"\s+", " ", cell.replace("\n", " ")).strip()
    match = AEI_STALLION_RE.match(text)
    if not match:
        raise ValueError(f"Unparsed AEI stallion cell {cell!r}")
    name = match.group("name").strip()
    country = match.group("cc")
    if country:
        name = f"{name} ({country.upper()})"
    name = title_if_all_caps(name)
    farm = match.group("farm")
    farm = re.sub(r"\s+", " ", farm).strip() if farm else None
    return name, match.group("sire").strip(), foaling_from_two_digits(match.group("yy")), farm


def parse_chief(cell: str) -> tuple[str | None, str | None]:
    if "\n" in cell:
        lines = [line.strip() for line in cell.splitlines() if line.strip()]
        if len(lines) != 2:
            raise ValueError(f"Unparsed chief earner {cell!r}")
        return lines[0], lines[1]
    text = cell.strip()
    if text in {"-", "N/A", "NA"}:
        return text, None
    money_only = re.fullmatch(r"\((\$[\d,]+)\)", text)
    if money_only:
        return None, money_only.group(1)
    comma = re.fullmatch(r"(.+?),\s*(\$[\d,]+)", text)
    if comma:
        return comma.group(1).strip(), comma.group(2)
    paren = re.fullmatch(r"(.+?)\s*\((\$[\d,]+)\)", text)
    if paren:
        return paren.group(1).strip(), paren.group(2)
    raise ValueError(f"Unparsed chief earner {cell!r}")


def parse_fee(cell: str) -> tuple[str | None, str | None]:
    parts = [part.strip() for part in re.split(r"[\n\r]+", cell) if part.strip()]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def parse_slash_pair(cell: str, pattern: re.Pattern[str], label: str) -> tuple[str, str]:
    match = pattern.fullmatch(cell.strip())
    if not match:
        raise ValueError(f"Unparsed {label} cell {cell!r}")
    return match.group(1), match.group(2)


CROPS_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
YEARLING_RE = re.compile(r"([\d,]+)\s*/\s*(\$[\d,]+)")
STAKES_RE = re.compile(r"([\d,]+)\s*-\s*([\d.]+%)")


def assign_column(list_name: str, table: str, kind: str, occurrence: int, header: str) -> tuple[str, str]:
    """Return (mode, column). mode is copy or a parser name. column is the copy or raw column."""
    intl_summary = table == "Summary"
    intl_region = table in {"North America", "Europe & Dubai", "Japan & Hong Kong"}
    aei = list_name == "Lifetime AEI"
    turf = list_name == "Turf"

    if kind == "rank":
        return "copy", "rank"
    if kind == "country":
        return "copy", "country"
    if kind == "stallion":
        return ("aei_stallion" if header.startswith("Stallion (Foreign") else "stallion"), "stallion_raw"
    if kind == "stud_fee":
        return "fee", "stud_fee_raw"
    if kind == "current_2yos":
        return "copy", "current_2yos"
    if kind == "repeat_winners":
        return "copy", "repeat_winners"
    if kind == "stakes_wins":
        return "copy", "stakes_wins"
    if kind == "graded_stakes_winners":
        return "copy", "graded_stakes_winners"
    if kind == "grade1_stakes_winners":
        return "copy", "grade1_stakes_winners"
    if kind == "yearling_average":
        return "copy", "yearling_average"
    if kind == "chief":
        return "chief", "chief_earner_raw"
    if kind == "year_earnings":
        return "copy", "year_earnings"
    if kind == "dams":
        return "copy", "dams"
    if kind == "cumulative_stakes_winners":
        return "copy", "cumulative_stakes_winners"
    if kind == "cumulative_foals":
        return "copy", "cumulative_foals"
    if kind == "aei":
        return "copy", "aei"
    if kind == "comparable_index":
        return "copy", "comparable_index"
    if kind == "crops":
        return "copy", "crops"
    if kind == "foals":
        return "copy", "foals"
    if kind == "avg":
        if not aei:
            raise ValueError(f"Avg. column outside Lifetime AEI ({list_name})")
        if occurrence == 1:
            return "copy", "lifetime_yearling_average"
        if occurrence == 2:
            return "copy", "window_yearling_average"
        raise ValueError("Unexpected extra Avg. column on Lifetime AEI")
    if kind == "sold":
        if not aei:
            raise ValueError(f"Sold column outside Lifetime AEI ({list_name})")
        if occurrence == 1:
            return "copy", "lifetime_yearlings_sold"
        if occurrence == 2:
            return "copy", "window_yearlings_sold"
        raise ValueError("Unexpected extra Sold column on Lifetime AEI")
    if kind == "crops_combo":
        return "crops_combo", "crops_raw"
    if kind == "foals_basis":
        return "foals_basis", "foals"
    if kind == "lifetime_yearlings":
        return "lifetime_yearlings", "lifetime_yearlings_raw"
    if kind == "window_yearlings":
        return "window_yearlings", "window_yearlings_raw"
    if kind == "stakes_combo":
        return "stakes_combo", "stakes_winners_raw"
    if kind == "graded_combo":
        return "graded_combo", "graded_stakes_winners_raw"
    if kind == "grade1_combo":
        return "grade1_combo", "grade1_stakes_winners_raw"

    if kind == "runners":
        if turf:
            column = "all_surfaces_runners" if occurrence == 1 else "turf_runners"
            if occurrence > 2:
                raise ValueError("Unexpected extra runners column on Turf")
            return "copy", column
        return "copy", "runners"
    if kind == "aei_wnrs":
        columns = ("stakes_winners", "graded_stakes_winners", "grade1_stakes_winners")
        if occurrence > 3:
            raise ValueError("Unexpected extra winner column on Lifetime AEI")
        return "copy", columns[occurrence - 1]
    if kind in {"wnrs", "winners"}:
        if turf:
            column = "all_surfaces_winners" if occurrence == 1 else "turf_winners"
            if occurrence > 2:
                raise ValueError("Unexpected extra winners column on Turf")
            return "copy", column
        return "copy", "winners"
    if kind == "bt_wnrs":
        if not aei or occurrence != 1:
            raise ValueError(f"Unexpected BT Wnrs on {list_name}")
        return "copy", "stakes_winners"
    if kind == "swrs":
        if turf:
            column = "all_surfaces_stakes_winners" if occurrence == 1 else "turf_stakes_winners"
            if occurrence > 2:
                raise ValueError("Unexpected extra stakes winners column on Turf")
            return "copy", column
        return "copy", "stakes_winners"
    if kind == "swnrs":
        if not intl_region:
            raise ValueError(f"SWnrs outside an international region table ({list_name} / {table})")
        if occurrence == 1:
            return "copy", "stakes_winners"
        if occurrence == 2:
            return "copy", "international_stakes_winners"
        raise ValueError("Unexpected extra SWnrs column")
    if kind == "stakes_horses":
        if intl_region:
            return "copy", "international_stakes_horses"
        return "copy", "stakes_horses"
    if kind == "percent":
        if aei:
            columns = (
                "stakes_winners_percent",
                "graded_stakes_winners_percent",
                "grade1_stakes_winners_percent",
            )
            if occurrence > 3:
                raise ValueError("Unexpected extra percent column on Lifetime AEI")
            return "copy", columns[occurrence - 1]
        if list_name in {"Two-Year-Old", "Turf"}:
            return "copy", "earnings_share"
        raise ValueError(f"(%) column on {list_name} is not a known earnings share or AEI percent")
    if kind == "earnings":
        if intl_summary:
            columns = (
                "north_america_earnings",
                "europe_dubai_earnings",
                "japan_hong_kong_earnings",
            )
            if occurrence > 3:
                raise ValueError("Unexpected extra earnings column on an international summary")
            return "copy", columns[occurrence - 1]
        if intl_region and occurrence == 1:
            return "copy", "region_earnings"
        raise ValueError(f"Earnings column on {list_name} / {table or 'North America'} is unmapped")
    raise ValueError(f"No column for {kind} on {list_name}")


def check_group_labels(list_name: str, table: str, group: list[str] | None, headers: list[str]) -> None:
    if not group:
        return
    labels = [norm_header(cell) for cell in group]
    if list_name.startswith("International") and table == "Summary" and len(labels) == len(headers):
        present = [label for label in labels if label]
        expected = ["North America", "Europe & Dubai", "Japan & Hong Kong", "International"]
        if present != expected:
            raise ValueError(f"International summary groups {present} != {expected}")
    if list_name == "Turf" and len(labels) == len(headers):
        present = [label for label in labels if label]
        if present != ["All Surfaces", "Turf"]:
            raise ValueError(f"Turf groups {present}")
    if table in {"North America", "Europe & Dubai", "Japan & Hong Kong"} and len(labels) == len(headers):
        present = [label for label in labels if label]
        if present != [table, "International"]:
            raise ValueError(f"Region groups {present} for table {table}")


def load_file(path: Path, year: str) -> list[dict[str, str | None]]:
    list_name, table = classify_file(path.name, year)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    header_index = next(
        (index for index, row in enumerate(rows[:4]) if row and row[0].strip() in {"#", "Rank"}),
        None,
    )
    if header_index is None:
        raise ValueError(f"No header row in {path.name}")
    headers = [norm_header(cell) for cell in rows[header_index]]
    group = rows[header_index - 1] if header_index else None
    check_group_labels(list_name, table, group, headers)

    occurrences: dict[str, int] = {}
    assigned: list[tuple[str, str, str]] = []
    for header in headers:
        kind = header_kind(header)
        if list_name == "Lifetime AEI" and kind in {"wnrs", "bt_wnrs"}:
            kind = "aei_wnrs"
        occurrences[kind] = occurrences.get(kind, 0) + 1
        mode, column = assign_column(list_name, table, kind, occurrences[kind], header)
        assigned.append((mode, column, header))

    source_file = f"{year}/{path.name}"
    loaded: list[dict[str, str | None]] = []
    data_rows = 0
    for row in rows[header_index + 1 :]:
        if not any((cell or "").strip() for cell in row):
            continue
        data_rows += 1
        if len(row) != len(headers):
            raise ValueError(f"{path.name} row has {len(row)} cells, header has {len(headers)}")
        record: dict[str, str | None] = {column: None for column in COLUMNS}
        record["year"] = year
        record["list"] = list_name
        record["table_name"] = table or None
        record["source_file"] = source_file
        covered: set[int] = set()
        for index, ((mode, column, header), cell) in enumerate(zip(assigned, row)):
            if not (cell or "").strip():
                continue
            covered.add(index)
            if mode == "copy":
                record[column] = cell
            elif mode == "stallion":
                record["stallion_raw"] = cell
                name, sire, foaling = parse_modern_stallion(cell)
                record["stallion"] = name
                record["sire"] = sire
                record["foaling_year"] = foaling
            elif mode == "aei_stallion":
                record["stallion_raw"] = cell
                name, sire, foaling, farm = parse_aei_stallion(cell)
                record["stallion"] = name
                record["sire"] = sire
                record["foaling_year"] = foaling
                record["farm"] = farm
            elif mode == "fee":
                record["stud_fee_raw"] = cell
                fee, farm = parse_fee(cell)
                record["stud_fee"] = fee
                record["stud_fee_season"] = fee_season(header)
                if farm:
                    record["farm"] = farm
            elif mode == "chief":
                record["chief_earner_raw"] = cell
                earner, earnings = parse_chief(cell)
                record["chief_earner"] = earner
                record["chief_earner_earnings"] = earnings
            elif mode == "crops_combo":
                record["crops_raw"] = cell
                crops, average = parse_slash_pair(cell, CROPS_RE, "crops")
                record["crops"] = crops
                record["average_crop_size"] = average
            elif mode == "foals_basis":
                record["foals"] = cell
                record["foals_basis"] = header
            elif mode == "lifetime_yearlings":
                record["lifetime_yearlings_raw"] = cell
                sold, average = parse_slash_pair(cell, YEARLING_RE, "lifetime yearlings")
                record["lifetime_yearlings_sold"] = sold
                record["lifetime_yearling_average"] = average
            elif mode == "window_yearlings":
                record["window_yearlings_raw"] = cell
                record["yearling_window"] = window_label(header)
                sold, average = parse_slash_pair(cell, YEARLING_RE, "window yearlings")
                record["window_yearlings_sold"] = sold
                record["window_yearling_average"] = average
            elif mode == "stakes_combo":
                record["stakes_winners_raw"] = cell
                count, percent = parse_slash_pair(cell, STAKES_RE, "stakes winners")
                record["stakes_winners"] = count
                record["stakes_winners_percent"] = percent
            elif mode == "graded_combo":
                record["graded_stakes_winners_raw"] = cell
                count, percent = parse_slash_pair(cell, STAKES_RE, "graded stakes winners")
                record["graded_stakes_winners"] = count
                record["graded_stakes_winners_percent"] = percent
            elif mode == "grade1_combo":
                record["grade1_stakes_winners_raw"] = cell
                count, percent = parse_slash_pair(cell, STAKES_RE, "grade 1 stakes winners")
                record["grade1_stakes_winners"] = count
                record["grade1_stakes_winners_percent"] = percent
            else:
                raise ValueError(f"Unknown mode {mode}")
        if (
            list_name == "Lifetime AEI"
            and record["yearling_window"] is None
            and (record["window_yearling_average"] or record["window_yearlings_sold"])
        ):
            record["yearling_window"] = "3-Year"
        missing = [
            headers[index]
            for index, cell in enumerate(row)
            if (cell or "").strip() and index not in covered
        ]
        if missing:
            raise ValueError(f"{path.name} left source cells unstored: {missing}")
        for index in covered:
            cell = row[index]
            mode, column, _header = assigned[index]
            stored = record[column]
            if stored != cell:
                raise ValueError(
                    f"{path.name} column {headers[index]!r} stored {stored!r} instead of {cell!r}"
                )
        loaded.append(record)
    if len(loaded) != data_rows:
        raise ValueError(f"{path.name} loaded {len(loaded)} of {data_rows} data rows")
    return loaded


def create_database(records: list[dict[str, str | None]]) -> None:
    if OUT_DB.exists():
        OUT_DB.unlink()
    connection = sqlite3.connect(OUT_DB)
    try:
        column_sql = ", ".join(f"{column} TEXT" for column in COLUMNS)
        connection.execute(
            f"CREATE TABLE stallion_rankings (id INTEGER PRIMARY KEY, {column_sql})"
        )
        placeholders = ", ".join("?" for _ in COLUMNS)
        connection.executemany(
            f"INSERT INTO stallion_rankings ({', '.join(COLUMNS)}) VALUES ({placeholders})",
            [tuple(record[column] for column in COLUMNS) for record in records],
        )
        connection.execute(
            "CREATE INDEX idx_stallion_rankings_year_list ON stallion_rankings (year, list, table_name)"
        )
        connection.execute(
            "CREATE INDEX idx_stallion_rankings_stallion ON stallion_rankings (stallion)"
        )
        connection.execute(
            "CREATE INDEX idx_stallion_rankings_year_stallion ON stallion_rankings (year, stallion)"
        )
        connection.commit()
    finally:
        connection.close()


def build() -> None:
    records: list[dict[str, str | None]] = []
    files = 0
    for year in YEAR_DIRS:
        folder = ROOT / year
        paths = sorted(path for path in folder.glob("*.csv"))
        if len(paths) != 28:
            raise ValueError(f"{year} has {len(paths)} CSV files, expected 28")
        for path in paths:
            records.extend(load_file(path, year))
            files += 1
    if files != 728:
        raise ValueError(f"Loaded {files} files, expected 728")
    create_database(records)
    connection = sqlite3.connect(OUT_DB)
    try:
        count = connection.execute("SELECT COUNT(*) FROM stallion_rankings").fetchone()[0]
        lists = connection.execute("SELECT COUNT(DISTINCT list) FROM stallion_rankings").fetchone()[0]
        years = connection.execute("SELECT MIN(year), MAX(year) FROM stallion_rankings").fetchone()
    finally:
        connection.close()
    if count != len(records):
        raise ValueError(f"Database has {count} rows after inserting {len(records)}")
    print(f"Wrote {OUT_DB}")
    print(f"Files: {files}")
    print(f"Rows: {count}")
    print(f"Lists: {lists}")
    print(f"Years: {years[0]}–{years[1]}")


if __name__ == "__main__":
    build()
