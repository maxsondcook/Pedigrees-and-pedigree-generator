"""Build a 5-generation pedigree from the in-memory book and a fetch callback.

The subject is generation 1. A horse at generation 5 is a leaf. A horse born
before 1970 is a leaf too: that horse is kept, and their parents are not
fetched. A horse foaled in 1970 is still walked. Network and race-record
storage stay outside this module. ``fetch`` is called only for a horse the
book cannot already cover.
"""

from __future__ import annotations

import copy
from typing import Callable, NamedTuple

from pq_scraper.ancestors import count_tree_depth, tree_is_incomplete, useful_node
from pq_scraper.dbio import storage_key_for

from equibase_scraper.queue import clean_name, foaling_year, strip_year

MAX_GEN = 5
EARLIEST_YEAR = 1970


class AncestorQuery(NamedTuple):
    name: str
    year: str
    refno: str
    registry: str
    role: str = ""


def horse_label(name: str, year: str | None = None) -> str:
    """Database style: cleaned uppercase name, plus `` (YYYY)`` when known."""
    raw = name or ""
    year_s = str(year or "").strip()
    if year_s in {"None", "N/A", "NAN"}:
        year_s = ""
    if not year_s:
        year_s = foaling_year(raw)
    base = clean_name(strip_year(raw) if foaling_year(raw) else raw)
    if not base:
        base = clean_name(raw)
    if not base:
        return ""
    if year_s.isdigit():
        return f"{base} ({year_s})"
    return base


def born_before_1970(year: str | None) -> bool:
    text = str(year or "").strip()
    return text.isdigit() and int(text) < EARLIEST_YEAR


def build_ancestor_index(pedigree_map: dict) -> dict:
    """Deepest tree for every nested horse, keyed by cleaned name and year."""
    index: dict = {"by_pair": {}, "by_name": {}}
    for tree in pedigree_map.values():
        index_tree(index, tree)
    return index


def index_tree(index: dict, node) -> None:
    if not isinstance(node, dict):
        return
    if useful_node(node):
        label = str(node.get("Horse") or "")
        year = foaling_year(label)
        base = clean_name(strip_year(label) if year else label)
        if base:
            pair = (base, year)
            prev = index["by_pair"].get(pair)
            if prev is None or count_tree_depth(node) > count_tree_depth(prev):
                index["by_pair"][pair] = node
                index["by_name"].setdefault(base, {})[year] = node
    for rel in ("Sire", "Dam"):
        child = node.get(rel)
        if isinstance(child, dict):
            index_tree(index, child)


def lookup_ancestor(index: dict, name: str, year: str | None) -> dict | None:
    """Match name+year. Several years and no year yet means do not guess."""
    clean = clean_name(name or "")
    if not clean or not index:
        return None
    year_s = str(year or "").strip()
    if year_s in {"None", "N/A", "NAN"}:
        year_s = ""
    by_pair = index.get("by_pair") or {}
    by_name = index.get("by_name") or {}
    if year_s:
        return by_pair.get((clean, year_s))
    years = by_name.get(clean) or {}
    nonempty = {key: tree for key, tree in years.items() if key}
    if len(nonempty) == 1:
        return next(iter(nonempty.values()))
    if len(nonempty) > 1:
        return None
    if "" in years:
        return years[""]
    return None


def covers_remaining(node, current_gen: int, max_gen: int = MAX_GEN) -> bool:
    return useful_node(node) and not tree_is_incomplete(node, current_gen, max_gen)


def stored_pedigree_complete(index: dict, name: str, year: str | None) -> bool:
    tree = lookup_ancestor(index, name, year)
    return covers_remaining(tree, 0)


def trim_tree(node: dict, current_gen: int, max_gen: int = MAX_GEN) -> dict:
    """Copy ``node``, dropping ancestors past generation 5."""
    horse = node.get("Horse")
    if current_gen >= max_gen - 1:
        return {"Horse": horse}
    out = {"Horse": horse}
    for rel in ("Sire", "Dam"):
        child = node.get(rel)
        if useful_node(child):
            out[rel] = trim_tree(child, current_gen + 1, max_gen)
    return out


def _remember(pedigree_map: dict, index: dict, updated: set[str], node: dict) -> None:
    if not useful_node(node):
        return
    label = str(node.get("Horse") or "")
    year = foaling_year(label)
    clean = clean_name(strip_year(label) if year else label)
    if not clean:
        return
    key = storage_key_for(clean, year, pedigree_map, clean_name)
    prev = pedigree_map.get(key)
    if isinstance(prev, dict) and count_tree_depth(prev) >= count_tree_depth(node):
        return
    stored = copy.deepcopy(node)
    pedigree_map[key] = stored
    updated.add(key)
    index_tree(index, stored)


def _stub(name: str, year: str) -> dict | None:
    label = horse_label(name, year)
    if not label:
        return None
    return {"Horse": label}


def _graft(index: dict, name: str, year: str, current_gen: int) -> dict | None:
    tree = lookup_ancestor(index, name, year)
    if not useful_node(tree):
        return None
    label_year = foaling_year(str(tree.get("Horse") or ""))
    if born_before_1970(year) or born_before_1970(label_year):
        label = tree.get("Horse") or horse_label(name, year or label_year)
        return {"Horse": label}
    if not covers_remaining(tree, current_gen):
        return None
    return trim_tree(tree, current_gen)


def fill_profile_pedigree(
    profile: dict,
    pedigree_map: dict,
    fetch: Callable[[AncestorQuery], dict | None],
    *,
    index: dict | None = None,
    failed_refnos: set[str] | None = None,
    failed_names: set[tuple[str, str]] | None = None,
) -> dict:
    """Fill ``profile`` to 5 generations.

    ``fetch`` returns a parsed profile, or None when that horse cannot be
    loaded. It is not called for the subject. A process-wide failed set skips
    repeats. The returned ``updated_keys`` are pedigree_map keys written
    because the new tree is deeper than what was stored.
    """
    index = index if index is not None else build_ancestor_index(pedigree_map)
    failed_refnos = failed_refnos if failed_refnos is not None else set()
    failed_names = failed_names if failed_names is not None else set()
    updated: set[str] = set()
    fetches = 0
    name = str(profile.get("display_name") or "")
    year = str(profile.get("foal_year") or "").strip()

    def note_fetch() -> None:
        nonlocal fetches
        fetches += 1

    if stored_pedigree_complete(index, name, year):
        tree = lookup_ancestor(index, name, year)
        return {
            "tree": trim_tree(tree, 0),
            "updated_keys": set(),
            "skipped": True,
            "fetches": 0,
        }

    stack: set[tuple] = set()

    def resolve(parent_name: str, parent_year: str, refno: str, registry: str, gen: int, role: str) -> tuple[dict | None, bool]:
        parent_name = parent_name or ""
        parent_year = str(parent_year or "").strip()
        refno = str(refno or "").strip()
        registry = (registry or "T").strip() or "T"
        clean = clean_name(parent_name)
        if not parent_name and not refno:
            return None, False
        if refno and ("ref", refno) in stack:
            return _stub(parent_name, parent_year), False
        if clean and ("id", clean, parent_year) in stack:
            return _stub(parent_name, parent_year), False

        if born_before_1970(parent_year) or gen >= MAX_GEN - 1:
            grafted = _graft(index, parent_name, parent_year, gen)
            return grafted or _stub(parent_name, parent_year), False

        grafted = _graft(index, parent_name, parent_year, gen)
        if grafted is not None:
            return grafted, False

        if refno and refno in failed_refnos:
            return _stub(parent_name, parent_year), True
        if clean and (clean, parent_year) in failed_names:
            return _stub(parent_name, parent_year), True

        try:
            loaded = fetch(
                AncestorQuery(parent_name, parent_year, refno, registry, role)
            )
        except Exception as exc:
            if exc.__class__.__name__ == "Blocked":
                raise
            who = parent_name or refno or "ancestor"
            print(f"pedigree fetch failed {who}: {exc}", flush=True)
            loaded = None
        note_fetch()
        if not loaded:
            if refno:
                failed_refnos.add(refno)
            if clean:
                failed_names.add((clean, parent_year))
            return _stub(parent_name, parent_year), True

        loaded = _with_fallback_identity(loaded, parent_name, parent_year)
        got_year = str(loaded.get("foal_year") or "").strip()
        got_name = str(loaded.get("display_name") or parent_name)
        grafted = _graft(index, got_name, got_year, gen)
        if grafted is not None:
            return grafted, False
        return build_known(loaded, gen), False

    def build_known(loaded: dict, gen: int) -> dict:
        got_name = str(loaded.get("display_name") or "")
        got_year = str(loaded.get("foal_year") or "").strip()
        refno = str(loaded.get("equibase_refno") or "").strip()
        registry = (loaded.get("registry") or "T").strip() or "T"
        node = {"Horse": horse_label(got_name, got_year)}
        clean = clean_name(got_name)
        added = []
        if refno:
            token = ("ref", refno)
            stack.add(token)
            added.append(token)
        if clean:
            token = ("id", clean, got_year)
            stack.add(token)
            added.append(token)
        try:
            if born_before_1970(got_year) or gen >= MAX_GEN - 1:
                _remember(pedigree_map, index, updated, node)
                return node
            sire, _sire_failed = resolve(
                str(loaded.get("sire") or ""),
                "",
                str(loaded.get("sire_refno") or ""),
                registry,
                gen + 1,
                "sire",
            )
            dam, dam_failed = resolve(
                str(loaded.get("dam") or ""),
                "",
                str(loaded.get("dam_refno") or ""),
                registry,
                gen + 1,
                "dam",
            )
            if (
                dam_failed
                and loaded.get("damsire")
                and (gen + 1) < MAX_GEN - 1
            ):
                damsire, _failed = resolve(
                    str(loaded.get("damsire") or ""),
                    "",
                    str(loaded.get("damsire_refno") or ""),
                    registry,
                    gen + 2,
                    "damsire",
                )
                if dam is not None and damsire is not None:
                    dam = dict(dam)
                    dam["Sire"] = damsire
            if sire:
                node["Sire"] = sire
            if dam:
                node["Dam"] = dam
            _remember(pedigree_map, index, updated, node)
            return node
        finally:
            for token in added:
                stack.discard(token)

    tree = build_known(profile, 0)
    return {
        "tree": tree,
        "updated_keys": updated,
        "skipped": False,
        "fetches": fetches,
    }


def _with_fallback_identity(profile: dict, name: str, year: str) -> dict:
    out = dict(profile)
    if not out.get("display_name") and name:
        out["display_name"] = name
    if not out.get("foal_year") and year:
        out["foal_year"] = year
    return out
