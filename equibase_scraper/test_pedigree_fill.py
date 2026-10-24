"""5-generation pedigree walk. No network and no live database.

Run from the project root:
    python3 -m pytest equibase_scraper/test_pedigree_fill.py equibase_scraper/test_parse.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equibase_scraper.pedigree_fill import (
    AncestorQuery,
    build_ancestor_index,
    fill_profile_pedigree,
    lookup_ancestor,
)
from equibase_scraper.run import fetch_ancestor_profile, save_ancestor_page
from pq_scraper.ancestors import count_tree_depth, tree_is_incomplete

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _read(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def complete_tree(prefix: str, year: int, remaining: int = 5) -> dict:
    node = {"Horse": f"{prefix} ({year})"}
    if remaining <= 1:
        return node
    node["Sire"] = complete_tree(f"{prefix} S", year - 15, remaining - 1)
    node["Dam"] = complete_tree(f"{prefix} D", year - 15, remaining - 1)
    return node


def _book() -> dict:
    """Into Mischief is top-level. Yankee Gentleman exists only as a nested sire."""
    return {
        "INTO MISCHIEF": complete_tree("INTO MISCHIEF", 2005),
        "LITTLEPRINCESSEMMA": complete_tree("LITTLEPRINCESSEMMA", 2006),
        "CARRIER": {
            "Horse": "CARRIER (2010)",
            "Sire": complete_tree("YANKEE GENTLEMAN", 1999),
            "Dam": {"Horse": "UNRELATED MARE (2000)"},
        },
        "ECLIPTICAL": complete_tree("ECLIPTICAL", 1980),
        "ZETTA JET": complete_tree("ZETTA JET", 1981),
    }


def _subject(**parents) -> dict:
    profile = {
        "display_name": "American Pharoah",
        "foal_year": "2012",
        "registry": "T",
        "equibase_refno": "ap",
    }
    profile.update(parents)
    return profile


def test_nested_index_keeps_deepest_yankee_gentleman():
    index = build_ancestor_index(_book())
    found = lookup_ancestor(index, "Yankee Gentleman", "")
    assert found is not None
    assert found["Horse"] == "YANKEE GENTLEMAN (1999)"
    assert not tree_is_incomplete(found, 0, 5)
    shallow = {"Horse": "YANKEE GENTLEMAN (1999)"}
    index_again = build_ancestor_index(
        {
            "SHALLOW": shallow,
            "CARRIER": _book()["CARRIER"],
        }
    )
    assert count_tree_depth(lookup_ancestor(index_again, "Yankee Gentleman", "1999")) > 1


def test_both_parents_in_the_book_fetch_nothing():
    calls = []

    def fetch(req: AncestorQuery):
        calls.append(req.name)
        return None

    book = _book()
    deep = count_tree_depth(book["INTO MISCHIEF"])
    result = fill_profile_pedigree(
        _subject(
            sire="Into Mischief",
            sire_refno="im",
            dam="Littleprincessemma",
            dam_refno="lp",
        ),
        book,
        fetch,
    )
    assert calls == []
    assert result["fetches"] == 0
    assert result["tree"]["Sire"]["Horse"].startswith("INTO MISCHIEF")
    assert result["tree"]["Dam"]["Horse"].startswith("LITTLEPRINCESSEMMA")
    assert "Sire" in result["tree"]["Sire"]
    assert "Dam" in result["tree"]["Dam"]
    assert count_tree_depth(book["INTO MISCHIEF"]) == deep


def test_sire_in_book_dam_is_fetched_and_her_sire_grafts():
    calls = []
    profiles = {
        "Littleprincessemma": {
            "display_name": "Littleprincessemma",
            "foal_year": "2006",
            "sire": "Yankee Gentleman",
            "sire_refno": "yg",
            "dam": "Exclusive Rosette",
            "dam_refno": "er",
            "damsire": "Ecliptical",
            "damsire_refno": "ec",
            "registry": "T",
            "equibase_refno": "lp",
        },
        "Exclusive Rosette": {
            "display_name": "Exclusive Rosette",
            "foal_year": "1993",
            "sire": "Ecliptical",
            "sire_refno": "ec",
            "dam": "Zetta Jet",
            "dam_refno": "zj",
            "registry": "T",
            "equibase_refno": "er",
        },
    }

    def fetch(req: AncestorQuery):
        calls.append(req.name)
        return profiles[req.name]

    book = _book()
    del book["LITTLEPRINCESSEMMA"]
    result = fill_profile_pedigree(
        _subject(
            sire="Into Mischief",
            sire_refno="im",
            dam="Littleprincessemma",
            dam_refno="lp",
            damsire="Yankee Gentleman",
            damsire_refno="yg",
        ),
        book,
        fetch,
    )
    assert calls == ["Littleprincessemma", "Exclusive Rosette"]
    assert "Into Mischief" not in calls
    assert "Yankee Gentleman" not in calls
    assert "Ecliptical" not in calls
    assert "Zetta Jet" not in calls
    dam = result["tree"]["Dam"]
    assert dam["Horse"] == "LITTLEPRINCESSEMMA (2006)"
    assert dam["Sire"]["Horse"].startswith("YANKEE GENTLEMAN")
    assert dam["Dam"]["Horse"].startswith("EXCLUSIVE ROSETTE")
    assert result["tree"]["Sire"]["Horse"].startswith("INTO MISCHIEF")


def test_ambiguous_year_fetches_then_grafts_the_matching_year():
    calls = []

    def fetch(req: AncestorQuery):
        calls.append(req.refno)
        assert req.refno == "999"
        return {
            "display_name": "Into Mischief",
            "foal_year": "2005",
            "sire": "Should Not Matter",
            "sire_refno": "nope",
            "dam": "Also Not",
            "dam_refno": "nope2",
            "registry": "T",
            "equibase_refno": "999",
        }

    book = {
        "INTO MISCHIEF": complete_tree("INTO MISCHIEF", 2005),
        "INTO MISCHIEF (2010)": complete_tree("INTO MISCHIEF", 2010),
        "ZETTA JET": complete_tree("ZETTA JET", 1981),
    }
    result = fill_profile_pedigree(
        _subject(
            sire="Into Mischief",
            sire_refno="999",
            dam="Zetta Jet",
            dam_refno="zj",
        ),
        book,
        fetch,
    )
    assert calls == ["999"]
    assert result["tree"]["Sire"]["Horse"] == "INTO MISCHIEF (2005)"
    assert result["tree"]["Sire"]["Sire"]["Horse"].startswith("INTO MISCHIEF S")
    assert "SHOULD NOT MATTER" not in str(result["tree"])


def test_year_1969_does_not_fetch_parents_and_1970_does():
    calls = []

    def fetch(req: AncestorQuery):
        calls.append(req.name)
        return None

    stopped = fill_profile_pedigree(
        {
            "display_name": "Old Horse",
            "foal_year": "1969",
            "sire": "Ancient",
            "sire_refno": "1",
            "dam": "Ancient Mare",
            "dam_refno": "2",
            "registry": "T",
        },
        {},
        fetch,
    )
    assert calls == []
    assert stopped["tree"] == {"Horse": "OLD HORSE (1969)"}

    walked = fill_profile_pedigree(
        {
            "display_name": "Boundary Horse",
            "foal_year": "1970",
            "sire": "Still Walked",
            "sire_refno": "3",
            "dam": "Still Walked Mare",
            "dam_refno": "4",
            "registry": "T",
        },
        {},
        fetch,
    )
    assert calls == ["Still Walked", "Still Walked Mare"]
    assert walked["tree"]["Horse"] == "BOUNDARY HORSE (1970)"
    assert "Sire" in walked["tree"]
    assert "Dam" in walked["tree"]


def test_ancestor_born_before_1970_stops_that_branch():
    calls = []

    def fetch(req: AncestorQuery):
        calls.append(req.name)
        if req.name == "Young Sire":
            return {
                "display_name": "Young Sire",
                "foal_year": "1969",
                "sire": "Ancient",
                "sire_refno": "9",
                "dam": "Ancient Mare",
                "dam_refno": "8",
                "registry": "T",
                "equibase_refno": "ys",
            }
        if req.name == "Boundary Dam":
            return {
                "display_name": "Boundary Dam",
                "foal_year": "1970",
                "sire": "Ecliptical",
                "sire_refno": "ec",
                "dam": "Zetta Jet",
                "dam_refno": "zj",
                "registry": "T",
                "equibase_refno": "bd",
            }
        raise AssertionError(req.name)

    result = fill_profile_pedigree(
        {
            "display_name": "Catalog Horse",
            "foal_year": "2015",
            "sire": "Young Sire",
            "sire_refno": "ys",
            "dam": "Boundary Dam",
            "dam_refno": "bd",
            "registry": "T",
        },
        _book(),
        fetch,
    )
    assert calls == ["Young Sire", "Boundary Dam"]
    assert result["tree"]["Sire"] == {"Horse": "YOUNG SIRE (1969)"}
    assert result["tree"]["Dam"]["Horse"] == "BOUNDARY DAM (1970)"
    assert result["tree"]["Dam"]["Sire"]["Horse"].startswith("ECLIPTICAL")
    assert result["tree"]["Dam"]["Dam"]["Horse"].startswith("ZETTA JET")


def test_fetch_failure_leaves_a_stub_and_keeps_the_sire():
    calls = []

    def fetch(req: AncestorQuery):
        calls.append(req.name)
        return None

    book = _book()
    del book["LITTLEPRINCESSEMMA"]
    result = fill_profile_pedigree(
        _subject(
            sire="Into Mischief",
            sire_refno="im",
            dam="Littleprincessemma",
            dam_refno="lp",
            damsire="Yankee Gentleman",
            damsire_refno="yg",
        ),
        book,
        fetch,
    )
    assert calls == ["Littleprincessemma"]
    assert result["tree"]["Sire"]["Horse"].startswith("INTO MISCHIEF")
    assert "Sire" in result["tree"]["Sire"]
    assert result["tree"]["Dam"]["Horse"] == "LITTLEPRINCESSEMMA"
    assert result["tree"]["Dam"]["Sire"]["Horse"].startswith("YANKEE GENTLEMAN")


def test_save_profile_keeps_foal_year_and_ancestor_page_writes_the_race(tmp_path):
    from equibase_scraper import db

    conn = db.connect(tmp_path / "results.db")
    try:
        db.upsert_pending(
            conn,
            {
                "pedigree_key": "KEPT YEAR",
                "name_key": "KEPT YEAR",
                "foal_year": "2006",
                "display_name": "Kept Year",
            },
        )
        kept = db.find_horses(conn, "KEPT YEAR", "KEPT YEAR", "2006")[0]
        db.save_profile(
            conn,
            kept["id"],
            {
                "display_name": "Kept Year",
                "foal_year": "",
                "year_stats": [
                    {
                        "year": "2008",
                        "starts": 1,
                        "firsts": 1,
                        "seconds": 0,
                        "thirds": 0,
                        "highest_esf": 80,
                        "earnings": 100,
                        "earnings_per_start": 100,
                    }
                ],
                "starts": [
                    {
                        "race_date": "2008-05-01",
                        "track": "Churchill",
                        "place": "1",
                    }
                ],
            },
            "ok",
            "",
            "2026-10-15T00:00:00+00:00",
        )
        fresh = db.get_by_id(conn, kept["id"])
        assert fresh["foal_year"] == "2006"
        assert len(db.year_rows(conn, kept["id"])) == 1
        assert len(db.start_rows(conn, kept["id"])) == 1

        db.upsert_pending(
            conn,
            {
                "pedigree_key": "AMERICAN PHAROAH",
                "name_key": "AMERICAN PHAROAH",
                "foal_year": "2012",
                "display_name": "American Pharoah",
            },
        )
        pending = db.find_horses(conn, "AMERICAN PHAROAH", "AMERICAN PHAROAH", "2012")[0]
        assert pending["status"] == "pending"
        profile = save_ancestor_page(
            conn,
            _read("american_pharoah_profile.html"),
            existing=None,
            fallback_name="American Pharoah",
            fallback_year="",
        )
        assert profile["sire"] == "Pioneerof the Nile"
        assert profile["foal_year"] == "2012"
        stored = db.get_by_id(conn, pending["id"])
        assert stored["status"] == "ok"
        assert stored["foal_year"] == "2012"
        assert stored["equibase_refno"] == "9314281"
        assert stored["sire_refno"] == "7766522"
        assert len(db.year_rows(conn, pending["id"])) >= 1
        assert len(db.start_rows(conn, pending["id"])) == 11
        assert db.find_by_equibase_refno(conn, "9314281")["id"] == pending["id"]
        assert len(db.find_horses(conn, "AMERICAN PHAROAH", "AMERICAN PHAROAH", "2012")) == 1

        reused = fetch_ancestor_profile(
            None,
            conn,
            0,
            AncestorQuery("American Pharoah", "2012", "9314281", "T", "sire"),
        )
        assert reused["sire"] == "Pioneerof the Nile"
        assert reused["dam"] == "Littleprincessemma"
        assert reused["damsire"] == "Yankee Gentleman"
        assert db.get_by_id(conn, pending["id"])["status"] == "ok"
    finally:
        conn.close()
