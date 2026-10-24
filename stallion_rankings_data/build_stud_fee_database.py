#!/usr/bin/env python3
"""Build stud_fee_database.csv from BloodHorse year-ranking CSVs (2001–2026)."""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/maxsoncook/Desktop/stallion_rankings_data")
OUT_CSV = ROOT / "stud_fee_database.csv"
OUT_README = ROOT / "stud_fee_database_README.txt"

YEAR_DIRS = [str(y) for y in range(2001, 2027)]
NA = "N/A"

COLUMNS = ["Year", "Stallion", "Stud Fee", "Farm", "Source List", "Notes"]

FEE_HEADER_RE = re.compile(r"stud\s*fee|/\s*farm|(?<![a-z])fee(?![a-z])", re.I)
SKIP_DIR_NAMES = {"bloodhorse_sirelists"}

PRIVATE_RE = re.compile(r"^private(?:\s+fee)?$", re.I)
STATUS_RE = re.compile(
    r"^(?P<status>"
    r"n/?a|"
    r"pensioned|"
    r"retired|"
    r"deceased|"
    r"not standing|"
    r"to be announced|"
    r"died(?:\s+\d{4})?"
    r")\s*$",
    re.I,
)
USD_RE = re.compile(r"^\$\s*([\d,]+)\s*([A-Za-z])?\s*$")
USD_CAN_RE = re.compile(r"^\$\s*([\d,]+)\s*\(\s*CAN\s*\)\s*$", re.I)
PLAIN_NUM_RE = re.compile(r"^([\d,]+)\s*$")
FOREIGN_FEE_RE = re.compile(
    r"^([\d,]+)\s*\(\s*(Euros?|Lira|Yen|Pounds?|Rands?|AUS\$|NZ\$|Pesos|CAN)\s*\)\s*$",
    re.I,
)
# AEI 2001–2008: NAME [(CC)] (YY, Sire), Farm, ST
AEI_STALLION_RE = re.compile(
    r"^(?P<name>.+?)"
    r"(?:\s+\((?P<cc>[A-Za-z]{2,3})\))?"
    r"\s+\((?P<yy>\d{2}),\s*(?P<sire>[^)]+)\)"
    r"(?:,\s*(?P<farm>.+))?$"
)
COUNTRY_RE = re.compile(r"\(([A-Za-z]{2,3})\)")
APOSTROPHES = dict.fromkeys(map(ord, "’`´ʻʹ"), "'")


def clean_text(value: str) -> str:
    if value is None:
        return ""
    text = str(value).translate(APOSTROPHES)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def is_blank(value: str) -> bool:
    return (not value) or value.upper() in {"N/A", "NA", "N.A.", "-", "—", "–", "?", "*"}


PUNCT_ONLY_RE = re.compile(r"^[\s,;./\\|:_\-–—'\"`]+$")
GENERIC_FARM_TOKENS = {
    "farm", "farms", "stallion", "stallions", "stud", "studs",
    "ltd", "limited", "inc", "llc", "station",
}
GEO_TOKENS = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy", "on", "qc", "bc", "ab", "mb", "sk", "ns", "nb", "pe", "nl",
    "can", "usa", "ire", "jpn", "japan", "aus", "nz", "eng", "gb",
    "fr", "fra", "ity", "ger", "saf", "uae", "tur", "arg", "brz",
    "chi", "kentucky", "florida", "california", "newyork", "texas",
}


def display_or_na(value: str) -> str:
    if is_blank(value) or PUNCT_ONLY_RE.match(value or ""):
        return NA
    return value


def normalize_country_codes(name: str) -> str:
    return COUNTRY_RE.sub(lambda m: f"({m.group(1).upper()})", name)


def title_if_all_caps(name: str) -> str:
    letters = [c for c in name if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        parts = []
        for token in name.split(" "):
            m = re.fullmatch(r"\(([A-Z]{2,3})\)", token)
            if m:
                parts.append(token)
            elif re.fullmatch(r"[A-Z]\.(?:[A-Z]\.)+", token):
                parts.append(token)  # A.P.
            elif "." in token:
                parts.append(".".join(p.capitalize() if p else "" for p in token.split(".")))
            else:
                parts.append(token.capitalize() if token else token)
        return " ".join(parts)
    return name


def stallion_key(name: str) -> str:
    key = normalize_country_codes(name).casefold()
    key = re.sub(r"[^a-z0-9]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def parse_stallion_cell(raw: str) -> tuple[str, str]:
    """Return (stallion_name, farm_if_embedded)."""
    text = clean_text(raw)
    if not text:
        return "", ""
    first = clean_text(text.splitlines()[0])
    aei = AEI_STALLION_RE.match(first)
    if aei:
        name = clean_text(aei.group("name"))
        cc = aei.group("cc")
        if cc:
            name = f"{name} ({cc.upper()})"
        farm = clean_text(aei.group("farm") or "")
        return title_if_all_caps(normalize_country_codes(name)), farm
    name = normalize_country_codes(first)
    return title_if_all_caps(name), ""


def format_usd(amount: str, suffix: str = "") -> str:
    digits = amount.replace(",", "").replace(" ", "")
    if not digits.isdigit():
        return f"${amount}{suffix}"
    pretty = f"${int(digits):,}"
    return pretty + suffix


def normalize_fee_for_match(fee: str) -> str:
    if is_blank(fee):
        return "N/A"
    text = fee.upper().replace(" ", "")
    m = re.match(r"^\$?([\d,]+)", fee.replace(" ", ""))
    if m and "(" not in fee:
        return f"${int(m.group(1).replace(',', ''))}"
    return re.sub(r"\s+", " ", fee).casefold()


def parse_fee_farm_cell(raw: str) -> tuple[str, str, str]:
    """Parse a combined or fee-only cell into (fee, farm, notes)."""
    text = clean_text(raw)
    if not text:
        return NA, NA, ""

    parts = [clean_text(p) for p in re.split(r"[\n\r]+", text) if clean_text(p)]
    if not parts:
        return NA, NA, ""

    first, rest = parts[0], parts[1:]
    farm_from_rest = clean_text(" ".join(rest)) if rest else ""

    # Combined on one line: "Private WinStar Farm, KY" / "Private fee Claiborne"
    private_line = re.match(r"^(Private(?:\s+fee)?)\s+(.+)$", first, re.I)
    if private_line and not rest and re.search(r"[A-Za-z]", private_line.group(2)):
        return "Private", display_or_na(clean_text(private_line.group(2))), ""

    # Combined on one line: "$60,000 WinStar Farm, KY"
    one_line = re.match(
        r"^(\$\s*[\d,]+(?:\s*\([^)]+\))?|[0-9][\d,]*\s*\([^)]+\))\s+(.+)$",
        first,
    )
    if one_line and not rest:
        maybe_fee, maybe_farm = one_line.group(1), one_line.group(2)
        if re.search(r"[A-Za-z]", maybe_farm):
            fee, farm, notes = classify_fee_token(maybe_fee)
            if fee != NA or notes:
                return fee, display_or_na(maybe_farm), notes
            # fall through if the "farm" looked like more fee text

    fee, farm_from_first, notes = classify_fee_token(first)
    farm = farm_from_rest or farm_from_first
    if notes and farm and farm.casefold() == notes.casefold():
        farm = NA
    return fee, display_or_na(farm), notes


def classify_fee_token(token: str) -> tuple[str, str, str]:
    """Classify a single fee/status token. Returns (fee, farm_if_any, notes)."""
    token = clean_text(token)
    if is_blank(token):
        return NA, "", ""

    if PRIVATE_RE.match(token):
        return "Private", "", ""

    status = STATUS_RE.match(token)
    if status:
        label = clean_text(status.group("status"))
        if label.upper() in {"N/A", "NA", "N.A."}:
            return NA, "", ""
        # Died / Pensioned / Retired / TBA stay in Notes; fee is N/A
        if label[:1].islower():
            label = label[0].upper() + label[1:]
        return NA, "", label

    m = USD_CAN_RE.match(token)
    if m:
        return format_usd(m.group(1), " (CAN)"), "", ""

    m = USD_RE.match(token)
    if m:
        return format_usd(m.group(1)), "", ""

    m = FOREIGN_FEE_RE.match(token)
    if m:
        amount, currency = m.group(1), m.group(2)
        currency = {
            "euro": "Euros",
            "euros": "Euros",
            "lira": "Lira",
            "yen": "Yen",
            "pound": "Pounds",
            "pounds": "Pounds",
            "rand": "Rands",
            "rands": "Rands",
            "aus$": "AUS$",
            "nz$": "NZ$",
            "pesos": "Pesos",
            "can": "CAN",
        }.get(currency.lower(), currency)
        return f"{amount} ({currency})", "", ""

    m = PLAIN_NUM_RE.match(token)
    if m:
        return format_usd(m.group(1)), "", ""

    # Unknown standing-status text: keep as notes, not a dollar fee
    return NA, "", token


def farm_score(farm: str) -> tuple[int, int]:
    if is_blank(farm) or PUNCT_ONLY_RE.match(farm or ""):
        return (0, 0)
    bonus = 2 if "," in farm else 1
    if re.fullmatch(r"[A-Za-z]{2,3}", farm):
        bonus = 1
    return (bonus, len(farm))


def prefer_name(current: str, candidate: str) -> str:
    if not current:
        return candidate
    if not candidate:
        return current
    cur_caps = current.isupper()
    cand_caps = candidate.isupper()
    if cur_caps and not cand_caps:
        return candidate
    if cand_caps and not cur_caps:
        return current
    if len(candidate) > len(current):
        return candidate
    return current


def is_header_row(row: list[str], stallion: str) -> bool:
    joined = " ".join(row).lower()
    if stallion.lower() in {"stallion", "sire", "horse", "rank"}:
        return True
    if stallion.startswith("#"):
        return True
    return "stud fee" in joined and stallion.lower() == "stallion"


def detect_header(rows: list[list[str]]) -> tuple[int, list[str]] | None:
    for i, row in enumerate(rows[:3]):
        if any(c and FEE_HEADER_RE.search(c) for c in row):
            return i, row
    return None


def source_list_name(path: Path) -> str:
    name = path.name
    if " - " in name:
        return name.split(" - ", 1)[1].removesuffix(".csv").strip()
    return name.removesuffix(".csv")


def iter_ranking_csvs(root: Path) -> list[Path]:
    files: list[Path] = []
    for year in YEAR_DIRS:
        year_dir = root / year
        if not year_dir.is_dir():
            continue
        files.extend(sorted(year_dir.glob("*.csv")))
    return files


def extract_rows() -> tuple[list[dict], dict]:
    extracted: list[dict] = []
    stats = {
        "files_seen": 0,
        "files_with_fee": 0,
        "files_skipped_no_fee": 0,
        "skipped_lists": defaultdict(int),
        "used_lists": defaultdict(int),
        "combined_rows": 0,
        "split_rows": 0,
        "ignored_columns": set(),
        "fee_columns_used": set(),
        "name_columns_used": set(),
    }

    for path in iter_ranking_csvs(ROOT):
        stats["files_seen"] += 1
        with path.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        detected = detect_header(rows)
        if not detected:
            stats["files_skipped_no_fee"] += 1
            stats["skipped_lists"][source_list_name(path)] += 1
            continue

        header_idx, header = detected
        year = path.parent.name
        source = source_list_name(path)
        stats["files_with_fee"] += 1
        stats["used_lists"][source] += 1

        fee_idxs = [i for i, c in enumerate(header) if c and FEE_HEADER_RE.search(c)]
        name_idx = None
        for i, c in enumerate(header):
            cl = (c or "").lower()
            if "stallion" in cl:
                name_idx = i
                break
        if name_idx is None:
            continue

        combined = any("/" in (header[i] or "") and "farm" in (header[i] or "").lower() for i in fee_idxs)
        for i, col in enumerate(header):
            if i == name_idx or i in fee_idxs:
                continue
            if col:
                stats["ignored_columns"].add(col.replace("\n", " "))
        for i in fee_idxs:
            stats["fee_columns_used"].add(header[i].replace("\n", " "))
        stats["name_columns_used"].add(header[name_idx].replace("\n", " "))

        for row in rows[header_idx + 1 :]:
            if name_idx >= len(row):
                continue
            stallion, embedded_farm = parse_stallion_cell(row[name_idx])
            if not stallion or is_header_row(row, stallion):
                continue

            fee, farm, notes = NA, NA, ""
            for i in fee_idxs:
                if i >= len(row):
                    continue
                col = header[i] or ""
                cell = row[i]
                if re.search(r"stud\s*fee", col, re.I) or ("fee" in col.lower() and "farm" in col.lower()):
                    fee, farm, notes = parse_fee_farm_cell(cell)
                elif re.search(r"(?<![a-z])fee(?![a-z])", col, re.I):
                    fee, farm, notes = parse_fee_farm_cell(cell)

            if is_blank(farm) and embedded_farm:
                farm = embedded_farm

            extracted.append(
                {
                    "Year": year,
                    "Stallion": stallion,
                    "Stud Fee": display_or_na(fee),
                    "Farm": display_or_na(farm),
                    "Source List": source,
                    "Notes": notes,
                    "_combined": combined,
                    "_key": (year, stallion_key(stallion)),
                    "_fee_key": normalize_fee_for_match(fee),
                    "_farm_key": stallion_key(farm) if not is_blank(farm) else "n/a",
                }
            )
            if combined:
                stats["combined_rows"] += 1
            else:
                stats["split_rows"] += 1

    return extracted, stats


def merge_notes(*parts: str) -> str:
    seen: list[str] = []
    for part in parts:
        for piece in re.split(r"\s*;\s*", part):
            piece = clean_text(piece)
            if piece and piece not in seen:
                seen.append(piece)
    return "; ".join(seen)


def farm_tokens(farm: str) -> set[str]:
    if is_blank(farm) or PUNCT_ONLY_RE.match(farm or ""):
        return set()
    return set(stallion_key(farm).split())


def farm_core(farm: str) -> set[str]:
    return {t for t in farm_tokens(farm) if t not in GENERIC_FARM_TOKENS and t not in GEO_TOKENS}


def farm_geo(farm: str) -> set[str]:
    return farm_tokens(farm) & GEO_TOKENS


def farm_is_subset(shorter: str, longer: str) -> bool:
    if is_blank(shorter) or PUNCT_ONLY_RE.match(shorter or ""):
        return True
    if is_blank(longer) or PUNCT_ONLY_RE.match(longer or ""):
        return False
    a, b = farm_tokens(shorter), farm_tokens(longer)
    return bool(a) and a <= b


def same_farm(a: str, b: str) -> bool:
    if farm_is_subset(a, b) or farm_is_subset(b, a):
        return True
    ca, cb = farm_core(a), farm_core(b)
    if not ca or not cb:
        return False
    if not (ca <= cb or cb <= ca):
        return False
    ga, gb = farm_geo(a), farm_geo(b)
    return (not ga) or (not gb) or bool(ga & gb)


def dedupe(rows: list[dict]) -> tuple[list[dict], int]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["_key"]].append(row)

    out: list[dict] = []
    conflict_groups = 0

    for key, items in groups.items():
        by_fee: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            by_fee[item["_fee_key"]].append(item)

        fee_conflict = len(by_fee) > 1
        if fee_conflict:
            conflict_groups += 1

        canonical_name = ""
        for item in items:
            canonical_name = prefer_name(canonical_name, item["Stallion"])

        merged_for_key: list[dict] = []
        for fee_key, fee_items in by_fee.items():
            best = fee_items[0]
            sources = set()
            extra_farms: list[str] = []
            notes = []
            for item in fee_items:
                sources.add(item["Source List"])
                notes.append(item["Notes"])
                if farm_score(item["Farm"]) > farm_score(best["Farm"]):
                    if not is_blank(best["Farm"]) and not same_farm(best["Farm"], item["Farm"]):
                        extra_farms.append(best["Farm"])
                    best = {**best, **item}
                elif not same_farm(item["Farm"], best["Farm"]) and not is_blank(item["Farm"]):
                    extra_farms.append(item["Farm"])
            extra_farms = [f for f in dict.fromkeys(extra_farms) if not same_farm(f, best["Farm"])]
            note = merge_notes(*notes)
            if extra_farms:
                note = merge_notes(note, "Also listed at: " + "; ".join(extra_farms))
            merged_for_key.append(
                {
                    "Year": best["Year"],
                    "Stallion": canonical_name,
                    "Stud Fee": best["Stud Fee"],
                    "Farm": display_or_na(best["Farm"]),
                    "Source List": "; ".join(sorted(sources)),
                    "Notes": note,
                }
            )

        if fee_conflict:
            for row in merged_for_key:
                fees = sorted({r["Stud Fee"] for r in merged_for_key})
                row["Notes"] = merge_notes(
                    row["Notes"],
                    "Conflict: different stud fees for same stallion-year (" + "; ".join(fees) + ")",
                )
        out.extend(merged_for_key)

    out.sort(key=lambda r: (r["Year"], r["Stallion"].casefold(), r["Stud Fee"], r["Source List"]))
    return out, conflict_groups


def write_csv(rows: list[dict]) -> None:
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_readme(rows: list[dict], raw_count: int, stats: dict, conflict_count: int) -> None:
    years = sorted({r["Year"] for r in rows})
    unique_sy = len({(r["Year"], stallion_key(r["Stallion"])) for r in rows})
    na_fees = sum(1 for r in rows if r["Stud Fee"] == NA)
    private_fees = sum(1 for r in rows if r["Stud Fee"].casefold() == "private")
    conflict_rows = sum(1 for r in rows if "Conflict:" in r["Notes"])
    used = ", ".join(f"{k} ({v} files)" for k, v in sorted(stats["used_lists"].items()))
    skipped = ", ".join(f"{k} ({v} files)" for k, v in sorted(stats["skipped_lists"].items()))
    fee_cols = "\n  - ".join(sorted(stats["fee_columns_used"]))
    name_cols = "\n  - ".join(sorted(stats["name_columns_used"]))
    ignored = "\n  - ".join(sorted(stats["ignored_columns"]))

    text = f"""Stud Fee Database
=================
Built from BloodHorse year-ranking CSVs under:
  {ROOT}

Output
------
  {OUT_CSV}

Counts
------
  Output rows:              {len(rows):,}
  Unique stallion-years:    {unique_sy:,}
  Years covered:            {years[0]}–{years[-1]} ({len(years)} years)
  N/A stud fees:            {na_fees:,}
  Private stud fees:        {private_fees:,}
  Conflict groups:          {conflict_count:,}  (same stallion+year, different fees)
  Conflict rows:            {conflict_rows:,}
  Raw extracted rows:       {raw_count:,}  (before same-fee/farm collapse)
  Source files scanned:     {stats['files_seen']:,}
  Source files with fees:   {stats['files_with_fee']:,}
  Source files skipped:     {stats['files_skipped_no_fee']:,}  (no fee/farm column)

How columns were parsed
-----------------------
Year is the ranking-folder / filename prefix (2001–2026), not the year printed
inside a fee header. Some first-crop lists label an earlier inaugural fee
(e.g. 2001 list column "1998 Stud Fee / Farm"); AEI lists often label the
next covering season (e.g. 2001 AEI column "2002 Stud Fee"). Those header
years are not copied into Year.

Combined "Stud Fee / Farm" cells (newline- or space-separated) were split:
  $60,000 + WinStar Farm, KY  ->  Stud Fee=$60,000, Farm=WinStar Farm, KY
  N/A + KY                    ->  Stud Fee=N/A, Farm=KY
  N/A                         ->  Stud Fee=N/A, Farm=N/A
  Died 2002 + Claiborne Farm  ->  Stud Fee=N/A, Farm=Claiborne Farm, Notes=Died 2002
  Private / private fee       ->  Stud Fee=Private, farm kept when present
  Pensioned / Retired / To Be Announced  ->  fee N/A, status in Notes,
  farm kept when a farm/state remained.

Split AEI 2001–2008 columns:
  "YYYY Stud Fee" + farm embedded in
  "Stallion (Foreign foaled), Year, Sire, Where Stands"
  e.g. DANZIG (77, Northern Dancer), Claiborne Farm, KY

Combined-style source rows extracted: {stats['combined_rows']:,}
Split-style source rows extracted:    {stats['split_rows']:,}

Deduping
--------
Same stallion+year with the same fee is collapsed to one row. Source List
names are joined with "; ". The longest / most complete farm string is kept;
other distinct farms are recorded as "Also listed at: ..." in Notes.
Different fees for the same stallion+year are all kept and tagged
"Conflict: different stud fees for same stallion-year".

Missing values are N/A. Encoding is UTF-8 with BOM.

Fee / name columns used
-----------------------
Fee:
  - {fee_cols}

Stallion:
  - {name_cols}

Lists used ({stats['files_with_fee']} files)
--------------------------------------------
  {used}

Lists skipped — no fee/farm column ({stats['files_skipped_no_fee']} files)
-------------------------------------------------------------------------
  {skipped}

Leftover columns ignored
------------------------
  - {ignored}

Not read: bloodhorse_sirelists/ (scraper, cache, LIST_MAPPING.md, code).
"""
    OUT_README.write_text(text, encoding="utf-8")


def main() -> None:
    raw_rows, stats = extract_rows()
    final_rows, conflict_count = dedupe(raw_rows)
    write_csv(final_rows)
    write_readme(final_rows, len(raw_rows), stats, conflict_count)
    years = sorted({r["Year"] for r in final_rows})
    unique_sy = len({(r["Year"], stallion_key(r["Stallion"])) for r in final_rows})
    na_fees = sum(1 for r in final_rows if r["Stud Fee"] == NA)
    print(f"Wrote {OUT_CSV}")
    print(f"Rows: {len(final_rows)}")
    print(f"Unique stallion-years: {unique_sy}")
    print(f"Years: {years[0]}-{years[-1]}")
    print(f"N/A fees: {na_fees}")
    print(f"Conflict groups: {conflict_count}")
    print(f"Wrote {OUT_README}")


if __name__ == "__main__":
    main()
