"""Build the catalog horse list and enqueue it as one Equibase batch.

Does not fetch Equibase. Run the scraper later with --resume --batch.
"""

from __future__ import annotations

import csv
import sqlite3
from collections import Counter
from pathlib import Path

from equibase_scraper import db
from equibase_scraper.catalogs import (
    HorseIndex,
    clean_name,
    parse_pdf,
    pedigree_key_for,
    plausible,
    source_label,
    tidy_name,
)
from equibase_scraper.queue import clean_name as queue_clean

BATCH = "catalog-2026-10-15"
PROJECT = Path(__file__).resolve().parents[1]
LIST_PATH = PROJECT / "equibase_new_horses.csv"
REVIEW_PATH = PROJECT / "equibase_bare_names_review.csv"
PDF_DIR = Path("/Users/maxsoncook/Desktop/PDF PEDIGREES")
EXTRA = [
    Path("/Users/maxsoncook/Desktop/PedigreePDFS/FTSS2026.pdf"),
    Path("/Users/maxsoncook/Desktop/PedigreePDFS/fullsale.pdf"),
    Path("/Users/maxsoncook/Desktop/PedigreePDFS/web (1).pdf"),
    Path("/Users/maxsoncook/Desktop/PedigreePDFS/web (2).pdf"),
    Path("/Users/maxsoncook/Desktop/PedigreePDFS/web (3).pdf"),
    Path("/Users/maxsoncook/Desktop/PedigreePDFS/web (4).pdf"),
    Path("/Users/maxsoncook/Desktop/PedigreePDFS/web (5).pdf"),
    Path("/Users/maxsoncook/Desktop/PedigreePDFS/web (6).pdf"),
    Path("/Users/maxsoncook/Desktop/PedigreePDFS/web.pdf"),
    Path("/Users/maxsoncook/Desktop/PedigreePDFS/webHORA.pdf"),
]
STAKES = PROJECT / "data" / "graded_stakes.csv"


def catalog_pdfs() -> list[Path]:
    found = []
    if PDF_DIR.exists():
        found.extend(sorted(path for path in PDF_DIR.glob("*.pdf") if path.stat().st_size > 10000))
    for path in EXTRA:
        if path.exists():
            found.append(path)
    return found


def load_equibase(conn) -> tuple[set[tuple[str, str]], set[tuple[str, str, str]]]:
    name_year: set[tuple[str, str]] = set()
    name_parents: set[tuple[str, str, str]] = set()
    for row in conn.execute("SELECT name_key, foal_year, sire, dam FROM horses"):
        name = row["name_key"] or ""
        year = (row["foal_year"] or "").strip()
        if name and year:
            name_year.add((name, year))
        sire = queue_clean(row["sire"] or "")
        dam = queue_clean(row["dam"] or "")
        if name and sire and dam:
            name_parents.add((name, sire, dam))
    return name_year, name_parents


def already_stored(row: dict, name_year, name_parents) -> bool:
    if row["year"] and (row["name_key"], row["year"]) in name_year:
        return True
    if row["sire_key"] and row["dam_key"] and (row["name_key"], row["sire_key"], row["dam_key"]) in name_parents:
        return True
    return False


def add_graded_stakes(index: HorseIndex, name_year) -> tuple[int, int]:
    seen: set[tuple[str, str]] = set()
    added = 0
    skipped = 0
    with STAKES.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            display = tidy_name(row.get("Horse Name") or "")
            year = (row.get("Foaling Year") or row.get("Year Foaled") or "").strip()
            if not display or not year or not plausible(display):
                continue
            key = (clean_name(display), year)
            if key in seen:
                continue
            seen.add(key)
            if key in name_year:
                skipped += 1
                continue
            sex = (row.get("Sex") or "").strip()[:1].upper()
            index.add(display, "graded_stakes", year=year, sex=sex)
            added += 1
    return added, skipped


def main() -> None:
    import pickle

    pdfs = catalog_pdfs()
    pickle_path = Path("/tmp/equibase_catalog_index.pkl")
    if pickle_path.exists():
        with pickle_path.open("rb") as handle:
            index = pickle.load(handle)
        done = set(getattr(index, "files", set()))
        print(f"Loaded {len(index.rows())} horses from {len(done)} already parsed PDFs", flush=True)
    else:
        index = HorseIndex()
        index.files = set()
        done = set()
    pending = [path for path in pdfs if str(path) not in done]
    print(f"Parsing {len(pending)} new PDFs ({len(pdfs)} on disk)", flush=True)
    failures = []
    for number, path in enumerate(pending, start=1):
        try:
            pages = parse_pdf(path, index)
            index.files.add(str(path))
            print(f"[{number}/{len(pending)}] {path.name} pages={pages} horses={len(index.rows())}", flush=True)
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
            print(f"[{number}/{len(pending)}] FAILED {path.name}: {exc}", flush=True)

    conn = db.connect()
    try:
        name_year, name_parents = load_equibase(conn)
        graded_added, graded_skipped = add_graded_stakes(index, name_year)
        print(f"Graded stakes added {graded_added}, already in equibase {graded_skipped}", flush=True)

        year_counts: Counter[tuple[str, str]] = Counter()
        for row in index.rows():
            if row["year"]:
                year_counts[(row["name_key"], row["year"])] += 1
        shared_years = {key for key, count in year_counts.items() if count > 1}

        kept = []
        skipped_catalog = 0
        skipped_graded_only = 0
        for row in index.rows():
            if already_stored(row, name_year, name_parents):
                files = [item for item in row["sources"] if item != "graded_stakes"]
                if files:
                    skipped_catalog += 1
                else:
                    skipped_graded_only += 1
                continue
            kept.append(row)

        kept.sort(key=lambda row: (row["name_key"], row["year"], row["sire_key"], row["dam_key"]))
        with LIST_PATH.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["name", "foal_year", "sire", "dam", "sex", "source"])
            for row in kept:
                writer.writerow([
                    row["display_name"],
                    row["year"],
                    row["sire"],
                    row["dam"],
                    row["sex"],
                    source_label(row["sources"]),
                ])

        review = index.review_rows()
        with REVIEW_PATH.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["name", "name_key", "source"])
            writer.writerows(review)

        inserted = 0
        collisions = 0
        with conn:
            for row in kept:
                subject = {
                    "pedigree_key": pedigree_key_for(row, shared_years),
                    "name_key": row["name_key"],
                    "foal_year": row["year"],
                    "display_name": row["display_name"],
                    "sire": row["sire"],
                    "dam": row["dam"],
                    "sex": row["sex"],
                    "queue_batch": BATCH,
                }
                if db.insert_batch_horse(conn, subject):
                    inserted += 1
                else:
                    collisions += 1
        batch_pending = conn.execute(
            "SELECT COUNT(*) FROM horses WHERE queue_batch = ? AND status = 'pending'",
            (BATCH,),
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM horses").fetchone()[0]
        print(f"LIST {len(kept)} INSERTED {inserted} COLLISIONS {collisions} PENDING {batch_pending} TOTAL {total}", flush=True)
        print(f"SKIPPED_CATALOG {skipped_catalog} SKIPPED_GRADED_ONLY {skipped_graded_only}", flush=True)
        print(f"REVIEW {len(review)}", flush=True)
        catalog_rows = sum(1 for row in kept if any(item != "graded_stakes" for item in row["sources"]))
        graded_only = sum(1 for row in kept if row["sources"] == {"graded_stakes"})
        both = sum(1 for row in kept if "graded_stakes" in row["sources"] and any(item != "graded_stakes" for item in row["sources"]))
        print(f"QUEUED_CATALOG {catalog_rows} QUEUED_GRADED_ONLY {graded_only} QUEUED_BOTH {both}", flush=True)
        if failures:
            print("PDF_FAILURES", failures, flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
