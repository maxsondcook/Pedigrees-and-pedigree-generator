"""Read upcoming-sale catalogs from Upcoming Sales/ (and Analyzed Sales/)."""
import csv
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYZED_DIR = os.path.join(ROOT, "Analyzed Sales")
UPCOMING_DIR = os.path.join(ROOT, "Upcoming Sales")
_ID_RE = re.compile(r"[A-Za-z0-9._()\- ]+")
_PLACEHOLDER_NAME = re.compile(r"^(?:hip\s*\d+|\d{4}-)", re.I)


def _blank(value):
    text = "" if value is None else str(value).strip()
    if text.lower() in {"", "nan", "none", "null"}:
        return ""
    return text


def _year(value):
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return match.group(0) if match else ""


def _title(stem):
    name = stem[len("analyzed_"):] if stem.lower().startswith("analyzed_") else stem
    name = name.replace("_", " ").strip()
    return name if name else stem


def _hip_sort(hip):
    digits = "".join(ch for ch in str(hip or "") if ch.isdigit())
    return int(digits) if digits else 10**9


def _safe_csv(folder, stem):
    if not stem or not isinstance(stem, str):
        return None
    if stem != stem.strip() or not _ID_RE.fullmatch(stem):
        return None
    if ".." in stem:
        return None
    path = os.path.join(folder, stem + ".csv")
    if not os.path.isfile(path):
        return None
    real = os.path.realpath(path)
    root = os.path.realpath(folder)
    if real != root and not real.startswith(root + os.sep):
        return None
    return real


def _count_hips(path):
    try:
        _, rows = _read_rows(path)
    except OSError:
        return 0
    count = 0
    for row in rows:
        if _blank(_col(row, "HIP", "HIP NUMBER", "LOT")) or _blank(_col(row, "HORSE NAME", "NAME", "HORSE")):
            count += 1
    return count


def _catalog_entry(stem, path, source):
    year = _year(stem)
    title = _title(stem)
    return {
        "id": stem,
        "title": title,
        "year": year,
        "hips": _count_hips(path),
        "source": source,
    }


def _yy_suffix(year):
    digits = _year(year)
    if not digits or len(digits) < 2:
        return ""
    return f" '{digits[-2:]}"


def _display_name(name, sire, dam, hip="", year=""):
    """Yearling placeholders like 2025-RAVER become Sire x Dam '25."""
    label = _blank(name)
    suffix = _yy_suffix(year)
    if not label or _PLACEHOLDER_NAME.match(label):
        if sire or dam:
            base = f"{sire} x {dam}".strip(" x")
            return f"{base}{suffix}" if base else (f"Hip {hip}" if hip else "Unnamed")
        return f"Hip {hip}" if hip else "Unnamed"
    if re.search(r"\s+x\s+", label, re.I):
        base = re.sub(r"\s*'\d{2}\s*$", "", label).strip()
        return f"{base}{suffix}" if suffix else base
    return label


def _sex_word(sex):
    letter = _blank(sex)[:1].upper()
    return {
        "C": "Colt",
        "F": "Filly",
        "M": "Mare",
        "H": "Horse",
        "G": "Gelding",
        "R": "Ridgling",
        "W": "Weanling",
    }.get(letter, _blank(sex))


def _color_word(color):
    raw = _blank(color)
    if not raw:
        return ""
    key = re.sub(r"\s+", " ", raw.upper().replace(".", "")).strip()
    key = key.replace("DKB/", "DK B/").replace("DKB ", "DK B ")
    mapping = {
        "B": "Bay",
        "BAY": "Bay",
        "CH": "Chestnut",
        "CHESTNUT": "Chestnut",
        "DK B/BR": "Dark Bay or Brown",
        "DK B / BR": "Dark Bay or Brown",
        "DK B BR": "Dark Bay or Brown",
        "DKB/BR": "Dark Bay or Brown",
        "DARK BAY OR BROWN": "Dark Bay or Brown",
        "GR/RO": "Gray/Roan",
        "GR / RO": "Gray/Roan",
        "G/R": "Gray/Roan",
        "GRAY/ROAN": "Gray/Roan",
        "GR": "Gray",
        "GRAY": "Gray",
        "GREY": "Gray",
        "RO": "Roan",
        "ROAN": "Roan",
        "BLK": "Black",
        "BLACK": "Black",
        "WH": "White",
        "WHITE": "White",
    }
    if key in mapping:
        return mapping[key]
    # Tolerate "Dk B/Br" style with mixed spacing.
    compact = key.replace(" ", "")
    compact_map = {
        "DKB/BR": "Dark Bay or Brown",
        "GR/RO": "Gray/Roan",
    }
    if compact in compact_map:
        return compact_map[compact]
    return raw


def _birth_date(raw):
    text = _blank(raw)
    if not text:
        return ""
    if re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", text):
        return text
    return _year(text)


def _path_for(catalog_id):
    """Resolve catalog CSV from Analyzed Sales/ first, then Upcoming Sales/."""
    path = _safe_csv(ANALYZED_DIR, catalog_id)
    if path:
        return path
    return _safe_csv(UPCOMING_DIR, catalog_id)


def _read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _col(row, *names):
    lookup = {(key or "").upper().strip(): key for key in row.keys() if key is not None}
    for name in names:
        key = lookup.get(name.upper())
        if key is not None:
            return row.get(key)
    return ""


def _price_num(raw):
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit() or ch == ".")
    try:
        return float(digits) if digits else 0
    except ValueError:
        return 0


def _sold_as(row, birth_year=None, sale_year=None):
    sold = _blank(_col(row, "SOLD AS", "SOLD AS DESCRIPTION", "DESCRIPTION"))
    if sold:
        return sold
    code = _blank(_col(row, "SOLD AS CODE")).upper()
    mapped = {
        "Y": "Yearling",
        "W": "Weanling",
        "B": "Broodmare",
        "H": "Horse of Racing Age",
        "2": "Two-Year-Old",
        "3": "Three-Year-Old",
    }.get(code, code)
    if mapped:
        return mapped
    # Foaling age vs catalog year when the CSV leaves sold-as blank.
    try:
        from crossr_core.projections import kind_from_foaling_age

        return kind_from_foaling_age(birth_year, sale_year) or ""
    except Exception:
        return ""


def _lot_from_csv(row, sale_year=None):
    sex = _blank(_col(row, "SEX"))
    price_raw = _blank(_col(row, "PRICE", "PRICE_RAW", "SALE PRICE", "AUCTION PRICE"))
    starred = _blank(_col(row, "STARRED")).lower()
    raw_name = _blank(_col(row, "HORSE NAME", "NAME", "HORSE"))
    sire = _blank(_col(row, "SIRE"))
    dam = _blank(_col(row, "DAM"))
    hip = _blank(_col(row, "HIP", "HIP NUMBER", "LOT"))
    yob_raw = _blank(_col(row, "YEAR OF BIRTH", "YOB", "DOB"))
    birth_year = _year(yob_raw)
    color_raw = _blank(_col(row, "COLOR", "COLOUR"))
    display = _display_name(raw_name, sire, dam, hip, year=birth_year or yob_raw)
    return {
        "hip": hip,
        "name": display,
        "raw_name": raw_name,
        "sex": sex,
        "sex_letter": sex[:1].upper() if sex else "",
        "sex_label": _sex_word(sex),
        "sire": sire,
        "dam": dam,
        "damsire": _blank(_col(row, "SIRE OF DAM", "BMS", "DAMSIRE", "BROODMARE SIRE", "DAM SIRE")),
        "birth_year": birth_year,
        "birth_date": _birth_date(yob_raw),
        "foaled": _blank(_col(row, "FOALED", "STATE")),
        "sold_as": _sold_as(row, birth_year=birth_year, sale_year=sale_year),
        "covering_sire": _blank(_col(row, "COVERING SIRE")),
        "color": color_raw,
        "color_label": _color_word(color_raw),
        "consignor": _blank(_col(row, "CONSIGNOR", "CONSIGNED BY", "PROPERTY LINE")),
        "barn": _blank(_col(row, "BARN")),
        "notes": _blank(_col(row, "NOTES")),
        "starred": starred in {"*", "1", "true", "yes"},
        "price_raw": price_raw,
        "price_num": _price_num(price_raw),
    }


def list_catalogs():
    """Prefer analyzed catalogs; also surface raw files still in Upcoming Sales."""
    by_key = {}
    if os.path.isdir(ANALYZED_DIR):
        for name in sorted(os.listdir(ANALYZED_DIR)):
            if not name.lower().endswith(".csv") or name.startswith("."):
                continue
            stem = name[:-4]
            path = _safe_csv(ANALYZED_DIR, stem)
            if not path:
                continue
            by_key[stem.lower()] = _catalog_entry(stem, path, "analyzed")
    if os.path.isdir(UPCOMING_DIR):
        for name in sorted(os.listdir(UPCOMING_DIR)):
            if not name.lower().endswith(".csv") or name.startswith("."):
                continue
            stem = name[:-4]
            path = _safe_csv(UPCOMING_DIR, stem)
            if not path:
                continue
            key = stem.lower()
            analyzed_key = f"analyzed_{key}"
            if analyzed_key in by_key or key in by_key:
                continue
            by_key[key] = _catalog_entry(stem, path, "upcoming")
    return sorted(by_key.values(), key=lambda row: row["title"].lower())


def _pg():
    from crossr_core import railway_db

    return railway_db if railway_db.enabled() else None


def _apply_mark(lot, mark):
    if not mark:
        return lot
    if mark.get("starred") is not None:
        lot["starred"] = bool(mark["starred"])
    if mark.get("notes") is not None:
        lot["notes"] = mark["notes"]
    return lot


def list_lots(catalog_id):
    path = _path_for(catalog_id)
    if not path:
        return None
    sale_year = _year(catalog_id)
    _, rows = _read_rows(path)
    # With Postgres, stars/notes live in upcoming_lot_marks and override the CSV.
    pg = _pg()
    marks = pg.read_lot_marks(catalog_id) if pg else {}
    lots = []
    for row in rows:
        lot = _lot_from_csv(row, sale_year=sale_year)
        lot["sale_year"] = sale_year
        _apply_mark(lot, marks.get(lot["hip"]))
        if lot["hip"] or lot["name"]:
            lots.append(lot)
    # Catalog modal age fills any remaining blank sold_as (mixed/untitled sales).
    try:
        from crossr_core import projections as proj_svc

        proj_svc.annotate_lot_kinds(
            lots, sale_year=sale_year, catalog_title=str(catalog_id or "")
        )
    except Exception:
        pass
    lots.sort(key=lambda lot: (_hip_sort(lot["hip"]), lot["hip"]))
    return lots


def get_lot(catalog_id, hip):
    lots = list_lots(catalog_id)
    if lots is None:
        return None
    want = str(hip).strip()
    for lot in lots:
        if lot["hip"] == want:
            return lot
    return None


def update_lot(catalog_id, hip, starred=None, notes=None):
    path = _path_for(catalog_id)
    if not path:
        return None
    fieldnames, rows = _read_rows(path)
    if not fieldnames:
        return None
    upper = {name.upper(): name for name in fieldnames}
    if starred is not None and "STARRED" not in upper:
        fieldnames.append("STARRED")
        upper["STARRED"] = "STARRED"
    if notes is not None and "NOTES" not in upper:
        fieldnames.append("NOTES")
        upper["NOTES"] = "NOTES"
    want = str(hip).strip()
    found = None
    for row in rows:
        if _blank(_col(row, "HIP", "HIP NUMBER", "LOT")) == want:
            found = row
            break
    if found is None:
        return None
    pg = _pg()
    if pg:
        # The CSV ships inside the container and resets on deploy; store in Postgres.
        mark = pg.set_lot_mark(catalog_id, want, starred=starred, notes=notes)
        return _apply_mark(_lot_from_csv(found), mark)
    if starred is not None:
        found[upper["STARRED"]] = "*" if starred else ""
    if notes is not None:
        found[upper["NOTES"]] = notes
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: (row.get(key) if row.get(key) is not None else "") for key in fieldnames})
    os.replace(tmp, path)
    return _lot_from_csv(found)


def filter_lots(lots, sex=None, color=None, max_price=None, height=None, starred=None, exclude_hips=None, only_hips=None):
    excluded = {str(hip).strip() for hip in (exclude_hips or []) if str(hip).strip()}
    only = {str(hip).strip() for hip in (only_hips or []) if str(hip).strip()}
    kept = []
    for lot in lots:
        hip = str(lot.get("hip") or "")
        if only and hip not in only:
            continue
        if not only and hip in excluded:
            continue
        if sex and (lot.get("sex_letter") or "") != str(sex).upper()[:1]:
            continue
        if color:
            coat = (lot.get("color") or "").lower()
            if not coat or str(color).lower() not in coat:
                continue
        if max_price not in (None, ""):
            price = lot.get("price_num") or 0
            if not price or price > float(max_price):
                continue
        if height:
            hands = (lot.get("height") or "").lower()
            if not hands or str(height).lower() not in hands:
                continue
        if starred and not lot.get("starred"):
            continue
        kept.append(lot)
    return kept
