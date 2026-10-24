"""Load/save pedigrees_database.py in the existing one-line-repr format."""

from __future__ import annotations

import fcntl
import os
import re
from pathlib import Path

_YEAR_RE = re.compile(r"\((\d{4})\)")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_FILE = PROJECT_ROOT / "pedigrees_database.py"
LOCK_FILE = Path(__file__).resolve().parent / "db.lock"
BACKUP_NAME = "pedigrees_database.py.bak-before-pq"


def foaling_year(label: str | None) -> str:
    if not label:
        return ""
    m = _YEAR_RE.search(str(label))
    return m.group(1) if m else ""


def tree_year(tree: dict | None) -> str:
    if not isinstance(tree, dict):
        return ""
    return foaling_year(tree.get("Horse"))


def existing_name_years(pedigree_map: dict, clean_fn) -> set[tuple[str, str]]:
    """(cleaned name, foaling year) pairs already stored — year from key or tree."""
    out: set[tuple[str, str]] = set()
    for k, tree in pedigree_map.items():
        clean = clean_fn(k)
        if not clean:
            continue
        year = foaling_year(k) or tree_year(tree)
        out.add((clean, year))
    return out


def storage_key_for(clean: str, year: str, pedigree_map: dict, clean_fn) -> str:
    """Keep the first horse as NAME; later years become NAME (YYYY).

    Also copies the occupant to NAME (its year) so both trees are addressable.
    """
    year = str(year or "").strip()
    occupied = False
    for k, tree in list(pedigree_map.items()):
        if clean_fn(k) != clean:
            continue
        occupied = True
        existing_year = foaling_year(k) or tree_year(tree)
        if year and existing_year == year:
            return k
        if year and existing_year and existing_year != year:
            yk = f"{clean} ({existing_year})"
            if yk not in pedigree_map:
                pedigree_map[yk] = tree
    if occupied and year:
        return f"{clean} ({year})"
    return clean


def backup_database_once() -> Path:
    dest = PROJECT_ROOT / BACKUP_NAME
    if dest.exists():
        return dest
    dest.write_bytes(DB_FILE.read_bytes())
    return dest


def load_pedigree_map() -> dict:
    if not DB_FILE.is_file() or DB_FILE.stat().st_size == 0:
        return {}
    ns: dict = {}
    code = DB_FILE.read_text(encoding="utf-8")
    exec(compile(code, str(DB_FILE), "exec"), {"__name__": "pedigrees_database"}, ns)
    return ns.get("pedigree_map", {}) or {}


def save_pedigree_map(pedigree_map: dict, overwrite_keys: set[str] | None = None) -> None:
    """Match add_pedigrees/pedigrees_cleaner: sorted keys, repr(tree) per horse.

    Exclusive flock on db.lock; reload disk and merge new keys so a concurrent
    writer is not overwritten. overwrite_keys replaces incomplete ancestor trees.
    """
    overwrite_keys = overwrite_keys or set()
    LOCK_FILE.touch(exist_ok=True)
    with LOCK_FILE.open("a+") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            disk = load_pedigree_map()
            for horse, tree in pedigree_map.items():
                if horse not in disk or horse in overwrite_keys:
                    disk[horse] = tree
            pedigree_map.clear()
            pedigree_map.update(disk)
            tmp = DB_FILE.with_suffix(".py.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                f.write('"""\nAutomatically compiled pedigree database\n"""\n\n')
                f.write("pedigree_map = {\n")
                items = sorted(disk.items(), key=lambda kv: str(kv[0]))
                for horse, tree in items:
                    f.write(f"    {repr(horse)}: {repr(tree)},\n")
                f.write("}\n")
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(DB_FILE)
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
