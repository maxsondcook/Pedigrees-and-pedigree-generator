"""Parser tests against trimmed Equibase HTML.

Run from the project root:  python3 -m pytest equibase_scraper/test_parse.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equibase_scraper.parse import is_blocked, page_is_clear, parse_profile, resolve_html
from equibase_scraper.queue import subject_from_line
from equibase_scraper.run import confirmed_clear, interruption_cleared

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _read(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def test_american_pharoah_profile():
    profile = parse_profile(_read("american_pharoah_profile.html"))
    assert profile["display_name"] == "American Pharoah"
    assert profile["foaled_in"] == "KY"
    assert profile["foal_year"] == "2012"
    assert profile["foaled"] == "2012-02-02"
    assert profile["breed"] == "TB"
    assert profile["equibase_refno"] == "9314281"
    assert profile["registry"] == "T"
    assert profile["sire"] == "Pioneerof the Nile"
    assert profile["sire_refno"] == "7766522"
    assert profile["dam"] == "Littleprincessemma"
    assert profile["dam_refno"] == "7719052"
    assert profile["damsire"] == "Yankee Gentleman"
    assert profile["damsire_refno"] == "4965983"
    assert profile["breeder"] == "Zayat Stables"
    assert "Baffert" in (profile["trainer"] or "")
    assert profile["best_class"] == "Multiple Graded Stakes Winner"

    assert len(profile["starts"]) == 11
    dates = [row["race_date"] for row in profile["starts"]]
    assert dates == sorted(dates)

    career = next(row for row in profile["year_stats"] if row["year"] == "Career")
    assert career["starts"] == 11
    assert career["firsts"] == 9
    assert career["seconds"] == 1
    assert career["thirds"] == 0
    assert career["earnings"] == 8650300
    assert career["highest_esf"] == 119

    first = profile["starts"][0]
    assert first["race_date"] == "2014-08-09"
    assert first["track"] == "Del Mar"
    assert first["race_name"] == "Maiden Special Weight"
    assert first["place"] == "5"
    assert first["esf"] == 70
    assert first["grade"] is None

    last = profile["starts"][-1]
    assert last["race_date"] == "2015-10-31"
    assert last["track"] == "Keeneland"
    assert last["race_name"].replace("\u2019", "'").startswith("Breeders' Cup Classic")
    assert last["grade"] == "1"
    assert last["place"] == "1"
    assert last["esf"] == 119
    assert last["stakes_id"] == "4198"
    assert last["track_code"] == "KEE"
    assert last["country"] == "USA"


def test_search_picks_matching_foal_year():
    american = resolve_html(_read("search_american_pharoah.html"), "2012")
    assert american["kind"] == "candidate"
    assert american["candidate"]["refno"] == "9314281"
    assert american["candidate"]["registry"] == "T"
    assert american["candidate"]["yob"] == "2012"

    storm = resolve_html(_read("search_storm_cat.html"), "1983")
    assert storm["kind"] == "candidate"
    assert storm["candidate"]["refno"] == "935962"
    assert storm["candidate"]["name"] == "Storm Cat"


def test_search_year_mismatch_and_ambiguous_and_blocked():
    mismatch = resolve_html(_read("search_storm_cat.html"), "1900")
    assert mismatch["kind"] == "year_mismatch"
    assert "1983" in mismatch["detail"]

    empty = """
    <h2>Click on a horse name to see the history of that horse.</h2>
    <table><thead><tr><th>Horse</th><th>YOB</th></tr></thead><tbody></tbody></table>
    """
    assert resolve_html(empty, "1983")["kind"] == "not_found"

    missing = "<h2>013 in NA/US could not be found. Please try again.</h2><form><input name='horse_name'></form>"
    assert resolve_html(missing, "")["kind"] == "not_found"

    ambiguous = """
    <h2>Click on a horse name to see the history of that horse.</h2>
    <table class="text-left fullwidth">
      <thead><tr><th>Horse</th><th>YOB</th><th>Sex</th><th>Sire</th><th>Dam</th></tr></thead>
      <tbody>
        <tr>
          <td><a href="/profiles/Results.cfm?type=Horse&refno=111&registry=T&rbt=TB">Storm Cat</a></td>
          <td>1983</td><td>Horse</td><td>Storm Bird</td><td>Terlingua</td>
        </tr>
        <tr>
          <td><a href="/profiles/Results.cfm?type=Horse&refno=222&registry=T&rbt=TB">Storm Cat</a></td>
          <td>1983</td><td>Horse</td><td>Storm Bird</td><td>Terlingua</td>
        </tr>
      </tbody>
    </table>
    """
    resolved = resolve_html(ambiguous, "1983")
    assert resolved["kind"] == "ambiguous"
    assert "111:T" in resolved["detail"]
    assert "222:T" in resolved["detail"]
    assert is_blocked("<html>Pardon Our Interruption</html>")
    assert resolve_html("Pardon Our Interruption", "2012")["kind"] == "blocked"
    assert is_blocked("<html>Access Denied Error 15</html>")
    assert not page_is_clear("")
    assert not page_is_clear("<html></html>")
    assert not page_is_clear("<html>Pardon Our Interruption</html>")
    assert not page_is_clear("<html>Pardon Our Interruption equibase</html>")
    assert page_is_clear("<html><a class='equibase-logo'>Equibase</a></html>")
    assert page_is_clear("<div id='horseProfileInfo'></div>")
    assert confirmed_clear(False, True) is False
    assert confirmed_clear(True, False) is False
    assert confirmed_clear(True, True) is True
    assert interruption_cleared(True, True, seen_block=False, require_seen_block=False)
    assert not interruption_cleared(True, True, seen_block=False, require_seen_block=True)
    assert interruption_cleared(True, True, seen_block=True, require_seen_block=True)
    assert not interruption_cleared(False, True, seen_block=True, require_seen_block=False)


def test_search_parent_filter_narrows_same_year_hits():
    html = """
    <h2>Click on a horse name to see the history of that horse.</h2>
    <table class="text-left fullwidth">
      <thead><tr><th>Horse</th><th>YOB</th><th>Sex</th><th>Sire</th><th>Dam</th></tr></thead>
      <tbody>
        <tr>
          <td><a href="/profiles/Results.cfm?type=Horse&refno=111&registry=T&rbt=TB">Storm Cat</a></td>
          <td>1983</td><td>Horse</td><td>Storm Bird</td><td>Terlingua</td>
        </tr>
        <tr>
          <td><a href="/profiles/Results.cfm?type=Horse&refno=222&registry=T&rbt=TB">Storm Cat</a></td>
          <td>1983</td><td>Horse</td><td>Storm Bird</td><td>Crimson Saint</td>
        </tr>
      </tbody>
    </table>
    """
    both = resolve_html(html, "1983")
    assert both["kind"] == "ambiguous"

    matched = resolve_html(html, "1983", sire="Storm Bird", dam="Terlingua")
    assert matched["kind"] == "candidate"
    assert matched["candidate"]["refno"] == "111"

    cleaned = resolve_html(html, "1983", sire="STORM BIRD", dam="terlingua")
    assert cleaned["kind"] == "candidate"
    assert cleaned["candidate"]["refno"] == "111"

    sire_only = resolve_html(html, "1983", sire="Storm Bird")
    assert sire_only["kind"] == "ambiguous"

    mismatch = resolve_html(html, "1983", sire="Storm Bird", dam="Not a Dam")
    assert mismatch["kind"] == "not_found"
    assert mismatch["detail"] == "parent mismatch"

    wrong_year = resolve_html(html, "1900", sire="Storm Bird", dam="Terlingua")
    assert wrong_year["kind"] == "year_mismatch"


def test_queue_subject_is_root_horse():
    kid = subject_from_line(
        "    'A P KID': {'Dam': {'Horse': 'EXCLUSIVE DANCER (1967)'}, "
        "'Horse': 'A. P. KID (2022)', 'Sire': {'Horse': 'HONOR A.P. (2017)'}},\n"
    )
    assert kid["pedigree_key"] == "A P KID"
    assert kid["foal_year"] == "2022"
    assert kid["name_key"] == "A P KID"
    assert kid["display_name"] == "A. P. KID"

    america = subject_from_line(
        "    'AMERICA (2011)': {'Horse': 'AMERICA', 'Sire': {'Horse': 'TRUMPATOR (1782)'}},\n"
    )
    assert america["foal_year"] == "2011"
    assert america["name_key"] == "AMERICA"
    assert america["display_name"] == "AMERICA"

    curly = subject_from_line(
        "    'CURLINS CATCH': {'Horse': 'CURLIN\u2019S CATCH (2018)'},\n"
    )
    assert curly["name_key"] == "CURLINS CATCH"
    assert curly["foal_year"] == "2018"
    assert curly["display_name"] == "CURLIN'S CATCH"
