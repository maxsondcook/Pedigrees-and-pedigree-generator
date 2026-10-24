"""Canonical runtime store: the 8 sample CSVs under data/ (+ pedigrees_database.py).

Scrapers and export scripts write here with atomic replace. The API reloads when
mtime changes so :8000 can keep serving while scrapes merge new rows.
"""

from __future__ import annotations

import csv
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("CROSSR_SAMPLE_DATA", str(ROOT / "data")))

# Exact eight sample-database tables (filenames without .csv).
TABLES = {
    "stud_fees": ["Year", "Stallion", "Stud Fee", "Farm", "Source List", "Notes"],
    "race_horses": [
        "id", "pedigree_key", "name_key", "foal_year", "display_name", "foaled_in",
        "breed", "color", "sex", "foaled", "sire", "sire_refno", "dam", "dam_refno",
        "damsire", "damsire_refno", "jockey", "trainer", "owner", "breeder",
        "best_class", "equibase_refno", "registry", "profile_url", "status",
        "detail", "fetched_at", "queue_batch",
    ],
    "race_seasons": [
        "id", "horse_id", "year", "starts", "firsts", "seconds", "thirds",
        "highest_esf", "earnings", "earnings_per_start",
    ],
    "race_starts": [
        "id", "horse_id", "race_date", "track", "track_code", "country",
        "race_number", "race_name", "grade", "breed", "place", "esf",
        "stakes_id", "chart_url", "video_url",
    ],
    "breeding_seasons": [
        "breeding_year", "stallion", "mares_bred", "reports_received",
        "live_foals", "live_foal_pct", "state", "source",
    ],
    "stallion_rankings": [
        "year", "list", "table_name", "rank", "stallion", "sire", "foaling_year",
        "country", "stallion_raw", "source_file", "stud_fee", "stud_fee_season",
        "farm", "stud_fee_raw", "runners", "winners", "repeat_winners",
        "stakes_winners", "stakes_winners_percent", "stakes_winners_raw",
        "stakes_wins", "graded_stakes_winners", "graded_stakes_winners_percent",
        "graded_stakes_winners_raw", "grade1_stakes_winners",
        "grade1_stakes_winners_percent", "grade1_stakes_winners_raw",
        "stakes_horses", "current_2yos", "yearling_average", "chief_earner",
        "chief_earner_earnings", "chief_earner_raw", "year_earnings",
        "earnings_share", "dams", "cumulative_stakes_winners", "cumulative_foals",
        "aei", "comparable_index", "all_surfaces_runners", "all_surfaces_winners",
        "all_surfaces_stakes_winners", "turf_runners", "turf_winners",
        "turf_stakes_winners", "north_america_earnings", "europe_dubai_earnings",
        "japan_hong_kong_earnings", "region_earnings",
        "international_stakes_winners", "international_stakes_horses", "crops",
        "average_crop_size", "crops_raw", "foals", "foals_basis",
        "lifetime_yearlings_sold", "lifetime_yearling_average",
        "lifetime_yearlings_raw", "yearling_window", "window_yearlings_sold",
        "window_yearling_average", "window_yearlings_raw",
    ],
    "graded_stakes": [
        "Race Name", "Horse Name", "Year Foaled", "Sex", "Place", "Country",
        "Track", "Date", "Distance", "Age", "Purse", "Group", "Race Conditions",
        "Date (ISO)", "Purse Source", "Purse (Local)", "Purse Currency",
        "Distance (Metres)", "Colour", "Jockey", "Horse Country Suffix",
        "Foaling Year", "race_id", "Race Year", "Grade",
    ],
    "sales_lots": [
        "catalog_year", "catalog_title", "source_file", "hip", "name", "name_key",
        "sex", "sex_letter", "sire", "sire_key", "dam", "dam_key", "damsire",
        "damsire_key", "color", "consignor", "purchaser", "barn",
        "foaled_location", "birth_year", "price_raw", "price_num", "is_rna",
        "is_out", "is_fasig",
    ],
}

# Upsert identity keys per table (columns that uniquely identify a row).
UPSERT_KEYS = {
    "stud_fees": ("Year", "Stallion", "Source List"),
    "race_horses": ("id",),
    "race_seasons": ("id",),
    "race_starts": ("id",),
    "breeding_seasons": ("breeding_year", "stallion"),
    "stallion_rankings": ("year", "list", "table_name", "rank", "stallion", "source_file"),
    "graded_stakes": ("race_id", "Horse Name", "Place", "Date (ISO)"),
    "sales_lots": ("source_file", "hip", "name_key"),
}

_LOCK = threading.RLock()
_ROWS: dict[str, list[dict]] = {}
_MTIME: dict[str, float] = {}
_SALES_MEM: sqlite3.Connection | None = None
_SALES_MTIME: float | None = None
_RANK_MEM: sqlite3.Connection | None = None
_RANK_MTIME: float | None = None


def csv_path(table: str) -> Path:
    if table not in TABLES:
        raise KeyError(f"Unknown sample table {table!r}; expected one of {sorted(TABLES)}")
    return DATA_DIR / f"{table}.csv"


def name_key(name: str) -> str:
    if not name or not isinstance(name, str):
        return ""
    cleaned = re.sub(r"\(.*?\)", "", name)
    cleaned = cleaned.replace(".", "").replace("'", "").replace(",", "").replace("’", "")
    return " ".join(cleaned.split()).strip().upper()


def broodmare_clean_horse_name(name: str) -> str:
    if not name or not isinstance(name, str):
        return ""
    cleaned = re.sub(r"\(.*?\)", "", name)
    cleaned = cleaned.replace(".", "")
    return " ".join(cleaned.split()).strip().lower()


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _read_csv(table: str) -> list[dict]:
    path = csv_path(table)
    columns = TABLES[table]
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for raw in reader:
            rows.append({col: (raw.get(col) if raw.get(col) is not None else "") for col in columns})
        return rows


def _mtime(table: str) -> float:
    path = csv_path(table)
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def load_table(table: str, refresh: bool = False) -> list[dict]:
    """Return rows for one of the 8 CSVs. Reloads when the file mtime changes."""
    with _LOCK:
        mtime = _mtime(table)
        if refresh or table not in _ROWS or _MTIME.get(table) != mtime:
            _ROWS[table] = _read_csv(table)
            _MTIME[table] = mtime
        return list(_ROWS[table])


def invalidate(table: str | None = None) -> None:
    with _LOCK:
        if table is None:
            _ROWS.clear()
            _MTIME.clear()
            global _SALES_MEM, _SALES_MTIME, _RANK_MEM, _RANK_MTIME
            if _SALES_MEM is not None:
                _SALES_MEM.close()
            if _RANK_MEM is not None:
                _RANK_MEM.close()
            _SALES_MEM = None
            _SALES_MTIME = None
            _RANK_MEM = None
            _RANK_MTIME = None
        else:
            _ROWS.pop(table, None)
            _MTIME.pop(table, None)
            if table == "sales_lots":
                if _SALES_MEM is not None:
                    _SALES_MEM.close()
                _SALES_MEM = None
                _SALES_MTIME = None
            if table == "stallion_rankings":
                if _RANK_MEM is not None:
                    _RANK_MEM.close()
                _RANK_MEM = None
                _RANK_MTIME = None


def atomic_write_table(table: str, rows: list[dict]) -> int:
    """Replace the whole CSV atomically (tmp + os.replace). Safe mid-scrape."""
    columns = TABLES[table]
    path = csv_path(table)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{time.time_ns()}.tmp")
    normalized = [
        {col: _cell(row.get(col) if isinstance(row, dict) else "") for col in columns}
        for row in rows
    ]
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(normalized)
    os.replace(tmp, path)
    invalidate(table)
    return len(normalized)


def _row_key(table: str, row: dict) -> tuple:
    keys = UPSERT_KEYS[table]
    return tuple(_cell(row.get(k)) for k in keys)


def upsert_rows(table: str, incoming: list[dict]) -> dict:
    """Merge incoming rows by UPSERT_KEYS; write atomically. Returns counts."""
    if not incoming:
        return {"inserted": 0, "updated": 0, "total": len(load_table(table))}
    columns = TABLES[table]
    existing = load_table(table, refresh=True)
    by_key = {_row_key(table, row): dict(row) for row in existing}
    inserted = updated = 0
    for raw in incoming:
        row = {col: _cell(raw.get(col)) for col in columns}
        key = _row_key(table, row)
        if key in by_key:
            prior = by_key[key]
            merged = dict(prior)
            for col in columns:
                val = row.get(col, "")
                if val != "":
                    merged[col] = val
            if merged != prior:
                updated += 1
            by_key[key] = merged
        else:
            by_key[key] = row
            inserted += 1
    total = atomic_write_table(table, list(by_key.values()))
    return {"inserted": inserted, "updated": updated, "total": total}


def replace_partition(table: str, match: dict, incoming: list[dict]) -> dict:
    """Drop rows matching all match fields, then append incoming; atomic write."""
    columns = TABLES[table]
    existing = load_table(table, refresh=True)
    kept = []
    removed = 0
    for row in existing:
        if all(_cell(row.get(k)) == _cell(v) for k, v in match.items()):
            removed += 1
        else:
            kept.append(row)
    normalized = [{col: _cell(raw.get(col)) for col in columns} for raw in incoming]
    total = atomic_write_table(table, kept + normalized)
    return {"removed": removed, "written": len(normalized), "total": total}


# ---------------------------------------------------------------------------
# Derived in-memory indexes (allowed by data-sources principle)
# ---------------------------------------------------------------------------

_SALES_SCHEMA = """
CREATE TABLE catalogs (
    id INTEGER PRIMARY KEY,
    year INTEGER NOT NULL,
    title TEXT NOT NULL,
    month_index INTEGER,
    source_file TEXT,
    UNIQUE(year, title)
);
CREATE TABLE lots (
    id INTEGER PRIMARY KEY,
    catalog_id INTEGER NOT NULL,
    hip TEXT,
    name TEXT,
    name_key TEXT,
    sex TEXT,
    sex_letter TEXT,
    sire TEXT,
    sire_key TEXT,
    dam TEXT,
    dam_key TEXT,
    damsire TEXT,
    damsire_key TEXT,
    color TEXT,
    consignor TEXT,
    purchaser TEXT,
    barn TEXT,
    foaled_location TEXT,
    birth_year TEXT,
    price_raw TEXT,
    price_num REAL,
    is_rna INTEGER,
    is_out INTEGER,
    is_fasig INTEGER
);
CREATE INDEX idx_lots_sire ON lots(sire_key);
CREATE INDEX idx_lots_name ON lots(name_key);
CREATE INDEX idx_lots_dam ON lots(dam_key);
CREATE INDEX idx_lots_damsire ON lots(damsire_key);
CREATE INDEX idx_lots_catalog ON lots(catalog_id);
"""


def _month_index(title: str) -> int:
    try:
        import sales_history
        return sales_history.get_sale_month_index(title)
    except Exception:
        return 0


def _truthy(val) -> int:
    text = str(val or "").strip().lower()
    return 1 if text in {"1", "true", "yes", "y", "t"} else 0


def sales_connection() -> sqlite3.Connection | None:
    """In-memory SQLite built from sales_lots.csv; rebuilds on mtime change."""
    global _SALES_MEM, _SALES_MTIME
    path = csv_path("sales_lots")
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    with _LOCK:
        if _SALES_MEM is not None and _SALES_MTIME == mtime:
            return _SALES_MEM
        if _SALES_MEM is not None:
            _SALES_MEM.close()
        rows = _read_csv("sales_lots")
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SALES_SCHEMA)
        catalogs: dict[tuple, int] = {}
        lot_id = 0
        for row in rows:
            try:
                year = int(str(row.get("catalog_year") or "0").strip() or 0)
            except ValueError:
                year = 0
            title = (row.get("catalog_title") or "").strip() or (row.get("source_file") or "")
            key = (year, title)
            if key not in catalogs:
                cur = conn.execute(
                    "INSERT INTO catalogs (year, title, month_index, source_file) VALUES (?, ?, ?, ?)",
                    (year, title, _month_index(title), row.get("source_file") or ""),
                )
                catalogs[key] = cur.lastrowid
            lot_id += 1
            try:
                price = float(str(row.get("price_num") or "0").replace(",", "") or 0)
            except ValueError:
                price = 0.0
            conn.execute(
                """
                INSERT INTO lots (
                    id, catalog_id, hip, name, name_key, sex, sex_letter,
                    sire, sire_key, dam, dam_key, damsire, damsire_key, color,
                    consignor, purchaser, barn, foaled_location, birth_year,
                    price_raw, price_num, is_rna, is_out, is_fasig
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    lot_id,
                    catalogs[key],
                    row.get("hip") or "",
                    row.get("name") or "",
                    row.get("name_key") or name_key(row.get("name") or ""),
                    row.get("sex") or "",
                    row.get("sex_letter") or "",
                    row.get("sire") or "",
                    row.get("sire_key") or name_key(row.get("sire") or ""),
                    row.get("dam") or "",
                    row.get("dam_key") or name_key(row.get("dam") or ""),
                    row.get("damsire") or "",
                    row.get("damsire_key") or name_key(row.get("damsire") or ""),
                    row.get("color") or "",
                    row.get("consignor") or "",
                    row.get("purchaser") or "",
                    row.get("barn") or "",
                    row.get("foaled_location") or "",
                    row.get("birth_year") or "",
                    row.get("price_raw") or "",
                    price,
                    _truthy(row.get("is_rna")),
                    _truthy(row.get("is_out")),
                    _truthy(row.get("is_fasig")),
                ),
            )
        conn.commit()
        _SALES_MEM = conn
        _SALES_MTIME = mtime
        _ROWS["sales_lots"] = rows
        _MTIME["sales_lots"] = mtime
        return _SALES_MEM


def rankings_connection() -> sqlite3.Connection | None:
    """In-memory SQLite built from stallion_rankings.csv."""
    global _RANK_MEM, _RANK_MTIME
    path = csv_path("stallion_rankings")
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    with _LOCK:
        if _RANK_MEM is not None and _RANK_MTIME == mtime:
            return _RANK_MEM
        if _RANK_MEM is not None:
            _RANK_MEM.close()
        rows = _read_csv("stallion_rankings")
        cols = TABLES["stallion_rankings"]
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        col_sql = ", ".join(f'"{c}" TEXT' for c in cols)
        conn.execute(f"CREATE TABLE stallion_rankings ({col_sql})")
        placeholders = ", ".join(["?"] * len(cols))
        insert = f'INSERT INTO stallion_rankings VALUES ({placeholders})'
        for row in rows:
            conn.execute(insert, [row.get(c, "") for c in cols])
        conn.execute(
            'CREATE INDEX idx_rank_stallion ON stallion_rankings (stallion)'
        )
        conn.commit()
        _RANK_MEM = conn
        _RANK_MTIME = mtime
        _ROWS["stallion_rankings"] = rows
        _MTIME["stallion_rankings"] = mtime
        return _RANK_MEM


def graded_stakes_winners() -> list[dict]:
    """Winner rows from graded_stakes.csv (Place == 1), shaped for hypomating."""
    records = []
    for row in load_table("graded_stakes"):
        place = str(row.get("Place") or "").strip()
        if place and place not in {"1", "1.0"}:
            continue
        name = (row.get("Horse Name") or "").strip()
        if not name or name.upper() in {"N/A", "NAN", "NONE"}:
            continue
        grade = (row.get("Grade") or row.get("Group") or "").strip()
        foal = (row.get("Foaling Year") or row.get("Year Foaled") or "").strip()
        records.append({
            "Horse Name": name,
            "Foaling Year": foal,
            "Year Foaled": foal,
            "Sex": (row.get("Sex") or "").strip(),
            "Race Name": (row.get("Race Name") or "").strip(),
            "Race Year": (row.get("Race Year") or "").strip(),
            "Grade": grade,
            "Group": grade,
            "Purse": (row.get("Purse") or "").strip(),
            "Distance": (row.get("Distance") or "").strip(),
            "Track": (row.get("Track") or "").strip(),
            "Date": (row.get("Date") or "").strip(),
            "Place": 1,
            "Country": (row.get("Country") or "").strip(),
            "Age": (row.get("Age") or "").strip(),
        })
    return records


def stud_fee_history() -> dict[str, dict[int, int]]:
    """stallion name_key -> {year: fee_int} from stud_fees.csv."""
    out: dict[str, dict[int, int]] = {}
    for row in load_table("stud_fees"):
        key = name_key(row.get("Stallion") or "")
        if not key:
            continue
        try:
            year = int(str(row.get("Year") or "").strip())
        except ValueError:
            continue
        fee_raw = str(row.get("Stud Fee") or "")
        digits = re.sub(r"[^\d]", "", fee_raw)
        if not digits:
            continue
        fee = int(digits)
        out.setdefault(key, {})[year] = fee
    return out


def breeding_for_stallion(stallion: str, year: int | None = None) -> list[dict]:
    key = name_key(stallion)
    rows = []
    for row in load_table("breeding_seasons"):
        if name_key(row.get("stallion") or "") != key:
            continue
        if year is not None and str(row.get("breeding_year")) != str(year):
            continue
        rows.append(row)
    return rows


def broodmare_sire_rows(year: int | None = None) -> list[dict]:
    """Latest (or year-filtered) Broodmare list from stallion_rankings.csv."""
    candidates = []
    for row in load_table("stallion_rankings"):
        if (row.get("list") or "").strip() != "Broodmare":
            continue
        try:
            y = int(str(row.get("year") or "").strip())
        except ValueError:
            continue
        if year is not None and y != year:
            continue
        candidates.append((y, row))
    if not candidates:
        return []
    if year is None:
        latest = max(y for y, _ in candidates)
        candidates = [(y, r) for y, r in candidates if y == latest]
    out = []
    for _y, row in candidates:
        def as_int(value):
            try:
                return int(float(re.sub(r"[^\d.-]", "", str(value or "0")) or 0))
            except ValueError:
                return 0

        def as_float(value):
            try:
                return float(re.sub(r"[^\d.-]", "", str(value or "0")) or 0)
            except ValueError:
                return 0.0

        out.append({
            "rank": as_int(row.get("rank")),
            "stallion": row.get("stallion") or "",
            "lineage": row.get("sire") or "",
            "dams": as_int(row.get("dams")),
            "rnrs": as_int(row.get("runners")),
            "wnrs": as_int(row.get("winners")),
            "chief_earner": row.get("chief_earner") or "",
            "chief_earners_earnings": as_int(row.get("chief_earner_earnings")),
            "earnings_2026": as_int(row.get("year_earnings")),
            "cum_swrs": as_int(row.get("cumulative_stakes_winners")),
            "aei": as_float(row.get("aei")),
            "comp_index": as_float(row.get("comparable_index")),
            "cum_foals": as_int(row.get("cumulative_foals")),
        })
    out.sort(key=lambda item: item["rank"] or 10**9)
    return out


def stallion_roster_from_fees(year: int | None = None) -> dict[str, dict]:
    """Active stud cards derived from stud_fees (+ latest breeding_seasons)."""
    fees = load_table("stud_fees")
    by_stallion: dict[str, list] = {}
    for row in fees:
        key = name_key(row.get("Stallion") or "")
        if not key:
            continue
        by_stallion.setdefault(key, []).append(row)
    breeding = {}
    for row in load_table("breeding_seasons"):
        key = name_key(row.get("stallion") or "")
        try:
            y = int(str(row.get("breeding_year") or "").strip())
        except ValueError:
            continue
        prior = breeding.get(key)
        if prior is None or y > prior[0]:
            breeding[key] = (y, row)
    ranks = {}
    for row in load_table("stallion_rankings"):
        if (row.get("list") or "").strip() != "General":
            continue
        key = name_key(row.get("stallion") or "")
        try:
            y = int(str(row.get("year") or "").strip())
            r = int(str(row.get("rank") or "").strip())
        except ValueError:
            continue
        prior = ranks.get(key)
        if prior is None or y > prior[0]:
            ranks[key] = (y, r)

    profiles = {}
    for key, rows in by_stallion.items():
        dated = []
        for row in rows:
            try:
                y = int(str(row.get("Year") or "").strip())
            except ValueError:
                continue
            dated.append((y, row))
        if not dated:
            continue
        if year is not None:
            dated = [pair for pair in dated if pair[0] == year] or dated
        y, row = max(dated, key=lambda p: p[0])
        fee_digits = re.sub(r"[^\d]", "", str(row.get("Stud Fee") or ""))
        fee = int(fee_digits) if fee_digits else 0
        mb = breeding.get(key)
        rank = ranks.get(key)
        display = (row.get("Stallion") or "").strip()
        profiles[display] = {
            "Farm": row.get("Farm") or "",
            "Year Born": 0,
            "Stud Duty Year": y,
            "Stud Fee": fee,
            "Status": "active",
            "Surface": "",
            "Height": "N/A",
            "Conformation & Physical Profile": "",
            "Major Wins": "",
            "Career Highlight": "",
            "Race Record": {},
            "sire_rank": rank[1] if rank else "",
            "mares_bred_2025": (mb[1].get("mares_bred") if mb and mb[0] >= 2025 else "") if mb else "",
            "_name_key": key,
        }
    return profiles
