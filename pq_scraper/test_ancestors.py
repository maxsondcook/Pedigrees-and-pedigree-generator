from copy import deepcopy

from main import clean_horse_name as _clean
from pq_scraper.ancestors import (
    incomplete_ancestor_queue,
    lookup_tree,
    build_lookup_index,
    stitch_pedigree_map,
    tree_is_incomplete,
)


def test_incomplete_unknown_parents():
    node = {
        "Horse": "TEST (2000)",
        "Sire": {"Horse": "UNKNOWN SIRE"},
        "Dam": {"Horse": "UNKNOWN DAM"},
    }
    assert tree_is_incomplete(node)


def test_complete_five_gen_stub():
    def leaf(name):
        return {"Horse": name}

    def pair(name, sire, dam):
        return {"Horse": name, "Sire": sire, "Dam": dam}

    # 5 generations of named horses — incomplete check stops at gen 4.
    g4s = leaf("S4 (1900)")
    g4d = leaf("D4 (1900)")
    g3 = pair("S3 (1920)", g4s, g4d)
    g3d = pair("D3 (1920)", leaf("X (1900)"), leaf("Y (1900)"))
    g2 = pair("S2 (1940)", g3, g3d)
    g2d = pair("D2 (1940)", g3, g3d)
    g1 = pair("S1 (1960)", g2, g2d)
    g1d = pair("D1 (1960)", g2, g2d)
    root = pair("ROOT (1980)", g1, g1d)
    assert not tree_is_incomplete(root)


def test_queue_includes_incomplete_subject():
    node = {
        "Horse": "TEST (2000)",
        "Sire": {"Horse": "UNKNOWN SIRE"},
        "Dam": {"Horse": "UNKNOWN DAM"},
    }
    q = incomplete_ancestor_queue({"TEST": node}, lambda s: " ".join(s.upper().split()))
    assert any(h["clean_key"] == "TEST" for h in q)


def _five_gen(name: str, year: int) -> dict:
    def leaf(n):
        return {"Horse": n}

    def pair(n, sire, dam):
        return {"Horse": n, "Sire": sire, "Dam": dam}

    y = year
    g4s = leaf(f"{name} GGS ({y - 80})")
    g4d = leaf(f"{name} GGD ({y - 80})")
    g3 = pair(f"{name} GS ({y - 60})", g4s, g4d)
    g3d = pair(f"{name} GD ({y - 60})", leaf(f"{name} X ({y - 80})"), leaf(f"{name} Y ({y - 80})"))
    g2 = pair(f"{name} S2 ({y - 40})", g3, g3d)
    g2d = pair(f"{name} D2 ({y - 40})", deepcopy(g3), deepcopy(g3d))
    g1 = pair(f"{name} SIRE ({y - 20})", g2, g2d)
    g1d = pair(f"{name} DAM ({y - 20})", deepcopy(g2), deepcopy(g2d))
    return pair(f"{name} ({y})", g1, g1d)


def test_lookup_skips_wrong_year_homonym():
    idx = build_lookup_index(
        {
            "VATICANA (2010)": {"Horse": "VATICANA (2010)", "Sire": {"Horse": "A (1990)"}, "Dam": {"Horse": "B (1990)"}},
            "VATICANA (2018)": {"Horse": "VATICANA (2018)", "Sire": {"Horse": "C (2000)"}, "Dam": {"Horse": "D (2000)"}},
        },
        _clean,
    )
    hit = lookup_tree(idx, "VATICANA", "2018", _clean)
    assert hit["Horse"] == "VATICANA (2018)"
    assert lookup_tree(idx, "VATICANA", "", _clean) is None


def test_stitch_fills_child_from_parent_trees():
    sire = _five_gen("SIRESTAR", 2000)
    dam = _five_gen("DAMSTAR", 2001)
    child = {
        "Horse": "FOAL (2018)",
        "Sire": {"Horse": "SIRESTAR (2000)"},
        "Dam": {"Horse": "DAMSTAR (2001)"},
    }
    db = {"SIRESTAR": sire, "DAMSTAR": dam, "FOAL": child}
    updated, stats = stitch_pedigree_map(db, _clean)
    assert "FOAL" in updated
    assert not tree_is_incomplete(db["FOAL"])
    assert db["FOAL"]["Sire"]["Sire"]["Horse"] == sire["Sire"]["Horse"]
    assert stats["incomplete_after"] < stats["incomplete_before"]
