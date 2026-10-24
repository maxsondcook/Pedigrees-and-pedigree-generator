"""Tests for agent2_parse, run against the real cached IFHA pages.

Every test that needs a specific page skips if that page is not in the cache,
so the suite stays green while the 2003-2026 fetch is still filling in.

The racepids below are from 2015 and were chosen because each one exercises a
documented trap:

    59931  colour contains a space ("DK B/")        -- fixed-width split
    60689  colour is blank                          -- fixed-width split
    39002  2003 race, winner reads "98 B M"         -- leading digits are YOB
    59159  Texas Mile S., no result published
    60442  dead heat for third, 4 finisher rows
    59742  distance in Furlongs
    59931  distance in Meters
    59316  purse in GBP (cp1252 "\xa3")             -- encoding
    59756  purse in JPY (cp1252 "\xa5")             -- encoding
"""

from __future__ import annotations

import json

import pytest

import agent2_parse as P
from agent1_fetch import HtmlCache, cache_key

CACHE = HtmlCache(P.ROOT / "cache")
NA = P.NA


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def raw_page(pid: str) -> str:
    html = CACHE.get(cache_key("GET", P.detail_url(pid)))
    if html is None:
        pytest.skip(f"racepid {pid} is not cached yet")
    return html


def parsed(pid: str):
    records, issues = P.parse_one(pid)
    if not records:
        pytest.skip(f"racepid {pid} is not cached yet")
    return records, issues


def issue_types(issues) -> set[str]:
    return {i["issue"] for i in issues}


def winner(records):
    return next(r for r in records if r["finish_position"] == 1)


def has_2015() -> bool:
    import asyncio

    async def check():
        async with P.CacheOnlyFetcher() as f:
            return f.listing_cached(2015)

    return asyncio.run(check())


# --------------------------------------------------------------------------- #
# the horse descriptor is FIXED WIDTH, not whitespace-delimited
# --------------------------------------------------------------------------- #


def test_descriptor_colour_containing_a_space():
    """'11 DK B/ H' -> yob 11, colour 'DK B/', sex H. A naive split gives 4 tokens."""
    records, _ = parsed("59931")
    first = winner(records)

    assert first["horse_name"] == "Liberal"
    assert first["horse_country_suffix"] == "PER"
    assert first["horse_yob_2digit"] == "11"
    assert first["horse_colour_code"] == "DK B/"
    assert first["horse_colour"] == "Dark Bay or Brown"
    assert first["horse_sex_code"] == "H"
    assert first["jockey"] == "Talaverano, E."

    # The reason the fixed-width rule is required at all.
    assert len(first["horse_descriptor_raw"].split()) == 4


def test_descriptor_blank_colour():
    """A blank 6-char colour field must not shift the sex code."""
    records, issues = parsed("60689")
    blank = [r for r in records if r["horse_colour_code"] == NA]
    assert blank, "expected at least one blank-colour runner on this page"

    row = blank[0]
    assert row["horse_colour"] == NA
    assert row["horse_sex_code"] in {"H", "M", "G", "R", "C", "F"}
    assert row["horse_yob_2digit"].isdigit()
    assert "colour_blank" in issue_types(issues)


def test_descriptor_split_unit():
    parts, problem = P.split_descriptor(" 11 DK B/ H")
    assert problem is None
    assert parts == {"yob2": "11", "colour_code": "DK B/", "sex_code": "H"}

    parts, problem = P.split_descriptor("11       G")  # blank colour
    assert problem is None
    assert parts == {"yob2": "11", "colour_code": None, "sex_code": "G"}

    parts, problem = P.split_descriptor("\xa012 DK B  H")  # &nbsp; prefix
    assert problem is None
    assert parts["colour_code"] == "DK B"

    parts, problem = P.split_descriptor("")
    assert problem == "descriptor_empty"
    assert parts["sex_code"] is None

    parts, problem = P.split_descriptor("not a descriptor at all")
    assert problem == "descriptor_malformed"


def test_every_2015_colour_code_resolves():
    """The colour codes IFHA actually emits must all map to a name."""
    for code in ["B", "CH", "DK B/", "DK B", "GR/RO", "GR", "BR",
                 "B/BR", "BLK", "GR/B", "BR/BL", "BL"]:
        assert P.colour_name(code), f"colour {code!r} does not resolve"


# --------------------------------------------------------------------------- #
# the leading two digits are YEAR OF BIRTH, not age
# --------------------------------------------------------------------------- #


def test_leading_digits_are_year_of_birth_not_age():
    """racepid 39002 is an Aug-2003 race whose winner reads '98 B M'."""
    records, _ = parsed("39002")
    first = winner(records)

    assert first["race_year"] == 2003
    assert first["horse_yob_2digit"] == "98"
    assert first["horse_foaling_year"] == 1998  # not "98 years old"
    assert first["horse_age"] == 5
    assert first["horse_sex_code"] == "M"


@pytest.mark.parametrize(
    "yob2, race_year, expected_foaled, expected_age",
    [
        ("98", 2003, 1998, 5),
        ("11", 2015, 2011, 4),
        ("00", 2004, 2000, 4),
        ("99", 2015, 1999, 16),
        ("12", 2015, 2012, 3),
    ],
)
def test_century_pivot(yob2, race_year, expected_foaled, expected_age):
    assert P.foaling_from_two_digit_yob(yob2, race_year) == (expected_foaled, expected_age)


def test_foaling_year_is_never_after_the_race():
    assert P.foaling_from_two_digit_yob("26", 2015)[0] == 1926
    assert P.foaling_from_two_digit_yob("", 2015) == (None, None)
    assert P.foaling_from_two_digit_yob("ab", 2015) == (None, None)
    assert P.foaling_from_two_digit_yob("11", None) == (None, None)


def test_2015_ages_are_plausible():
    if not has_2015():
        pytest.skip("2015 is not cached")
    records, _ = P.parse_all([2015], progress=False)
    ages = {r["horse_age"] for r in records if r["has_results"]}
    assert ages, "no ages derived"
    assert all(isinstance(a, int) and 2 <= a <= 15 for a in ages), sorted(ages, key=str)


# --------------------------------------------------------------------------- #
# races with nothing to parse
# --------------------------------------------------------------------------- #


def test_race_with_no_results_published():
    """0.8% of real races carry a full header but no finishers."""
    records, issues = parsed("59159")

    assert len(records) == 1
    row = records[0]
    assert row["has_results"] is False
    assert row["n_finishers"] == 0
    assert row["race_name"] == "Texas Mile S."     # race fields still parsed
    assert row["date_iso"] == "2015-04-24"
    assert row["group"] == "G3"
    assert row["finish_position"] == NA            # finisher fields all N/A
    assert row["horse_name"] == NA
    assert row["jockey"] == NA
    assert "no_results_published" in issue_types(issues)


def test_future_dated_race_with_no_race_data_block():
    """A future-dated race returns HTTP 200 with the whole block absent.

    Reproduced from a real cached page by removing exactly what the server
    omits, because no 2026 detail page is cached yet.
    """
    html = raw_page("59931")
    start = html.find(P.BEGIN_MARK)
    end = html.find(P.END_MARK, start)
    assert start > 0 and end > start
    empty = html[:start] + html[end + len(P.END_MARK):]

    assert P.race_data_block(empty) is None

    issues = P.IssueLog()
    records = P.parse_race({"racepid": "82671", "query_year": 2026}, empty, issues)

    assert len(records) == 1
    row = records[0]
    assert row["race_id"] == "82671"
    assert row["has_results"] is False
    assert row["race_name"] == NA
    assert row["horse_name"] == NA
    assert issue_types(issues.items) == {"empty_race_data"}
    # An empty page must not also generate a pile of missing-field noise.
    assert len(issues.items) == 1


def find_empty_detail_page():
    """First cached *detail* page with no race-data block, or None.

    Pages are located by racepid rather than by scanning the cache directory,
    so a listing page can never be mistaken for an empty detail page.
    """
    import asyncio

    from agent1_fetch import racepids

    async def scan():
        async with P.CacheOnlyFetcher() as fetcher:
            for year in range(2026, 2002, -1):
                if not fetcher.listing_cached(year):
                    continue
                listing = await fetcher.fetch_listing(year)
                for pid in racepids(listing):
                    html = CACHE.get(cache_key("GET", P.detail_url(pid)))
                    if html is not None and P.race_data_block(html) is None:
                        return pid, html
        return None

    return asyncio.run(scan())


def test_any_genuinely_empty_cached_page_is_handled():
    """If the running fetch has cached a real empty page, parse that one too."""
    found = find_empty_detail_page()
    if found is None:
        pytest.skip("no genuinely empty detail page cached yet")
    pid, html = found

    issues = P.IssueLog()
    records = P.parse_race({"racepid": pid, "query_year": 2026}, html, issues)
    assert len(records) == 1
    assert records[0]["has_results"] is False
    assert records[0]["race_id"] == pid
    assert issue_types(issues.items) == {"empty_race_data"}


def test_cache_miss_does_not_raise():
    issues = P.IssueLog()
    records = P.parse_race({"racepid": "999999999"}, P.CACHE_MISS, issues)
    assert len(records) == 1
    assert records[0]["has_results"] is False
    assert issue_types(issues.items) == {"detail_not_cached"}


def test_garbage_html_does_not_raise():
    issues = P.IssueLog()
    for junk in ("", "<html></html>", "not html at all", "<!---BEGIN RACE DATA HERE -->"):
        records = P.parse_race({"racepid": "1"}, junk, issues)
        assert len(records) == 1
        assert records[0]["has_results"] is False


# --------------------------------------------------------------------------- #
# distance units are mixed within a single year
# --------------------------------------------------------------------------- #


def test_meters_race():
    records, _ = parsed("59931")
    row = winner(records)
    assert row["distance_unit"] == "Meters"
    assert row["distance_value"] == 2100.0
    assert row["distance_metres"] == 2100.0
    assert row["distance_furlongs"] == 10.5
    assert row["distance_display"] == "10.5 Furlongs"
    assert row["surface"] == "D"
    assert row["surface_raw"] == "dirt"


def test_furlongs_race():
    records, _ = parsed("59742")
    row = winner(records)
    assert row["distance_unit"] == "Furlongs"
    assert row["distance_value"] == 10.0
    assert row["distance_metres"] == pytest.approx(2011.68, abs=0.1)
    assert row["distance_furlongs"] == 10.0
    assert row["surface"] == "T"


def test_fractional_furlongs_survive():
    """Epsom's Derby trip is 12.05 furlongs on the page; it must snap to 12f."""
    records, _ = parsed("59460")
    row = winner(records)
    assert row["distance_unit"] == "Furlongs"
    assert row["distance_value"] == 12.05
    assert row["distance_furlongs"] == 12.0
    assert row["race_name"].startswith("Investec Derby")
    assert row["horse_name"] == "Golden Horn"


def test_missing_distance_is_na_not_a_crash():
    """The 2003 page reads 'on the' with nothing after it."""
    records, issues = parsed("39002")
    row = winner(records)
    assert row["distance_value"] == NA
    assert row["distance_unit"] == NA
    assert row["distance_furlongs"] == NA
    assert "missing_distance" in issue_types(issues)


def test_both_units_appear_in_2015():
    if not has_2015():
        pytest.skip("2015 is not cached")
    records, _ = P.parse_all([2015], progress=False)
    units = {r["distance_unit"] for r in records if r["has_results"]}
    assert "Meters" in units and "Furlongs" in units


# --------------------------------------------------------------------------- #
# encoding: the pages are cp1252, and the cache holds the decoded text
# --------------------------------------------------------------------------- #


def test_sterling_symbol_survives():
    records, _ = parsed("59316")
    row = winner(records)
    assert "\u00a3" in row["purse_raw"], row["purse_raw"]
    assert row["purse_currency_symbol"] == "\u00a3"
    assert row["purse_currency"] == "GBP"
    assert row["purse_local_amount"] == 375000.0
    assert row["purse_usd_site"] == 585000.0
    assert row["race_name"] == "Queen Anne S."
    assert row["horse_name"] == "Solow"


def test_yen_symbol_survives():
    records, _ = parsed("59756")
    row = winner(records)
    assert "\u00a5" in row["purse_raw"], row["purse_raw"]
    assert row["purse_currency"] == "JPY"
    assert row["purse_local_amount"] == 197600000.0


def test_cached_pages_are_not_mojibake():
    """If a page had been decoded as UTF-8 the symbols would be U+FFFD."""
    html = raw_page("59316")
    assert "\ufffd" not in html
    assert "\u00c2\u00a3" not in html  # the classic cp1252-as-utf8 double encode


# --------------------------------------------------------------------------- #
# purse: both the site's own USD figure and the normalize.py conversion
# --------------------------------------------------------------------------- #


def test_captures_both_usd_figures():
    records, _ = parsed("59931")
    row = winner(records)
    assert row["purse_local_amount"] == 1_000_000.0
    assert row["purse_currency"] == "ARS"
    assert row["purse_usd_site"] == 118100.0          # IFHA's own figure
    assert isinstance(row["purse_usd_normalized"], float)  # normalize.py's
    assert row["purse_usd_normalized"] != row["purse_usd_site"]
    assert isinstance(row["purse_usd_delta_pct"], float)
    assert row["fx_provenance"] in {"ecb", "peg", "approximate"}


def test_usd_race_has_no_site_conversion():
    records, _ = parsed("59742")
    row = winner(records)
    assert row["purse_currency"] == "USD"
    assert row["purse_local_amount"] == 500000.0
    assert row["purse_usd_normalized"] == 500000.0
    assert row["purse_usd_site"] == NA  # the site does not convert USD to USD


def test_zero_purse_is_recorded_and_flagged():
    records, issues = parsed("39002")
    assert winner(records)["purse_local_amount"] == 0.0
    assert "zero_purse" in issue_types(issues)


def test_mislabelled_uae_purse_is_corrected():
    """IFHA prints Jebel Hatta's US$300,000 purse as 'AED 300,000 (*$300,000)'.

    Its own conversion equals the 'local' amount, which only happens when the
    amount was already USD.
    """
    records, issues = parsed("58976")
    row = winner(records)
    assert row["purse_currency_symbol"] == "AED"   # raw symbol preserved
    assert row["purse_currency"] == "USD"          # but the amount is USD
    assert row["purse_local_amount"] == 300000.0
    assert row["purse_usd_site"] == 300000.0
    assert row["purse_usd_normalized"] == 300000.0
    assert "purse_local_is_usd" in issue_types(issues)
    assert "purse_usd_disagrees" not in issue_types(issues)


def test_genuine_aed_purse_is_not_rewritten():
    """The Dubai World Cup really is carded in dirhams and converts properly."""
    records, issues = parsed("58985")
    row = winner(records)
    assert "Dubai World Cup" in row["race_name"]
    assert row["purse_currency"] == "AED"
    assert row["purse_local_amount"] == pytest.approx(36_724_201, rel=1e-6)
    assert row["purse_usd_site"] == 10_000_000.0
    assert row["purse_usd_normalized"] == pytest.approx(10_000_000, rel=0.001)
    assert "purse_local_is_usd" not in issue_types(issues)


def test_currency_resolution_prefers_an_unambiguous_symbol():
    """Istanbul's internationals are carded in euros, not Turkish lira."""
    assert P.resolve_currency("\u20ac", "TUR", "Turkey") == "EUR"
    # Ambiguous symbols defer to the host country.
    assert P.resolve_currency("R", "BRZ", "Brazil") == "BRL"
    assert P.resolve_currency("R", "SAF", "South Africa") == "ZAR"
    assert P.resolve_currency("Ps", "ARG", "Argentina") == "ARS"
    assert P.resolve_currency("Ps", "CHI", "Chile") == "CLP"
    assert P.resolve_currency("$", "USA", "United States") == "USD"
    # normalize.currency_for does not know IFHA's Korea code.
    assert P.resolve_currency("", "KOA", "Republic of Korea") == "KRW"


# --------------------------------------------------------------------------- #
# finisher count: 0, 3 or 4 -- never assume 3
# --------------------------------------------------------------------------- #


def test_dead_heat_produces_four_rows():
    records, issues = parsed("60442")
    assert len(records) == 4
    assert [r["finish_position"] for r in records] == [1, 2, 3, 3]
    assert all(r["n_finishers"] == 4 for r in records)
    assert "unexpected_finisher_count" in issue_types(issues)


def test_normal_race_produces_three_rows():
    records, issues = parsed("59931")
    assert len(records) == 3
    assert [r["finish_position"] for r in records] == [1, 2, 3]
    assert [r["finish_position_label"] for r in records] == ["First", "Second", "Third"]
    assert "unexpected_finisher_count" not in issue_types(issues)


# --------------------------------------------------------------------------- #
# header parsing oddities
# --------------------------------------------------------------------------- #


def test_race_name_containing_digits_is_not_read_as_the_purse():
    """GB names carry '(Class 1)', which looks like a purse line."""
    records, _ = parsed("59337")
    row = winner(records)
    assert "Class 1" in row["race_name"]
    assert row["purse_currency"] == "GBP"
    assert row["purse_local_amount"] == 60000.0
    assert row["purse_usd_site"] == 93600.0


def test_track_line_with_no_country_name():
    """Some pages read 'SIN Singapore -' with the country simply missing."""
    records, issues = parsed("58709")
    row = winner(records)
    assert row["track_code"] == "SIN"
    assert row["track_name"] == "Singapore"
    assert row["country_name"] == NA
    assert "missing_country_name" in issue_types(issues)


def test_track_regex():
    m = P.TRACK_RE.match("HAR Hipodromo Argentino De Palermo - Argentina")
    assert m.group("code") == "HAR"
    assert m.group("name") == "Hipodromo Argentino De Palermo"
    assert m.group("country") == "Argentina"

    m = P.TRACK_RE.match("AP Arlington Park - United States")  # code + 2 spaces
    assert m.group("code") == "AP"
    assert m.group("name") == "Arlington Park"

    m = P.TRACK_RE.match("SIN Singapore -")
    assert m.group("name") == "Singapore"
    assert m.group("country") == ""


def test_north_american_tracks_get_normalized_codes():
    records, _ = parsed("59742")
    row = winner(records)
    assert row["track_name"] == "Arlington Park"
    assert row["track_code_normalized"] == "AP"


# --------------------------------------------------------------------------- #
# schema and output contract
# --------------------------------------------------------------------------- #


def test_schema_is_exact_and_has_no_nulls():
    records, _ = parsed("59931")
    for row in records:
        assert list(row.keys()) == P.FIELDS
        assert None not in row.values(), row
        assert "_race_year" not in row and "_country_code" not in row


def test_missing_values_are_the_string_na():
    records, _ = parsed("59159")  # no results published
    row = records[0]
    for field in ("horse_name", "jockey", "horse_colour", "finish_position"):
        assert row[field] == "N/A"


def test_records_are_json_serializable():
    records, issues = parsed("59931")
    json.dumps(records)
    json.dumps(issues)


def test_issue_shape():
    _, issues = parsed("39002")
    for issue in issues:
        assert set(issue) == {"racepid", "issue", "detail"}
        assert isinstance(issue["racepid"], str)
        assert isinstance(issue["issue"], str)
        assert isinstance(issue["detail"], str)


def test_race_id_is_the_racepid():
    records, _ = parsed("59931")
    assert all(r["race_id"] == "59931" == r["racepid"] for r in records)
    assert all(r["source_url"].endswith("racepid=59931") for r in records)


# --------------------------------------------------------------------------- #
# parse_all
# --------------------------------------------------------------------------- #


def test_uncached_year_is_skipped_not_fatal():
    records, issues = P.parse_all([1999], progress=False)
    assert records == []
    assert [i["issue"] for i in issues] == ["year_not_cached"]


def test_mixed_cached_and_uncached_years():
    if not has_2015():
        pytest.skip("2015 is not cached")
    records, issues = P.parse_all([1999, 2015], limit=20, progress=False)
    assert records
    assert "year_not_cached" in issue_types(issues)
    assert "parse_exception" not in issue_types(issues)


def test_parse_all_2015_matches_the_known_race_count():
    if not has_2015():
        pytest.skip("2015 is not cached")
    records, issues = P.parse_all([2015], progress=False)
    summary = P.summarize(records, issues)

    assert summary["races_seen"] == 1611        # Agent 1's measured count
    assert summary["races_with_results"] == 1598
    assert summary["finisher_rows"] == 4796     # matches validate_cache.py
    assert summary["parse_failures"] == 0
    assert summary["issue_types"].get("descriptor_malformed", 0) == 0
    assert summary["issue_types"].get("descriptor_not_fixed_width", 0) == 0
    assert summary["issue_types"].get("colour_unmapped", 0) == 0
    assert summary["issue_types"].get("missing_race_name", 0) == 0
    assert summary["issue_types"].get("missing_date", 0) == 0
    assert summary["issue_types"].get("missing_group", 0) == 0
    assert summary["issue_types"].get("missing_jockey", 0) == 0
    assert summary["issue_types"].get("unknown_currency", 0) == 0


def test_american_pharoah_triple_crown():
    """A correctness check, not a well-formedness check."""
    if not has_2015():
        pytest.skip("2015 is not cached")
    records, _ = P.parse_all([2015], progress=False)

    wins = {
        r["race_name"]: r
        for r in records
        if r["horse_name"] == "American Pharoah" and r["finish_position"] == 1
    }
    names = " | ".join(wins)
    assert any("Kentucky Derby" in n for n in wins), names
    assert any("Preakness" in n for n in wins), names
    assert any("Belmont S" in n for n in wins), names
    assert any("Breeders' Cup Classic" in n for n in wins), names

    derby = next(r for n, r in wins.items() if "Kentucky Derby" in n)
    assert derby["date_iso"] == "2015-05-02"
    assert derby["track_code"] == "CD"
    assert derby["track_name"] == "Churchill Downs"
    assert derby["country_code"] == "USA"
    assert derby["group"] == "G1"
    assert derby["distance_furlongs"] == 10.0
    assert derby["surface"] == "D"
    assert derby["purse_local_amount"] == 2_000_000.0
    assert derby["jockey"] == "Espinoza, V."
    assert derby["horse_foaling_year"] == 2012
    assert derby["horse_age"] == 3

    # He was beaten in the Travers by Keen Ice.
    travers = [r for r in records if r["race_name"] == "Travers S."]
    assert {r["finish_position"]: r["horse_name"] for r in travers} == {
        1: "Keen Ice", 2: "American Pharoah", 3: "Frosted"
    }
