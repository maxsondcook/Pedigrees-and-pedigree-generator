#!/usr/bin/env python3
"""Build placeholderdatabase CSVs from the repo's real sales, pedigree, and stallion files.

Default scope is the demo sale, Fasig-Tipton The Saratoga Sale: every historical
edition in sales_data, plus the 2026 upcoming catalog. Pass --all-sales to also
fold every file under sales_data/ into sale_results (that CSV is large; the
committed file is the demo sale only).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import placeholder_store
import sales_history

DATA = ROOT / "placeholderdatabase"
CATALOG_FILE = ROOT / "Analyzed Sales" / "analyzed_the_saratoga_sale_(2026).csv"
SALE_TITLE = "Fasig Tipton The Saratoga Sale"
SALE_COMPANY = "Fasig-Tipton"
DEMO_GLOB = "Fasig-Tipton_The Saratoga Sale (*).csv"

SIRE_RANK = [
    "Not This Time", "Into Mischief", "Gun Runner", "Nyquist", "Curlin", "Constitution",
    "Practical Joke", "Munnings", "Liam's Map", "Uncle Mo", "Vekoma", "American Pharoah",
    "Tiz the Law", "Omaha Beach", "Maclean's Music", "Twirling Candy", "Justify",
    "Quality Road", "Mendelssohn", "Candy Ride (ARG)", "Oscar Performance", "Connect",
    "Hard Spun", "Bolt d'Oro", "Vino Rosso", "Speightstown", "Medaglia d'Oro",
    "Goldencents", "City of Light", "Mitole", "Frosted", "Street Sense", "Audible",
    "Volatile", "Authentic", "Mo Town", "Cairo Prince", "Yaupon", "Flameaway",
    "Honor A. P.", "Violence", "Collected", "Midshipman", "Ghostzapper", "Kantharos",
    "Exaggerator", "Tapit", "McKinzie", "Dialed In", "Tapiture", "Upstart", "Good Magic",
    "Maximus Mischief", "Essential Quality", "Charlatan", "Girvin", "The Big Beast",
    "Solomini", "Union Rags", "Blame", "Instagrand", "Runhappy", "Army Mule", "Maxfield",
    "Cloud Computing", "Bucchero", "The Factor", "More Than Ready", "Stay Thirsty",
    "Complexity", "Jimmy Creed", "Tacitus", "Great Notion", "Grazen", "Cupid",
    "Star Guitar", "Khozan", "Clubhouse Ride", "Awesome Slew", "War of Will", "Tonalist",
    "War Front", "Kitten's Joy", "Neolithic", "Take Charge Indy", "Golden Lad", "Blofeld",
    "Karakontie (JPN)", "Rock Your World", "Central Banker", "Enticed", "Beau Liam",
    "Paynter", "Aurelius Maximus", "Sergei Prokofiev", "Spun to Run", "Sir Prancealot (IRE)",
    "Unified", "Adios Charlie", "Maximum Security", "Summer Front", "Independence Hall",
    "West Coast", "Accelerate", "Preservationist", "Echo Town", "Warrior's Reward",
    "Speightster", "American Freedom", "Uncle Lino", "Smiling Tiger", "Thousand Words",
    "Game Winner", "Improbable", "Coal Front", "Distorted Humor", "Mastery", "Outwork",
    "Mucho Macho Man", "Cajun Breeze", "Modernist", "Tapwrit", "Gormley", "Always Dreaming",
    "Om", "Honest Mischief", "Keen Ice", "Good Samaritan", "Marking", "Stanford", "Pavel",
    "Flat Out", "Cinco Charlie", "Valiant Minister", "Souper Speedy", "Win Win Win",
    "Hoppertunity", "El Deal", "Divining Rod", "Cross Traffic", "Street Strategy",
    "Caracaro", "Weigelia", "Tom's d'Etat", "Catholic Boy", "Temple City",
    "Competitive Edge", "I'll Have Another", "Midnight Lute", "Lexitonian",
]


def blank_row(table: str) -> dict:
    return {column: "" for column in placeholder_store.TABLES[table]}


def split_name(raw: str):
    text = (raw or "").strip()
    year = ""
    country = ""
    year_match = re.search(r"\((\d{4})\)\s*$", text)
    if year_match:
        year = year_match.group(1)
        text = text[: year_match.start()].strip()
    country_match = re.search(r"\(([A-Za-z]{2,3})\)\s*$", text)
    if country_match:
        country = country_match.group(1).upper()
        text = text[: country_match.start()].strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text, year, country


def load_pedigree_index():
    namespace = {}
    path = ROOT / "pedigrees_database.py"
    exec(path.read_text(encoding="utf-8"), namespace)
    pedigree_map = namespace.get("pedigree_map", {})
    index = {}
    for key, value in pedigree_map.items():
        index[placeholder_store.name_key(str(key))] = value
    return index


def load_graded_class():
    classes = {}
    rank = {"": 0, "SW": 1, "G3": 2, "G2": 3, "G1": 4}
    path = ROOT / "graded_stakes_winners.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            grade = (row.get("Grade") or "").upper()
            label = "G1" if "G1" in grade else "G2" if "G2" in grade else "G3" if "G3" in grade else ""
            if not label:
                continue
            key = placeholder_store.name_key(row.get("Horse Name") or "")
            if rank[label] > rank.get(classes.get(key, ""), 0):
                classes[key] = label
    return classes


def class_from_text(text: str) -> str:
    upper = (text or "").upper()
    if "G1" in upper:
        return "G1"
    if "G2" in upper:
        return "G2"
    if "G3" in upper:
        return "G3"
    return ""


def header_map(fieldnames):
    return {((name or "").strip().lower()): name for name in fieldnames or []}


def cell(row, headers, *candidates):
    for candidate in candidates:
        key = headers.get(candidate)
        if key and row.get(key) is not None:
            return str(row.get(key)).strip()
    return ""


def year_from_filename(path: Path) -> str:
    match = re.search(r"(20\d{2}|19\d{2})", path.name)
    return match.group(1) if match else ""


def parse_sale_file(path: Path, sale_title: str, sale_year: str):
    extras = {}
    with path.open(encoding="utf-8-sig", newline="", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        headers = header_map(reader.fieldnames)
        for row in reader:
            hip = cell(row, headers, "hip", "hip number", "hip_no")
            if hip.isdigit():
                hip = hip.zfill(4)
            extras[hip] = {
                "sire_of_dam": cell(row, headers, "sire of dam"),
                "color": cell(row, headers, "color"),
                "foaled": cell(row, headers, "foaled"),
                "consignor": cell(row, headers, "property line", "propertyline1", "consignor"),
                "purchaser": cell(row, headers, "purchaser", "buyer", "buyer name"),
                "sold_as": cell(row, headers, "sold as description", "soldas", "sold as"),
            }
    records = sales_history.load_and_process_csv(path)
    rows = []
    for record in records:
        hip = str(record.get("hip") or "")
        extra = extras.get(hip, {})
        sold_as = extra.get("sold_as") or ""
        if not sold_as:
            lower = path.name.lower()
            if "yearling" in lower or "saratoga sale" in lower:
                sold_as = "Yearling"
        rows.append({
            "sale_title": sale_title,
            "sale_year": sale_year,
            "hip": hip,
            "horse_name": record.get("name") or "",
            "sex": record.get("sex") or "",
            "sire": record.get("sire") or "",
            "dam": record.get("dam") or "",
            "sire_of_dam": extra.get("sire_of_dam") or "",
            "birth_year": record.get("birth_year") or "",
            "price_num": record.get("price_num") or 0,
            "price_raw": record.get("price_raw") or "",
            "is_rna": 1 if record.get("is_rna") else 0,
            "is_out": 1 if record.get("is_out") else 0,
            "purchaser": extra.get("purchaser") or "",
            "consignor": extra.get("consignor") or "",
            "color": extra.get("color") or "",
            "foaled": extra.get("foaled") or "",
            "sold_as": sold_as,
            "source_file": str(path.relative_to(ROOT)),
        })
    return rows


def build_sale_rows(all_sales: bool):
    files = []
    if all_sales:
        files = sorted((ROOT / "sales_data").glob("*.csv"))
    else:
        files = sorted((ROOT / "sales_data").glob(DEMO_GLOB))
    sale_rows = []
    result_rows = []
    seen_sales = set()
    sale_id = 1
    result_id = 1
    for path in files:
        year = year_from_filename(path)
        if not year:
            continue
        if all_sales:
            title = sales_history.clean_title(path.name)
        else:
            title = SALE_TITLE
        parsed = parse_sale_file(path, title, year)
        key = (title, year)
        if key not in seen_sales:
            seen_sales.add(key)
            company = "Fasig-Tipton" if "fasig" in path.name.lower() else "Keeneland" if "keeneland" in path.name.lower() else ""
            if not all_sales:
                company = SALE_COMPANY
            sale_rows.append({
                "sale_id": sale_id,
                "sale_company": company,
                "sale_title": title,
                "sale_year": year,
                "sale_kind": "results",
                "month_index": sales_history.get_sale_month_index(title),
                "source_file": str(path.relative_to(ROOT)),
            })
            sale_id += 1
        for record in parsed:
            record["result_id"] = result_id
            result_id += 1
            result_rows.append(record)
    return sale_rows, result_rows, sale_id


def read_catalog():
    with CATALOG_FILE.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_profiles(mares_by_key):
    namespace = {}
    profile_path = ROOT / "stallion_profiles.py"
    if not profile_path.exists():
        profile_path = ROOT / "redundant_folders" / "stallion_profiles.py"
    exec(profile_path.read_text(encoding="utf-8"), namespace)
    profiles = namespace.get("stallion_profiles", {})
    rank_by_key = {placeholder_store.name_key(name): index for index, name in enumerate(SIRE_RANK, 1)}
    rows = []
    for name, data in profiles.items():
        key = placeholder_store.name_key(name)
        mares = mares_by_key.get(key)
        rows.append({
            "stallion_name": name,
            "farm": data.get("Farm", ""),
            "year_born": data.get("Year Born", ""),
            "stud_duty_year": data.get("Stud Duty Year", ""),
            "stud_fee": data.get("Stud Fee", 0),
            "status": data.get("Status", ""),
            "surface": data.get("Surface", ""),
            "height": data.get("Height", ""),
            "conformation": data.get("Conformation & Physical Profile", ""),
            "major_wins": data.get("Major Wins", "") if isinstance(data.get("Major Wins"), str) else "".join(data.get("Major Wins") or []),
            "career_highlight": data.get("Career Highlight", "") if isinstance(data.get("Career Highlight"), str) else "".join(data.get("Career Highlight") or []),
            "race_record": json.dumps(data.get("Race Record", {})),
            "progeny_racing_statistics": json.dumps(data.get("Progeny Racing Statistics", {})) if data.get("Progeny Racing Statistics") else "",
            "progeny_earnings_statistics": json.dumps(data.get("Progeny Earnings Statistics", {})) if data.get("Progeny Earnings Statistics") else "",
            "legacy_progeny_stats": json.dumps(data.get("Legacy Progeny Stats", {})) if data.get("Legacy Progeny Stats") else "",
            "sire_rank": rank_by_key.get(key, ""),
            "mares_bred_2025": "" if not mares else mares.get("mares_bred_2025") or "",
        })
    return rows, profiles


def build_broodmare_rows():
    import broodmare_sire_data
    rows = []
    for entry in broodmare_sire_data.broodmare_sire_raw:
        rows.append({key: entry.get(key, "") for key in placeholder_store.TABLES["broodmare_sire_stats"]})
    return rows


def build_mares_rows():
    import mares_bred_2025_by_stallion as mares
    rows = []
    by_key = {}
    for region, entries in mares.mares_bred_database.items():
        for entry in entries:
            row = {
                "stallion": entry.get("stallion") or "",
                "mares_bred_2025": "" if entry.get("mares_bred_2025") is None else entry.get("mares_bred_2025"),
                "state_prov": entry.get("state_prov") or "",
                "live_foal_percentage_for_2025_foals": entry.get("live_foal_percentage_for_2025_foals") or "",
                "live_foal_percentage_for_2024_foals": entry.get("live_foal_percentage_for_2024_foals") or "",
                "region": region,
            }
            rows.append(row)
            by_key[placeholder_store.name_key(row["stallion"])] = row
    return rows, by_key


def build_graded_rows():
    rows = []
    path = ROOT / "graded_stakes_winners.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            def clean(value):
                return re.sub(r"\s+", " ", (value or "")).strip()

            year = clean(raw.get("Race Year"))
            foal = clean(raw.get("Foaling Year"))
            rows.append({
                "race_name": clean(raw.get("Race Name")),
                "race_year": year if year.isdigit() else "",
                "horse_name": clean(raw.get("Horse Name")),
                "foaling_year": foal if foal.isdigit() else "",
                "sex": clean(raw.get("Sex")),
                "country": clean(raw.get("Country")),
                "track": clean(raw.get("Track")),
                "race_date": clean(raw.get("Date")),
                "distance": clean(raw.get("Distance")),
                "age": clean(raw.get("Age")),
                "purse": clean(raw.get("Purse")),
                "grade": clean(raw.get("Grade")),
            })
    return rows


def build_hypo_rows():
    namespace = {}
    hypo_path = ROOT / "hypofoals.py"
    if not hypo_path.exists():
        hypo_path = ROOT / "redundant_folders" / "hypofoals.py"
    exec(hypo_path.read_text(encoding="utf-8"), namespace)
    foals = namespace.get("HYPO_FOALS", {})
    rows = []
    for key, tree in foals.items():
        horse = tree.get("Horse", "") if isinstance(tree, dict) else ""
        sire = ""
        dam = ""
        if isinstance(tree, dict):
            sire_node = tree.get("Sire")
            dam_node = tree.get("Dam")
            if isinstance(sire_node, dict):
                sire, _, _ = split_name(sire_node.get("Horse", ""))
            if isinstance(dam_node, dict):
                dam, _, _ = split_name(dam_node.get("Horse", ""))
        rows.append({
            "mating_key": key,
            "horse_name": horse,
            "sire_name": sire,
            "dam_name": dam,
            "pedigree_json": json.dumps(tree),
        })
    return rows


class PedigreeWriter:
    def __init__(self, pedigree_index, class_map, profile_class):
        self.pedigree_index = pedigree_index
        self.class_map = class_map
        self.profile_class = profile_class
        self.horses = {}
        self.lines = []
        self.line_keys = set()
        self.next_horse = 1
        self.next_line = 1

    def class_of(self, name: str) -> str:
        key = placeholder_store.name_key(name)
        return self.class_map.get(key) or self.profile_class.get(key) or ""

    def pedigree_of(self, name: str):
        return self.pedigree_index.get(placeholder_store.name_key(name))

    def add_horse(self, name, year="", sex="", color="", country="", sire_name="", dam_name="", height="", conformation=""):
        key = placeholder_store.name_key(name)
        if not key:
            return
        current = self.horses.get(key)
        if current is None:
            self.horses[key] = {
                "horse_id": self.next_horse,
                "name": name,
                "name_key": key,
                "display_name": f"{name} ({year})" if year else name,
                "foaling_year": year,
                "sex": sex,
                "color": color,
                "country": country,
                "sire_name": sire_name,
                "dam_name": dam_name,
                "class_label": self.class_of(name),
                "height": height,
                "conformation": conformation,
            }
            self.next_horse += 1
            return
        for field, value in (
            ("foaling_year", year), ("sex", sex), ("color", color), ("country", country),
            ("sire_name", sire_name), ("dam_name", dam_name), ("height", height), ("conformation", conformation),
        ):
            if value and not current.get(field):
                current[field] = value
        if year and "(" not in current["display_name"]:
            current["display_name"] = f"{current['name']} ({year})"

    def add_line(self, subject, side, generation, relation, ancestor, year, klass):
        subject_key = placeholder_store.name_key(subject)
        token = (subject_key, side, generation, relation, placeholder_store.name_key(ancestor))
        if not subject_key or not ancestor or token in self.line_keys:
            return
        self.line_keys.add(token)
        self.lines.append({
            "line_id": self.next_line,
            "subject_name": subject,
            "subject_key": subject_key,
            "line_side": side,
            "generation": generation,
            "relation": relation,
            "ancestor_name": ancestor,
            "ancestor_year": year,
            "class_label": klass,
        })
        self.next_line += 1

    def walk(self, subject, sire_node, dam_node):
        node = sire_node
        generation = 1
        while isinstance(node, dict) and generation <= 5:
            name, year, country = split_name(node.get("Horse", ""))
            if not name:
                break
            sire_of = node.get("Sire") if isinstance(node.get("Sire"), dict) else {}
            dam_of = node.get("Dam") if isinstance(node.get("Dam"), dict) else {}
            sire_name, _, _ = split_name(sire_of.get("Horse", "")) if sire_of else ("", "", "")
            dam_name, _, _ = split_name(dam_of.get("Horse", "")) if dam_of else ("", "", "")
            self.add_horse(name, year=year, country=country, sire_name=sire_name, dam_name=dam_name)
            self.add_line(subject, "sire", generation, "sire", name, year, self.class_of(name))
            node = node.get("Sire")
            generation += 1

        node = dam_node
        generation = 1
        dam_relations = ["first_dam", "second_dam", "third_dam", "fourth_dam", "fifth_dam", "sixth_dam"]
        while isinstance(node, dict) and generation <= 6:
            name, year, country = split_name(node.get("Horse", ""))
            if not name:
                break
            sire_of = node.get("Sire") if isinstance(node.get("Sire"), dict) else {}
            dam_of = node.get("Dam") if isinstance(node.get("Dam"), dict) else {}
            sire_name, sire_year, _ = split_name(sire_of.get("Horse", "")) if sire_of else ("", "", "")
            dam_name, _, _ = split_name(dam_of.get("Horse", "")) if dam_of else ("", "", "")
            self.add_horse(name, year=year, country=country, sire_name=sire_name, dam_name=dam_name, sex="F")
            relation = dam_relations[generation - 1]
            self.add_line(subject, "dam", generation, relation, name, year, self.class_of(name))
            if sire_name:
                self.add_horse(sire_name, year=sire_year)
                self.add_line(subject, "dam", generation, "damsire", sire_name, sire_year, self.class_of(sire_name))
            node = node.get("Dam")
            generation += 1


def seed_accounts():
    roles = [
        ("Bloodstock Agent", "Buys and manages horses for clients"),
        ("Owner", "Races horses in their own name"),
        ("Breeder", "Plans matings and raises foals"),
        ("Owner/Breeder", "Breeds and races"),
        ("Trainer", "Trains runners"),
        ("Farm Manager", "Runs a stallion or broodmare farm"),
        ("Consignor", "Sells at auction"),
        ("Racing Manager", "Manages a racing stable"),
        ("Veterinarian", "Advises on soundness"),
        ("Other", "Another role in the industry"),
    ]
    accounts = [{
        "account_id": 1,
        "display_name": "Alex Rivera",
        "email": "alex.rivera@example.com",
        "industry_role": "Bloodstock Agent",
        "created_at": "2026-03-01",
    }]
    clients = [
        {"client_id": 1, "account_id": 1, "client_name": "Meadow Run"},
        {"client_id": 2, "account_id": 1, "client_name": "Lakeside Fillies"},
        {"client_id": 3, "account_id": 1, "client_name": "Empire State"},
    ]
    preferences = [
        {"preference_id": 1, "client_id": 1, "sex": "C", "foaled": "KY", "surface": "", "min_stud_fee": 100000, "max_stud_fee": "", "sire_name": "", "requires_producer_note": 0},
        {"preference_id": 2, "client_id": 2, "sex": "F", "foaled": "", "surface": "", "min_stud_fee": "", "max_stud_fee": 40000, "sire_name": "", "requires_producer_note": 0},
        {"preference_id": 3, "client_id": 3, "sex": "", "foaled": "NY", "surface": "", "min_stud_fee": "", "max_stud_fee": "", "sire_name": "", "requires_producer_note": 0},
    ]
    return (
        [{"role_name": name, "description": description} for name, description in roles],
        accounts,
        clients,
        preferences,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-sales", action="store_true", help="Load every sales_data CSV into sale_results")
    args = parser.parse_args()

    print("Loading pedigrees and stallion files...")
    pedigree_index = load_pedigree_index()
    class_map = load_graded_class()
    mares_rows, mares_by_key = build_mares_rows()
    profile_rows, profiles = build_profiles(mares_by_key)
    profile_class = {}
    for row in profile_rows:
        label = class_from_text(row.get("major_wins") or "")
        if label:
            profile_class[placeholder_store.name_key(row["stallion_name"])] = label
            class_map.setdefault(placeholder_store.name_key(row["stallion_name"]), label)

    print("Reading Saratoga results..." if not args.all_sales else "Reading every sales file...")
    sale_rows, result_rows, next_sale_id = build_sale_rows(args.all_sales)
    sale_rows.append({
        "sale_id": next_sale_id,
        "sale_company": SALE_COMPANY,
        "sale_title": SALE_TITLE,
        "sale_year": 2026,
        "sale_kind": "upcoming",
        "month_index": 8,
        "source_file": str(CATALOG_FILE.relative_to(ROOT)),
    })

    catalog = read_catalog()
    catalog_rows = []
    for index, raw in enumerate(catalog, 1):
        birth = raw.get("YEAR OF BIRTH") or ""
        year_match = re.search(r"\d{4}", birth)
        catalog_rows.append({
            "hip_id": index,
            "sale_title": SALE_TITLE,
            "sale_year": 2026,
            "hip": (raw.get("HIP") or "").strip(),
            "horse_name": (raw.get("HORSE NAME") or "").strip(),
            "sex": (raw.get("SEX") or "").strip(),
            "color": "",
            "sire": (raw.get("SIRE") or "").strip(),
            "dam": (raw.get("DAM") or "").strip(),
            "sire_of_dam": (raw.get("SIRE OF DAM") or "").strip(),
            "year_of_birth": year_match.group(0) if year_match else birth,
            "foaled": (raw.get("FOALED") or "").strip(),
            "sold_as": (raw.get("SOLD AS") or "").strip(),
            "covering_sire": (raw.get("COVERING SIRE") or "").strip(),
            "consignor": "",
            "notes": (raw.get("NOTES") or "").strip(),
            "cross_success": (raw.get("CROSS SUCCESS") or "").strip(),
            "dam_success_racer": (raw.get("DAM SUCCESS (RACER)") or "").strip(),
            "dam_success_producer": (raw.get("DAM SUCCESS (PRODUCER)") or "").strip(),
            "racing_success": (raw.get("RACING SUCCESS") or "").strip(),
            "starred": (raw.get("STARRED") or "").strip(),
            "source_file": str(CATALOG_FILE.relative_to(ROOT)),
        })

    print("Walking pedigrees for the catalog and stakes winners by those sires...")
    writer = PedigreeWriter(pedigree_index, class_map, profile_class)
    catalog_sire_keys = {placeholder_store.name_key(row["sire"]) for row in catalog_rows}
    for row in profile_rows:
        node = writer.pedigree_of(row["stallion_name"])
        sire_name = dam_name = ""
        if isinstance(node, dict):
            sire_node = node.get("Sire") if isinstance(node.get("Sire"), dict) else {}
            dam_node = node.get("Dam") if isinstance(node.get("Dam"), dict) else {}
            sire_name, _, _ = split_name(sire_node.get("Horse", "")) if sire_node else ("", "", "")
            dam_name, _, _ = split_name(dam_node.get("Horse", "")) if dam_node else ("", "", "")
        writer.add_horse(
            row["stallion_name"],
            year=row.get("year_born") or "",
            sex="H",
            sire_name=sire_name,
            dam_name=dam_name,
            height=row.get("height") or "",
            conformation=row.get("conformation") or "",
        )
        if isinstance(node, dict):
            writer.walk(row["stallion_name"], node.get("Sire"), node.get("Dam"))

    graded_rows = build_graded_rows()
    for row in graded_rows:
        key = placeholder_store.name_key(row["horse_name"])
        node = pedigree_index.get(key)
        if not isinstance(node, dict):
            continue
        sire_node = node.get("Sire") if isinstance(node.get("Sire"), dict) else {}
        sire_name, _, _ = split_name(sire_node.get("Horse", "")) if sire_node else ("", "", "")
        if placeholder_store.name_key(sire_name) not in catalog_sire_keys:
            continue
        writer.add_horse(row["horse_name"], year=row.get("foaling_year") or "", sex=row.get("sex") or "")
        writer.walk(row["horse_name"], node.get("Sire"), node.get("Dam"))

    dam_hits = 0
    for row in catalog_rows:
        writer.add_horse(
            row["horse_name"],
            year=row["year_of_birth"],
            sex=row["sex"],
            color=row["color"],
            sire_name=row["sire"],
            dam_name=row["dam"],
        )
        sire_node = writer.pedigree_of(row["sire"]) or {"Horse": row["sire"]}
        dam_node = writer.pedigree_of(row["dam"]) or {"Horse": row["dam"]}
        if writer.pedigree_of(row["dam"]):
            dam_hits += 1
        writer.walk(row["horse_name"], sire_node, dam_node)
        if isinstance(sire_node, dict) and sire_node.get("Sire"):
            writer.walk(row["sire"], sire_node.get("Sire"), sire_node.get("Dam"))

    roles, accounts, clients, preferences = seed_accounts()
    tables = {
        "industry_roles": roles,
        "accounts": accounts,
        "clients": clients,
        "client_preferences": preferences,
        "horses": list(writer.horses.values()),
        "pedigree_lines": writer.lines,
        "sales": sale_rows,
        "sale_results": result_rows,
        "catalog_hips": catalog_rows,
        "stallion_stats": profile_rows,
        "broodmare_sire_stats": build_broodmare_rows(),
        "mares_bred": mares_rows,
        "graded_stakes_winners": graded_rows,
        "notes": [],
        "hypothetical_matings": build_hypo_rows(),
    }
    DATA.mkdir(parents=True, exist_ok=True)
    for table, rows in tables.items():
        placeholder_store.write_table(table, rows)
        print(f"  {table}.csv  {len(rows)} rows")
    print(f"Catalog dams found in pedigrees_database: {dam_hits}/{len(catalog_rows)}")
    print(f"Demo catalog: {CATALOG_FILE.relative_to(ROOT)}")
    if not args.all_sales:
        print("sale_results holds every edition of Fasig-Tipton The Saratoga Sale in sales_data.")
        print("Re-run with --all-sales to load the rest of sales_data (large).")


if __name__ == "__main__":
    main()
