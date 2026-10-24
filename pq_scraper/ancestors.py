"""Discover incomplete 5-generation ancestor slots and stitch parent trees.

Mirrors pedigrees_cleaner.check_tree_is_incomplete / extract_all_ancestor_names_and_nodes
so the automated importer can queue the same horses the interactive cleaner would.
"""

from __future__ import annotations

import copy
import re
from typing import Callable

_YEAR_RE = re.compile(r"\((\d{4})\)")


def count_tree_depth(tree: dict | None) -> int:
    if not isinstance(tree, dict):
        return 0
    return 1 + max(
        count_tree_depth(tree.get("Sire")) if "Sire" in tree else 0,
        count_tree_depth(tree.get("Dam")) if "Dam" in tree else 0,
    )


def tree_is_incomplete(node, current_gen: int = 0, max_gen: int = 5) -> bool:
    if current_gen >= max_gen - 1:
        return False
    if not node or not isinstance(node, dict):
        return True
    sire_node = node.get("Sire")
    dam_node = node.get("Dam")
    if not sire_node or not isinstance(sire_node, dict) or "Horse" not in sire_node:
        return True
    if not dam_node or not isinstance(dam_node, dict) or "Horse" not in dam_node:
        return True
    sire_name = str(sire_node.get("Horse") or "")
    dam_name = str(dam_node.get("Horse") or "")
    if "unknown" in sire_name.lower() or "unknown" in dam_name.lower():
        return True
    return tree_is_incomplete(sire_node, current_gen + 1, max_gen) or tree_is_incomplete(
        dam_node, current_gen + 1, max_gen
    )


def _label_parts(horse_full_name: str) -> tuple[str, str]:
    text = (horse_full_name or "").strip()
    match = _YEAR_RE.search(text)
    year = match.group(1) if match else ""
    base = _YEAR_RE.sub("", text).strip()
    return base, year


def extract_nodes(node, found: dict | None = None) -> dict:
    if found is None:
        found = {}
    if not node or not isinstance(node, dict):
        return found
    horse_full_name = str(node.get("Horse") or "").strip()
    if horse_full_name and "UNKNOWN" not in horse_full_name.upper():
        base_name, year = _label_parts(horse_full_name)
        key = (base_name.upper(), year)
        prev = found.get(key)
        if prev is None or count_tree_depth(node) > count_tree_depth(prev["node"]):
            found[key] = {
                "full_name": horse_full_name,
                "base_name": base_name,
                "year": year,
                "node": node,
            }
    if "Sire" in node:
        extract_nodes(node["Sire"], found)
    if "Dam" in node:
        extract_nodes(node["Dam"], found)
    return found


def incomplete_ancestor_queue(
    pedigree_map: dict,
    clean_fn: Callable[[str], str],
    existing_ids: set[tuple[str, str]] | None = None,
) -> list[dict]:
    """Horses in DB trees that still lack a complete 5-gen subtree.

    Includes top-level incomplete entries and embedded ancestors that are not
    already stored as a complete top-level tree.
    """
    existing_ids = existing_ids if existing_ids is not None else set()
    found: dict = {}
    for tree in pedigree_map.values():
        extract_nodes(tree, found)

    complete_ids = set()
    for key, tree in pedigree_map.items():
        clean = clean_fn(key)
        year = ""
        m = _YEAR_RE.search(str(key))
        if m:
            year = m.group(1)
        else:
            _, year = _label_parts(str((tree or {}).get("Horse") or ""))
        if clean and not tree_is_incomplete(tree):
            complete_ids.add((clean, year))

    queue = []
    seen = set()
    for (_base_upper, year), info in found.items():
        if not tree_is_incomplete(info["node"]):
            continue
        clean = clean_fn(info["base_name"])
        if not clean:
            continue
        pair = (clean, str(year or ""))
        if pair in complete_ids:
            continue
        if pair in seen:
            continue
        seen.add(pair)
        queue.append(
            {
                "name": info["base_name"],
                "year": str(year or ""),
                "country": "",
                "clean_key": clean,
            }
        )
    queue.sort(key=lambda h: (h["clean_key"], h["year"]))
    return queue


def is_unknown_label(label: str | None) -> bool:
    text = str(label or "").strip()
    return not text or "unknown" in text.lower()


def identity_of(label: str | None, clean_fn: Callable[[str], str]) -> tuple[str, str]:
    base, year = _label_parts(str(label or ""))
    return clean_fn(base), year


def same_identity(a: dict | None, b: dict | None, clean_fn: Callable[[str], str]) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    ca, ya = identity_of(a.get("Horse"), clean_fn)
    cb, yb = identity_of(b.get("Horse"), clean_fn)
    if not ca or not cb or ca != cb:
        return False
    if ya and yb and ya != yb:
        return False
    return True


def useful_node(node) -> bool:
    return isinstance(node, dict) and not is_unknown_label(node.get("Horse"))


def build_lookup_index(pedigree_map: dict, clean_fn: Callable[[str], str]) -> dict:
    """(clean_name, year) -> tree. Year-less names map only when unique."""
    by_pair: dict[tuple[str, str], dict] = {}
    by_name: dict[str, dict[str, dict]] = {}
    for key, tree in pedigree_map.items():
        if not useful_node(tree):
            continue
        year = ""
        m = _YEAR_RE.search(str(key))
        if m:
            year = m.group(1)
        else:
            _, year = _label_parts(str(tree.get("Horse") or ""))
        base, _ = _label_parts(str(key))
        clean = clean_fn(base) or clean_fn(key)
        if not clean:
            continue
        pair = (clean, str(year or ""))
        prev = by_pair.get(pair)
        if prev is None or count_tree_depth(tree) >= count_tree_depth(prev):
            by_pair[pair] = tree
        by_name.setdefault(clean, {})[str(year or "")] = by_pair[pair]
    return {"by_pair": by_pair, "by_name": by_name}


def lookup_tree(index: dict, name: str, year: str | None, clean_fn: Callable[[str], str]):
    """Return a DB tree for this name+year, or None if missing/ambiguous."""
    clean = clean_fn(name or "")
    year = "" if not year or str(year) in ("None", "N/A", "NAN") else str(year).strip()
    if not clean or not index:
        return None
    by_pair = index.get("by_pair") or {}
    by_name = index.get("by_name") or {}
    if year and (clean, year) in by_pair:
        return by_pair[(clean, year)]
    years = by_name.get(clean) or {}
    if year and year in years:
        return years[year]
    if not year:
        nonempty = {y: t for y, t in years.items() if y}
        if len(years) == 1:
            return next(iter(years.values()))
        if len(nonempty) == 1 and "" not in years:
            return next(iter(nonempty.values()))
        return None
    if "" in years and len(years) == 1:
        return years[""]
    return None


def merge_node(base: dict, extra: dict, clean_fn: Callable[[str], str]) -> tuple[dict, bool]:
    """Keep base identity; copy missing/unknown sire/dam from extra."""
    if not useful_node(extra):
        return base, False
    if not isinstance(base, dict):
        return copy.deepcopy(extra), True
    if useful_node(base) and useful_node(extra) and not same_identity(base, extra, clean_fn):
        return base, False
    out = dict(base)
    changed = False
    if (not useful_node(base) or not (base.get("Horse") or "").strip()) and extra.get("Horse"):
        out["Horse"] = extra["Horse"]
        changed = True
    for rel in ("Sire", "Dam"):
        b = base.get(rel)
        e = extra.get(rel)
        if useful_node(b) and useful_node(e) and same_identity(b, e, clean_fn):
            merged, c = merge_node(b, e, clean_fn)
            if c:
                out[rel] = merged
                changed = True
        elif not useful_node(b) and useful_node(e):
            out[rel] = copy.deepcopy(e)
            changed = True
    return out, changed


def stitch_node(
    node: dict,
    index: dict,
    clean_fn: Callable[[str], str],
    depth: int = 0,
    max_gen: int = 5,
    stack: tuple[tuple[str, str], ...] = (),
) -> tuple[dict, bool]:
    if not isinstance(node, dict) or depth >= max_gen:
        return node, False
    if not useful_node(node):
        return node, False
    if not tree_is_incomplete(node, depth, max_gen):
        return node, False
    ident = identity_of(node.get("Horse"), clean_fn)
    if ident[0] and ident in stack:
        return node, False
    changed = False
    base, year = _label_parts(str(node.get("Horse") or ""))
    tmpl = lookup_tree(index, base, year, clean_fn)
    if tmpl is not None and tmpl is not node:
        node, c = merge_node(node, tmpl, clean_fn)
        changed |= c
    new_stack = stack + (ident,) if ident[0] else stack
    for rel in ("Sire", "Dam"):
        child = node.get(rel)
        if isinstance(child, dict):
            new_child, c = stitch_node(child, index, clean_fn, depth + 1, max_gen, new_stack)
            if c:
                node[rel] = new_child
                changed = True
    return node, changed


def stitch_pedigree_map(
    pedigree_map: dict,
    clean_fn: Callable[[str], str],
    max_gen: int = 5,
    max_passes: int = 8,
) -> tuple[set[str], dict]:
    """Fill incomplete trees from parent records already in the map. Mutates map."""
    incomplete_before = sum(1 for t in pedigree_map.values() if tree_is_incomplete(t, 0, max_gen))
    updated: set[str] = set()
    passes = 0
    for _ in range(max_passes):
        passes += 1
        index = build_lookup_index(pedigree_map, clean_fn)
        pass_changed = False
        for key, tree in list(pedigree_map.items()):
            if not tree_is_incomplete(tree, 0, max_gen):
                continue
            new_tree, c = stitch_node(tree, index, clean_fn, 0, max_gen)
            if c:
                pedigree_map[key] = new_tree
                updated.add(key)
                pass_changed = True
        print(f"  pass {passes}: updated {len(updated)} trees so far", flush=True)
        if not pass_changed:
            break
    incomplete_after = sum(1 for t in pedigree_map.values() if tree_is_incomplete(t, 0, max_gen))
    stats = {
        "passes": passes,
        "keys_updated": len(updated),
        "incomplete_before": incomplete_before,
        "incomplete_after": incomplete_after,
        "top_level": len(pedigree_map),
    }
    return updated, stats
