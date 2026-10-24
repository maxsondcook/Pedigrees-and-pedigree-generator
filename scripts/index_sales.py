"""One-shot indexer: load sales_data CSVs into crossr_sales.db (backend only)."""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import sales_history  # noqa: E402

DB_PATH = os.environ.get("SALES_DB_PATH", os.path.join(ROOT, "crossr_sales.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalogs (
    id INTEGER PRIMARY KEY,
    year INTEGER NOT NULL,
    title TEXT NOT NULL,
    month_index INTEGER,
    source_file TEXT,
    UNIQUE(year, title)
);
CREATE TABLE IF NOT EXISTS lots (
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
    is_fasig INTEGER,
    FOREIGN KEY(catalog_id) REFERENCES catalogs(id)
);
CREATE INDEX IF NOT EXISTS idx_lots_sire ON lots(sire_key);
CREATE INDEX IF NOT EXISTS idx_lots_name ON lots(name_key);
CREATE INDEX IF NOT EXISTS idx_lots_dam ON lots(dam_key);
CREATE INDEX IF NOT EXISTS idx_lots_damsire ON lots(damsire_key);
CREATE INDEX IF NOT EXISTS idx_lots_catalog ON lots(catalog_id);
CREATE INDEX IF NOT EXISTS idx_lots_year ON lots(birth_year);
"""


def main():
    os.chdir(ROOT)
    db = sales_history.scan_sales_files()
    if not db:
        print("No sales CSVs found.")
        sys.exit(1)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    total_lots = 0
    catalog_count = 0

    for year, sales_map in sorted(db.items()):
        for title, file_path in sales_map.items():
            records = sales_history.load_and_process_csv(file_path)
            cur = conn.execute(
                "INSERT INTO catalogs (year, title, month_index, source_file) VALUES (?, ?, ?, ?)",
                (int(year), title, sales_history.get_sale_month_index(title), str(file_path)),
            )
            catalog_id = cur.lastrowid
            catalog_count += 1
            rows = []
            for r in records:
                rows.append((
                    catalog_id,
                    r.get("hip"),
                    r.get("name"),
                    sales_history.clean_search_string(r.get("name")),
                    r.get("sex"),
                    r.get("sex_letter"),
                    r.get("sire"),
                    sales_history.clean_search_string(r.get("sire")),
                    r.get("dam"),
                    sales_history.clean_search_string(r.get("dam")),
                    r.get("damsire"),
                    sales_history.clean_search_string(r.get("damsire")),
                    r.get("color"),
                    r.get("consignor"),
                    r.get("purchaser"),
                    r.get("barn"),
                    r.get("foaled_location"),
                    r.get("birth_year"),
                    r.get("price_raw"),
                    r.get("price_num") or 0,
                    1 if r.get("is_rna") else 0,
                    1 if r.get("is_out") else 0,
                    1 if r.get("is_fasig") else 0,
                ))
            conn.executemany(
                """INSERT INTO lots (
                    catalog_id, hip, name, name_key, sex, sex_letter, sire, sire_key,
                    dam, dam_key, damsire, damsire_key, color, consignor, purchaser, barn,
                    foaled_location, birth_year, price_raw, price_num, is_rna, is_out, is_fasig
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            total_lots += len(rows)
            print(f"  {year} {title}: {len(rows)} lots")
            conn.commit()

    conn.close()
    print(f"Indexed {catalog_count} catalogs / {total_lots} lots -> {DB_PATH}")


if __name__ == "__main__":
    main()
