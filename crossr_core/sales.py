"""Sales hub queries over data/sales_lots.csv (via sample_db in-memory index)."""
import sales_history
from crossr_core import sample_db

LOT_SELECT = """
    SELECT l.id, l.hip, l.name, l.sex, l.sex_letter, l.sire, l.dam, l.damsire,
           l.color, l.consignor, l.purchaser, l.barn, l.foaled_location, l.birth_year,
           l.price_raw, l.price_num, l.is_rna, l.is_out, l.is_fasig,
           c.year, c.title AS sale_title, c.month_index, l.catalog_id
    FROM lots l
    JOIN catalogs c ON c.id = l.catalog_id
"""


class _SharedConn:
    """Wrap the shared in-memory SQLite so callers' conn.close() is a no-op."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        return None


def db_path():
    return str(sample_db.csv_path("sales_lots"))


def ensure_damsire_index():
    # Index is created when sample_db builds the in-memory sales DB.
    return


def damsire_yearling_averages(stallion_name):
    """Catalog-year average sold yearling price for lots whose damsire is this stallion."""
    conn = connect()
    if not conn:
        return {}
    key = sales_history.clean_search_string(stallion_name)
    if not key:
        return {}
    try:
        rows = conn.execute(
            """
            SELECT c.year AS year, COUNT(*) AS n, AVG(l.price_num) AS avg_price
            FROM lots l
            JOIN catalogs c ON c.id = l.catalog_id
            WHERE l.damsire_key = ?
              AND l.is_rna = 0 AND l.is_out = 0 AND l.price_num > 0
              AND (
                LOWER(c.title) LIKE '%yearling%'
                OR LOWER(COALESCE(c.source_file, '')) LIKE '%yearling%'
              )
            GROUP BY c.year
            ORDER BY c.year DESC
            """,
            (key,),
        ).fetchall()
        out = {}
        for row in rows:
            year = int(row["year"])
            avg = float(row["avg_price"] or 0)
            out[year] = {"n": int(row["n"]), "avg_price": int(round(avg))}
        return out
    finally:
        conn.close()


def connect():
    """In-memory index derived from data/sales_lots.csv; refreshes on mtime."""
    conn = sample_db.sales_connection()
    return _SharedConn(conn) if conn is not None else None


def _lot_from_row(row):
    d = dict(row)
    d["is_rna"] = bool(d.get("is_rna"))
    d["is_out"] = bool(d.get("is_out"))
    d["is_fasig"] = bool(d.get("is_fasig"))
    d["year"] = str(d.get("year") or "")
    d["sale"] = d.get("sale_title") or d.get("sale") or ""
    return d


def list_years():
    conn = connect()
    if not conn:
        return []
    try:
        rows = conn.execute("SELECT DISTINCT year FROM catalogs ORDER BY year DESC").fetchall()
        return [r["year"] for r in rows]
    finally:
        conn.close()


def list_catalogs(year=None):
    conn = connect()
    if not conn:
        return []
    try:
        if year:
            rows = conn.execute(
                "SELECT id, year, title, month_index FROM catalogs WHERE year = ? ORDER BY month_index, title",
                (int(year),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, year, title, month_index FROM catalogs ORDER BY year DESC, month_index, title"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _query_lots(where_sql, params, sort="price_desc", sex=None, limit=100, offset=0, target_stallion=None):
    conn = connect()
    if not conn:
        return {"lots": [], "total": 0, "stats": None}
    clauses = [where_sql]
    args = list(params)
    if sex:
        clauses.append("l.sex_letter = ?")
        args.append(sex.upper()[:1])
    where = " AND ".join(clauses)
    order = {
        "price_desc": "l.price_num DESC",
        "price_asc": "l.price_num ASC",
        "hip": "l.hip ASC",
        "year_desc": "c.year DESC, c.month_index DESC",
        "name": "l.name ASC",
    }.get(sort, "l.price_num DESC")
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM lots l JOIN catalogs c ON c.id = l.catalog_id WHERE {where}",
            args,
        ).fetchone()["n"]
        rows = conn.execute(
            f"{LOT_SELECT} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            args + [limit, offset],
        ).fetchall()
        stat_rows = conn.execute(
            f"""
            SELECT l.price_num, l.is_rna, l.is_out, c.year
            FROM lots l
            JOIN catalogs c ON c.id = l.catalog_id
            WHERE {where}
            """,
            args,
        ).fetchall()
        records = [_lot_from_row(r) for r in rows]
        stat_records = [_lot_from_row(r) for r in stat_rows]
        return {
            "lots": records,
            "total": total,
            "stats": sales_history.calculate_sales_stats(stat_records, target_stallion=target_stallion),
        }
    finally:
        conn.close()


def catalog_lots(catalog_id, sort="price_desc", sex=None, limit=80, offset=0):
    return _query_lots("l.catalog_id = ?", [int(catalog_id)], sort=sort, sex=sex, limit=limit, offset=offset)


def sire_lots(sire_name, sort="year_desc", sex=None, limit=80, offset=0):
    key = sales_history.clean_search_string(sire_name)
    return _query_lots(
        "l.sire_key = ?",
        [key],
        sort=sort,
        sex=sex,
        limit=limit,
        offset=offset,
        target_stallion=sire_name,
    )


def horse_lots(name="", year="", sire="", dam="", sort="year_desc", limit=80, offset=0):
    identity = []
    params = []
    if name:
        identity.append("l.name_key = ?")
        params.append(sales_history.clean_search_string(name))
    if sire and dam:
        identity.append("(l.sire_key = ? AND l.dam_key = ?)")
        params.append(sales_history.clean_search_string(sire))
        params.append(sales_history.clean_search_string(dam))
    elif sire:
        identity.append("l.sire_key = ?")
        params.append(sales_history.clean_search_string(sire))
    elif dam:
        identity.append("l.dam_key = ?")
        params.append(sales_history.clean_search_string(dam))
    if not identity:
        return {"lots": [], "total": 0, "stats": None}
    clauses = ["(" + " OR ".join(identity) + ")"]
    if year:
        clauses.append("l.birth_year = ?")
        params.append(str(year).strip())
    return _query_lots(" AND ".join(clauses), params, sort=sort, limit=limit, offset=offset)


def get_lot(lot_id):
    conn = connect()
    if not conn:
        return None
    try:
        row = conn.execute(f"{LOT_SELECT} WHERE l.id = ?", (int(lot_id),)).fetchone()
        if not row:
            return None
        lot = _lot_from_row(row)
        sire_key = sales_history.clean_search_string(lot.get("sire") or "")
        comparable = []
        if sire_key:
            comparable = conn.execute(
                f"""
                {LOT_SELECT}
                WHERE l.sire_key = ? AND l.id != ? AND l.is_out = 0 AND l.price_num > 0
                ORDER BY ABS(l.price_num - ?) ASC
                LIMIT 8
                """,
                (sire_key, int(lot_id), lot.get("price_num") or 0),
            ).fetchall()
        sire_stats = sire_lots(lot.get("sire") or "", limit=1) if lot.get("sire") else {"stats": None}
        return {
            "lot": lot,
            "comparables": [_lot_from_row(r) for r in comparable],
            "sire_stats": sire_stats.get("stats"),
        }
    finally:
        conn.close()


def catalog_nav(catalog_id):
    """Compact hip list for walking a past catalog. No price aggregates."""
    conn = connect()
    if not conn:
        return None
    try:
        cat = conn.execute(
            "SELECT id, year, title FROM catalogs WHERE id = ?",
            (int(catalog_id),),
        ).fetchone()
        if not cat:
            return None
        rows = conn.execute(
            f"""
            {LOT_SELECT}
            WHERE l.catalog_id = ?
            ORDER BY CAST(l.hip AS INTEGER), l.hip
            """,
            (int(catalog_id),),
        ).fetchall()
        lots = []
        for row in rows:
            lot = _lot_from_row(row)
            lots.append({
                "id": lot["id"],
                "hip": lot.get("hip"),
                "name": lot.get("name"),
                "sex": lot.get("sex"),
                "sex_letter": lot.get("sex_letter"),
                "color": lot.get("color"),
                "sire": lot.get("sire"),
                "dam": lot.get("dam"),
                "birth_year": lot.get("birth_year"),
                "consignor": lot.get("consignor"),
                "foaled": lot.get("foaled_location"),
                "price_raw": lot.get("price_raw"),
                "price_num": lot.get("price_num") or 0,
                "is_rna": lot.get("is_rna"),
            })
        return {"catalog": dict(cat), "lots": lots, "total": len(lots)}
    finally:
        conn.close()


def auctions_for_horses(crosses, limit=40):
    """Sale rows for similar-cross horses: name, similarity, sale, price."""
    if not crosses:
        return []
    sim_by_key = {}
    name_by_key = {}
    ordered_keys = []
    for row in crosses:
        name = row.get("name") or ""
        key = sales_history.clean_search_string(name)
        if not key:
            continue
        similarity = row.get("similarity")
        previous = sim_by_key.get(key)
        if key not in sim_by_key:
            ordered_keys.append(key)
        if previous is None or (similarity is not None and similarity > previous):
            sim_by_key[key] = similarity
            name_by_key[key] = name
    if not ordered_keys:
        return []
    conn = connect()
    if not conn:
        return []
    try:
        placeholders = ",".join("?" * len(ordered_keys))
        rows = conn.execute(
            f"""
            SELECT l.name, l.name_key, l.hip, l.price_raw, l.price_num, l.is_rna, l.purchaser,
                   c.title AS sale, c.year
            FROM lots l
            JOIN catalogs c ON c.id = l.catalog_id
            WHERE l.name_key IN ({placeholders}) AND l.is_out = 0
            """,
            ordered_keys,
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        key = row["name_key"]
        out.append({
            "name": name_by_key.get(key) or row["name"],
            "similarity": sim_by_key.get(key),
            "sale": row["sale"],
            "year": row["year"],
            "hip": row["hip"],
            "price_raw": row["price_raw"],
            "price_num": row["price_num"],
            "is_rna": bool(row["is_rna"]),
            "purchaser": row["purchaser"],
        })
    out.sort(key=lambda item: (
        -(item["similarity"] if item["similarity"] is not None else -1),
        -(int(item["year"] or 0)),
        -(item["price_num"] or 0),
    ))
    return out[:limit]
