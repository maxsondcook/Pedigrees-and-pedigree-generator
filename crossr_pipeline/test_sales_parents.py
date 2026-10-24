from datetime import datetime, timedelta, timezone
from pathlib import Path

from crossr_pipeline import sales_parents as sp
from equibase_scraper.parse import narrow_yearless, resolve_html

FIXTURES = Path(__file__).resolve().parents[1] / "equibase_scraper" / "fixtures"


def test_yob_window_bounds_parent_age():
    assert sp.yob_window("dam", 2015, 2022) == (1997, 2012)
    assert sp.yob_window("sire", 2010, 2024) == (1994, 2007)
    assert sp.yob_window("dam", None, 2022) is None
    # Foals 30 years apart cannot share a dam.
    assert sp.yob_window("dam", 1990, 2020) is None


def test_pick_row_uses_sire_and_window():
    item = {"role": "dam", "sire": "Storm Cat", "yob_range": (2000, 2012)}
    rows = [
        {"id": "1", "sire": "Seattle Slew", "foal_year": "2005", "status": "ok"},
        {"id": "2", "sire": "STORM CAT", "foal_year": "2006", "status": "pending"},
        {"id": "3", "sire": "Storm Cat", "foal_year": "1988", "status": "ok"},
    ]
    row, why = sp.pick_row(rows, item)
    assert row["id"] == "2" and why == ""


def test_pick_row_prefers_single_ok_and_flags_ambiguous():
    item = {"role": "sire", "sire": "", "yob_range": None}
    rows = [{"id": "1", "status": "pending"}, {"id": "2", "status": "ok"}]
    assert sp.pick_row(rows, item)[0]["id"] == "2"
    rows = [{"id": "1", "status": "ok"}, {"id": "2", "status": "ok"}]
    assert sp.pick_row(rows, item) == (None, "ambiguous rows")
    assert sp.pick_row([], item) == (None, "no row")


def test_new_row_key_avoids_taken_keys():
    item = {"role": "dam", "name_key": "BELLA", "sire": "Tapit"}
    assert sp.new_row_key(item, lambda key: False) == "BELLA"
    assert sp.new_row_key(item, lambda key: True) == "BELLA [dam by TAPIT]"


def test_due_respects_done_and_retry_days():
    now = datetime.now(timezone.utc)
    item = {"key": "dam:X:"}
    assert sp.due(item, {}, now.timestamp())
    states = {"dam:X:": {"status": "complete", "last_attempt": now - timedelta(days=400)}}
    assert not sp.due(item, states, now.timestamp())
    states = {"dam:X:": {"status": "incomplete", "last_attempt": now - timedelta(days=5)}}
    assert not sp.due(item, states, now.timestamp())
    states = {"dam:X:": {"status": "incomplete", "last_attempt": now - timedelta(days=31)}}
    assert sp.due(item, states, now.timestamp())


def test_yearless_search_narrows_to_thoroughbred_stallion():
    html = (FIXTURES / "search_storm_cat.html").read_text()
    assert resolve_html(html, "")["kind"] == "ambiguous"
    resolved = resolve_html(html, "", None, None, (1975, 1990), "sire")
    assert resolved["kind"] == "candidate"
    assert resolved["candidate"]["name"] == "Storm Cat"
    assert resolved["candidate"]["yob"] == "1983"


def test_narrow_yearless_keeps_hits_when_a_filter_empties_them():
    rows = [{"breed": "QH", "sex": "Mare", "yob": "1957"}]
    assert narrow_yearless(rows, (2000, 2010), "sire") == rows


def test_pick_row_merges_duplicate_queue_rows():
    item = {"role": "dam", "sire": "Holy Bull", "yob_range": None}
    rows = [
        {"id": "1", "sire": "Holy Bull", "foal_year": "1997", "status": "pending"},
        {"id": "2", "sire": "Holy Bull", "foal_year": None, "status": "pending"},
    ]
    assert sp.pick_row(rows, item)[0]["id"] == "1"
