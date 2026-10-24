"""Sales hub queries over data/sales_lots.csv (via sample_db in-memory index)."""
import re

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


def _sale_price_num(raw):
    try:
        return int(float(str(raw or "0").replace(",", "").replace("$", "") or 0))
    except (TypeError, ValueError):
        return 0


def _is_catalog_label(horse_name):
    """Unnamed hips are listed as 'SIRE x DAM' (sometimes with a crop year)."""
    text = str(horse_name or "").strip()
    return not text or bool(re.search(r"\s[xX]\s", text)) or text.upper().startswith(("UNNAMED", "NAME"))


def auctions_for_horses(crosses, limit=40):
    """Sale rows from placeholderdatabase/sale_results.csv for similar-cross horses.

    Catalog hips are stored as SIRE x DAM labels. Match each cross horse by:
    (1) cleaned horse_name, or (2) sire+dam pair from the pedigree DB / cross row.
    """
    if not crosses:
        return []
    import placeholder_store
    import main

    targets = []  # (display_name, similarity, name_key, sire_key, dam_key)
    seen = set()
    for row in crosses:
        name = row.get("name") or ""
        key = placeholder_store.name_key(name) or sales_history.clean_search_string(name)
        if not key or key in seen:
            continue
        seen.add(key)
        sire = row.get("sire") or ""
        dam = row.get("dam") or ""
        ped = main.PEDIGREE_DATABASE.get(main.clean_horse_name(name)) or {}
        year_match = re.search(r"\((\d{4})\)", str(ped.get("Horse") or ""))
        foal_year = row.get("year") or (year_match.group(1) if year_match else "")
        if not sire or not dam:
            sire_node = ped.get("Sire") or {}
            dam_node = ped.get("Dam") or {}
            if not sire:
                sire = sire_node.get("Horse", "") if isinstance(sire_node, dict) else str(sire_node or "")
            if not dam:
                dam = dam_node.get("Horse", "") if isinstance(dam_node, dict) else str(dam_node or "")
        targets.append({
            "name": name,
            "similarity": row.get("similarity"),
            "name_key": key,
            "sire_key": placeholder_store.name_key(sire),
            "dam_key": placeholder_store.name_key(dam),
            "foal_year": str(foal_year or "").strip()[:4],
        })
    if not targets:
        return []

    by_name = {t["name_key"]: t for t in targets}
    by_pair = {}
    for t in targets:
        if t["sire_key"] and t["dam_key"]:
            by_pair.setdefault((t["sire_key"], t["dam_key"]), t)

    out = []
    for sale in placeholder_store.load_table("sale_results"):
        if str(sale.get("is_out") or "0") in {"1", "true", "True"}:
            continue
        horse = sale.get("horse_name") or ""
        hk = placeholder_store.name_key(horse)
        sk = placeholder_store.name_key(sale.get("sire") or "")
        dk = placeholder_store.name_key(sale.get("dam") or "")
        # Same name must also be the same parents (older horses reuse names), and a
        # sire/dam match only counts for an unnamed hip of the same foal crop, not a sibling.
        match = by_name.get(hk)
        if match and match["sire_key"] and match["dam_key"] and sk and dk and (sk, dk) != (match["sire_key"], match["dam_key"]):
            match = None
        if not match:
            pair = by_pair.get((sk, dk))
            named_other = hk and pair and hk != pair["name_key"] and not _is_catalog_label(horse)
            born = str(sale.get("birth_year") or "").strip()[:4]
            wrong_crop = pair and pair["foal_year"] and born and born != pair["foal_year"]
            if pair and not named_other and not wrong_crop:
                match = pair
        if not match:
            continue
        price_num = _sale_price_num(sale.get("price_num"))
        price_raw = sale.get("price_raw") or ""
        is_rna = str(sale.get("is_rna") or "0") in {"1", "true", "True"} or (
            price_raw and "RNA" in str(price_raw).upper()
        )
        out.append({
            "name": match["name"],
            "similarity": match["similarity"],
            "sale": sale.get("sale_title") or "",
            "year": sale.get("sale_year") or "",
            "hip": sale.get("hip") or "",
            "price_raw": price_raw,
            "price_num": price_num,
            "is_rna": is_rna,
            "purchaser": sale.get("purchaser") or "",
        })
    out.sort(key=lambda item: (
        -(item["similarity"] if item["similarity"] is not None else -1),
        -(int(str(item["year"] or "0") or 0) if str(item["year"] or "").isdigit() else 0),
        -(item["price_num"] or 0),
    ))
    return out[:limit]
