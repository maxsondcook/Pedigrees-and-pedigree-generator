"""Queue: the sire and dam of every lot in sales_lots, missing a full 5-gen tree.

Order: sires first, then dams, each by their most recent sale (newest first),
then by how many lots they have. Sale lots carry a parent's name but not its
foal year, so each item carries what narrows an Equibase search instead:

* dams: the lot's damsire is the dam's sire (most common non-blank value
  across the dam's lots)
* both: a foal-year window from the parent's foals' birth years
"""

from __future__ import annotations

from collections import Counter

from equibase_scraper.pedigree_fill import covers_remaining, lookup_ancestor
from equibase_scraper.queue import clean_name

JOB = "pedigrees-sales"
QUEUE_BATCH = "sales-parents"

# Parent ages at a foal's birth. Stallions: first crop at 3+, rarely past 30.
# Mares: first foal at 3+, rarely past 25.
AGE_LIMITS = {"sire": (3, 30), "dam": (3, 25)}

# Item states that are final; others ("error", "incomplete") are retried.
DONE = {"complete", "not_found", "ambiguous", "year_mismatch"}
RETRY_DAYS = {"incomplete": 30, "error": 3}


def yob_window(role: str, first_foal: int | None, last_foal: int | None) -> tuple[int, int] | None:
    if not first_foal or not last_foal:
        return None
    youngest, oldest = AGE_LIMITS[role]
    low, high = last_foal - oldest, first_foal - youngest
    return (low, high) if low <= high else None


def item_key(role: str, name_key: str, sire_key: str = "") -> str:
    return f"{role}:{name_key}:{sire_key}"


def _int(value) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def load_parents(conn) -> list[dict]:
    """Every distinct sale sire and dam with the facts that narrow a search."""
    items: list[dict] = []
    sires = conn.execute(
        """
        SELECT sire_key, MAX(sire) AS name, MAX(catalog_year) AS latest, COUNT(*) AS lots,
               MIN(NULLIF(birth_year, '')) AS first_foal, MAX(NULLIF(birth_year, '')) AS last_foal
        FROM sales_lots WHERE COALESCE(sire_key, '') <> ''
        GROUP BY sire_key
        """
    ).fetchall()
    for row in sires:
        items.append(_item("sire", row, ""))

    damsires: dict[str, Counter] = {}
    for row in conn.execute(
        """
        SELECT dam_key, damsire FROM sales_lots
        WHERE COALESCE(dam_key, '') <> '' AND COALESCE(damsire, '') <> ''
        """
    ):
        damsires.setdefault(row["dam_key"], Counter())[row["damsire"].strip()] += 1
    dams = conn.execute(
        """
        SELECT dam_key, MAX(dam) AS name, MAX(catalog_year) AS latest, COUNT(*) AS lots,
               MIN(NULLIF(birth_year, '')) AS first_foal, MAX(NULLIF(birth_year, '')) AS last_foal
        FROM sales_lots WHERE COALESCE(dam_key, '') <> ''
        GROUP BY dam_key
        """
    ).fetchall()
    for row in dams:
        counts = damsires.get(row["dam_key"])
        items.append(_item("dam", row, counts.most_common(1)[0][0] if counts else ""))

    items.sort(key=lambda it: (it["role"] != "sire", -(it["latest"] or 0), -it["lots"], it["name_key"]))
    return items


def _item(role: str, row: dict, sire: str) -> dict:
    name = (row["name"] or "").strip()
    name_key = clean_name(name)
    sire_key = clean_name(sire) if sire else ""
    return {
        "role": role,
        "name": name,
        "name_key": name_key,
        "sire": sire,
        "key": item_key(role, name_key, sire_key),
        "latest": _int(row["latest"]),
        "lots": int(row["lots"] or 0),
        "yob_range": yob_window(role, _int(row["first_foal"]), _int(row["last_foal"])),
    }


def is_complete(index: dict, item: dict) -> bool:
    tree = lookup_ancestor(index, item["name"], None)
    return bool(tree) and covers_remaining(tree, 0)


def due(item: dict, states: dict, now_ts: float) -> bool:
    """False when the item is finished, or failed too recently to retry."""
    state = states.get(item["key"])
    if not state:
        return True
    status = state["status"]
    if status in DONE:
        return False
    days = RETRY_DAYS.get(status, 1)
    return now_ts - state["last_attempt"].timestamp() >= days * 86400


def build_queue(conn, index: dict, states: dict, now_ts: float, limit: int | None = None,
                role: str | None = None) -> tuple[list[dict], Counter]:
    """Items still to do, in order, plus counts of why the others were skipped."""
    skipped: Counter = Counter()
    todo = []
    for item in load_parents(conn):
        if role and item["role"] != role:
            continue
        if not item["name_key"]:
            skipped["no name"] += 1
        elif not due(item, states, now_ts):
            skipped["done or retry later"] += 1
        elif is_complete(index, item):
            skipped["already complete"] += 1
        else:
            todo.append(item)
            if limit and len(todo) >= limit:
                break
    return todo, skipped


def pick_row(rows: list[dict], item: dict) -> tuple[dict | None, str]:
    """Choose the race_horses row for a sale parent among same-name rows.

    Rows must agree with the item's sire (dams) and foal-year window when the
    row knows them. Several plausible rows: prefer a single ok one, otherwise
    it is ambiguous. Returns (row, reason) and row None when nothing fits.
    """
    sire_key = clean_name(item.get("sire") or "")
    window = item.get("yob_range")

    def fits(row) -> bool:
        if sire_key and row.get("sire") and clean_name(row["sire"]) != sire_key:
            return False
        year = _int(row.get("foal_year"))
        if window and year and not (window[0] <= year <= window[1]):
            return False
        return True

    plausible = [row for row in rows if fits(row)]
    if len(plausible) == 1:
        return plausible[0], ""
    if not plausible:
        return None, "no row"
    ok = [row for row in plausible if row.get("status") == "ok"]
    if len(ok) == 1:
        return ok[0], ""
    if not ok:
        # Older queue imports can hold one horse twice (with and without a
        # year). One distinct foal year among the rows means one horse.
        years = {row.get("foal_year") for row in plausible if row.get("foal_year")}
        if len(years) == 1:
            dated = [row for row in plausible if row.get("foal_year")]
            return dated[0], ""
    return None, "ambiguous rows"


def new_row_key(item: dict, taken) -> str:
    """pedigree_key for a new queue row: the clean name, else name + parent."""
    base = item["name_key"]
    if not taken(base):
        return base
    sire = clean_name(item.get("sire") or "")
    key = f"{base} [{item['role']}{' by ' + sire if sire else ''}]"
    return key
