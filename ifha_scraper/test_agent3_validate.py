"""Tests for agent3_validate. Synthetic records; no network.

A couple of tests optionally re-parse a cached 2015 page so the CSV mapping
stays honest against Agent 2's real schema. Those skip if the page is absent.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import agent3_validate as V

NA = V.NA

ORIGINAL_11 = [
    "Horse Name",
    "Last 2 digits of year Foaled",
    "Sex",
    "Place",
    "Country",
    "Track",
    "Date",
    "Distance",
    "Age",
    "Purse",
    "Group",
]


def rec(**kw):
    """One finisher row in Agent 2's schema, with Zenyatta/BC Classic defaults."""
    base = {
        "race_id": "50001",
        "racepid": "50001",
        "race_name": "Breeders' Cup Classic",
        "group": "G1",
        "group_label": "Group 1",
        "date": "07 November 2009",
        "date_iso": "2009-11-07",
        "race_year": 2009,
        "country_code": "USA",
        "country_name": "United States",
        "track_code": "SA",
        "track_name": "Santa Anita",
        "track_code_normalized": "SA",
        "distance_value": 10.0,
        "distance_unit": "Furlongs",
        "distance_metres": 2011.7,
        "distance_furlongs": 10.0,
        "distance_display": "10 Furlongs",
        "surface": "D",
        "surface_raw": "dirt",
        "purse_raw": "$5,000,000",
        "purse_local_amount": 5_000_000.0,
        "purse_currency_symbol": "$",
        "purse_currency": "USD",
        "purse_usd_site": 5_000_000.0,
        "purse_usd_normalized": 5_000_000.0,
        "purse_usd_display": "$5,000,000",
        "purse_usd_delta_pct": 0.0,
        "fx_rate": 1.0,
        "fx_rate_year": 2009,
        "fx_provenance": NA,
        "age_condition": "3U",
        "sex_condition": NA,
        "n_finishers": 3,
        "has_results": True,
        "source_url": "https://example.test/racepid=50001",
        "finish_position": 1,
        "finish_position_label": "First",
        "horse_name": "Zenyatta",
        "horse_country_suffix": NA,
        "horse_origin_country": "USA",
        "horse_origin_inferred": True,
        "horse_yob_2digit": "04",
        "horse_foaling_year": 2004,
        "horse_age": 5,
        "horse_colour_code": "DK B/",
        "horse_colour": "Dark Bay or Brown",
        "horse_sex_code": "M",
        "horse_sex": "M",
        "horse_descriptor_raw": "04 DK B/ M",
        "jockey": "Smith, M.",
    }
    base.update(kw)
    return base


def field(n, **kw):
    """Three finishers of one race, with optional shared overrides."""
    names = ("Zenyatta", "Gio Ponti", "Twice Over")
    rows = []
    for i in range(1, n + 1):
        overrides = {
            "finish_position": i,
            "horse_name": names[i - 1] if i - 1 < len(names) else f"Horse {i}",
            "horse_age": 5 + i - 1,
            "horse_foaling_year": 2004 - (i - 1),
            "horse_yob_2digit": f"{(2004 - (i - 1)) % 100:02d}",
        }
        overrides.update(kw)
        rows.append(rec(**overrides))
    return rows


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #


def test_race_name_is_first_and_race_id_is_last():
    assert V.COLUMNS[0] == "Race Name"
    assert V.COLUMNS[-1] == "race_id"


def test_original_11_columns_keep_their_relative_order():
    idx = {name: i for i, name in enumerate(V.COLUMNS)}
    for name in ORIGINAL_11:
        assert name in idx, name
    positions = [idx[name] for name in ORIGINAL_11]
    assert positions == sorted(positions)


def test_build_row_emits_exactly_the_declared_columns():
    row = V.build_row(rec(), "hybrid")
    assert list(row) == V.COLUMNS


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def test_missing_values_become_the_literal_na():
    assert V.text(None) == "N/A"
    assert V.text("") == "N/A"
    assert V.text("  ") == "N/A"
    assert V.money(None) == "N/A"
    assert V.foaled_two_digit({"horse_yob_2digit": None, "horse_foaling_year": None}) == "N/A"


def test_money_formats_and_keeps_zero():
    assert V.money(400_000) == "$400,000"
    assert V.money(0) == "$0"


def test_clean_text_is_applied_and_trailing_periods_survive():
    row = V.build_row(rec(race_name="Ack Ack S.", horse_name="Tumbarumba"), "hybrid")
    assert row["Race Name"] == "Ack Ack S."
    assert not row["Race Name"].endswith(" ")


def test_html_entities_and_nbsp_are_stripped():
    row = V.build_row(rec(race_name="Poule d&apos;Essai",
                          horse_name="Sea&nbsp;The Stars"), "hybrid")
    assert "&" not in row["Race Name"]
    assert "\xa0" not in row["Horse Name"]
    assert "Poule d'Essai" == row["Race Name"]
    assert row["Horse Name"] == "Sea The Stars"


# --------------------------------------------------------------------------- #
# presentation: age vs conditions, distance, date
# --------------------------------------------------------------------------- #


def test_age_is_the_horses_numeric_age_not_the_eligibility_string():
    row = V.build_row(rec(horse_age=5, age_condition="3U", sex_condition="fm"), "hybrid")
    assert row["Age"] == "5"
    assert row["Race Conditions"] == "3U fm"


def test_race_conditions_02_f_shape():
    row = V.build_row(rec(age_condition="02", sex_condition="f"), "hybrid")
    assert row["Race Conditions"] == "02 f"
    assert row["Age"] != "02 f"


def test_date_is_long_form_plus_iso():
    row = V.build_row(rec(), "hybrid")
    assert row["Date"] == "07 November 2009"
    assert row["Date (ISO)"] == "2009-11-07"


def test_distance_is_furlongs_with_surface_code():
    row = V.build_row(rec(distance_metres=1609.3, surface="D"), "hybrid")
    assert row["Distance"] == "8 Furlongs (D)"
    assert row["Distance (Metres)"] == "1,609"


def test_all_weather_is_aw_not_the_spreadsheet_e_code():
    row = V.build_row(rec(distance_metres=1307.6, surface="AW",
                          surface_raw="all weather"), "hybrid")
    assert row["Distance"].endswith("(AW)")
    assert "(E)" not in row["Distance"]


def test_extra_columns_are_populated():
    row = V.build_row(rec(), "hybrid")
    assert row["Jockey"] == "Smith, M."
    assert row["Colour"] == "Dark Bay or Brown"
    assert row["Foaling Year"] == "2004"
    assert row["Last 2 digits of year Foaled"] == "04"
    assert row["race_id"] == "50001"
    assert row["Purse (Local)"] == "5,000,000"
    assert row["Purse Currency"] == "USD"


# --------------------------------------------------------------------------- #
# purse policy
# --------------------------------------------------------------------------- #


def test_usd_purse_is_labelled_usd_native():
    usd, source = V.choose_purse(rec(), "hybrid")
    assert usd == 5_000_000.0
    assert source == "usd_native"


def test_hybrid_keeps_site_when_delta_is_small():
    record = rec(purse_currency="ZAR", purse_usd_site=14_295,
                 purse_usd_normalized=11_738, purse_usd_delta_pct=21.8,
                 fx_provenance="ecb")
    usd, source = V.choose_purse(record, "hybrid")
    assert usd == 14_295
    assert source == "site"


def test_hybrid_falls_back_to_normalized_when_site_is_stale_ecb():
    """The Brazil-2015 case: IFHA used the 2014 BRL rate."""
    record = rec(purse_currency="BRL", purse_usd_site=100_000,
                 purse_usd_normalized=70_000, purse_usd_delta_pct=42.9,
                 fx_provenance="ecb")
    usd, source = V.choose_purse(record, "hybrid")
    assert usd == 70_000
    assert source == "normalized_stale_site"
    row = V.build_row(record, "hybrid")
    assert row["Purse"] == "$70,000"
    assert row["Purse Source"] == "normalized_stale_site"


def test_hybrid_does_not_override_on_approximate_fx():
    record = rec(purse_currency="CLP", purse_usd_site=44_496,
                 purse_usd_normalized=20_000, purse_usd_delta_pct=122.5,
                 fx_provenance="approximate")
    usd, source = V.choose_purse(record, "hybrid")
    assert usd == 44_496
    assert source == "site"


def test_site_and_normalized_modes():
    record = rec(purse_currency="GBP", purse_usd_site=80_000,
                 purse_usd_normalized=90_000, purse_usd_delta_pct=-11.1,
                 fx_provenance="ecb")
    assert V.choose_purse(record, "site") == (80_000, "site")
    assert V.choose_purse(record, "normalized") == (90_000, "normalized")


def test_unknown_purse_source_raises():
    with pytest.raises(ValueError, match="unknown purse source"):
        V.choose_purse(rec(), "ecb")


# --------------------------------------------------------------------------- #
# dedup
# --------------------------------------------------------------------------- #


def test_dedup_keeps_the_numerically_lower_racepid():
    """'100' must not beat '99' just because it sorts first as a string."""
    findings = V.Findings()
    low = field(3, race_id="99", racepid="99")
    high = field(3, race_id="100", racepid="100")
    kept = V.deduplicate(low + high, findings)
    assert {r["race_id"] for r in kept} == {"99"}
    assert len(findings.collapses) == 1
    assert findings.collapses[0]["kept_race_id"] == "99"
    assert findings.collapses[0]["dropped_race_id"] == "100"
    assert findings.collapses[0]["identical_results"] is True


def test_dedup_keeps_both_when_finishers_differ():
    """Blue Diamond-style divisions share a key but are two real races."""
    findings = V.Findings()
    a = field(3, race_id="10", racepid="10")
    b = field(3, race_id="11", racepid="11")
    b[0]["horse_name"] = "Someone Else"
    kept = V.deduplicate(a + b, findings)
    assert {r["race_id"] for r in kept} == {"10", "11"}
    assert findings.counters["duplicate_key_distinct_races"] == 1
    assert findings.collapses == []


def test_dedup_empty_placeholder_does_not_beat_real_results():
    findings = V.Findings()
    empty = rec(race_id="1", racepid="1", has_results=False,
                finish_position=NA, horse_name=NA)
    full = field(3, race_id="99", racepid="99")
    kept = V.deduplicate([empty] + full, findings)
    assert {r["race_id"] for r in kept} == {"99"}
    assert findings.collapses[0]["dropped_race_id"] == "1"


def test_dedup_does_not_collapse_races_that_differ_on_the_key():
    findings = V.Findings()
    a = field(3, race_id="1", racepid="1", race_name="Queen Anne S.")
    b = field(3, race_id="2", racepid="2", race_name="Diamond Jubilee S.")
    kept = V.deduplicate(a + b, findings)
    assert len(kept) == 6
    assert findings.collapses == []


def test_punctuation_and_case_do_not_split_a_dedup_key():
    findings = V.Findings()
    a = field(3, race_id="5", racepid="5", race_name="Cox Plate")
    b = field(3, race_id="6", racepid="6", race_name="cox  plate.")
    kept = V.deduplicate(a + b, findings)
    assert {r["race_id"] for r in kept} == {"5"}


# --------------------------------------------------------------------------- #
# spot checks
# --------------------------------------------------------------------------- #


def test_spot_check_zenyatta_passes_and_2015_is_skipped():
    rows = [V.build_row(r, "hybrid") for r in field(3)]
    findings = V.Findings()
    results = V.run_spot_checks(rows, [2009], findings)
    by_year = {s["year"]: s for s in results if s["name"] == "breeders' cup classic"}
    assert by_year[2009]["status"] == "pass"
    assert by_year[2009]["found_winner"] == "Zenyatta"
    skipped_2015 = [s for s in results if s["year"] == 2015]
    # 2015 is not in SPOT_CHECKS at all -- Agent 2 already verified it.
    assert skipped_2015 == []
    skipped_other = [s for s in results if s["year"] == 2012]
    assert skipped_other and all(s["status"] == "skipped" for s in skipped_other)


def test_spot_check_prefers_belmont_stakes_over_belmont_sprint():
    stakes = rec(race_name="Belmont S.", horse_name="Summer Bird",
                 date="06 June 2009", date_iso="2009-06-06", finish_position=1)
    sprint = rec(race_id="50002", racepid="50002",
                 race_name="Belmont Sprint Championship",
                 horse_name="Someone Else",
                 date="06 June 2009", date_iso="2009-06-06", finish_position=1)
    rows = [V.build_row(stakes, "hybrid"), V.build_row(sprint, "hybrid")]
    findings = V.Findings()
    results = V.run_spot_checks(rows, [2009], findings)
    hit = next(s for s in results if s["name"] == "belmont s")
    assert hit["status"] == "pass"
    assert hit["found_winner"] == "Summer Bird"


def test_spot_check_date_filter_avoids_carnival_preview():
    preview = rec(race_name="Melbourne Cup Carnival Preview S.",
                  horse_name="Divine Madonna",
                  date="07 October 2006", date_iso="2006-10-07",
                  country_code="AUS")
    rows = [V.build_row(preview, "hybrid")]
    findings = V.Findings()
    results = V.run_spot_checks(rows, [2006], findings)
    hit = next(s for s in results if s["name"] == "melbourne cup")
    assert hit["status"] == "not_found"
    assert "2006-11-07" in hit["note"]


def test_spot_check_fails_on_the_wrong_winner():
    rows = [V.build_row(rec(horse_name="Blame"), "hybrid")]
    findings = V.Findings()
    results = V.run_spot_checks(rows, [2009], findings)
    hit = next(s for s in results
               if s["year"] == 2009 and s["name"] == "breeders' cup classic")
    assert hit["status"] == "fail"
    assert findings.counters["spot_check_failed"] == 1


# --------------------------------------------------------------------------- #
# validate() pipeline
# --------------------------------------------------------------------------- #


def test_validate_on_synthetic_records_writes_three_finishers():
    result = V.validate([2009], records=field(3), progress=False)
    assert result["summary"]["rows_written"] == 3
    assert result["summary"]["races_written"] == 1
    assert result["summary"]["duplicate_races_collapsed"] == 0
    assert result["rows"][0]["Place"] == "1"
    assert [r["Place"] for r in result["rows"]] == ["1", "2", "3"]


def test_validate_drops_uncached_detail_placeholders():
    records = field(3) + [rec(race_id="9", racepid="9", has_results=False,
                              finish_position=NA, horse_name=NA)]
    issues = [{"racepid": "9", "issue": "detail_not_cached", "detail": "url"}]
    result = V.validate([2009], records=records, parse_issues=issues, progress=False)
    assert result["summary"]["omitted_uncached_detail_rows"] == 1
    assert result["summary"]["rows_written"] == 3
    assert all(r["race_id"] != "9" for r in result["rows"])


def test_validate_flags_uncached_years_as_info_not_error():
    result = V.validate(
        [2009, 2016],
        records=field(3),
        parse_issues=[{"racepid": "year:2016", "issue": "year_not_cached",
                       "detail": "2016"}],
        progress=False,
    )
    missing = [i for i in result["findings"].issues if i["check"] == "year_missing"]
    assert missing and missing[0]["year"] == 2016
    assert missing[0]["severity"] == "info"
    anomaly = next(a for a in result["summary"]["coverage"]["anomalies"]
                   if a["year"] == 2016)
    assert anomaly["expected"] is True


def test_dead_heat_is_kept_and_flagged_info():
    rows = field(3)
    rows.append(rec(finish_position=3, horse_name="Also Third",
                    horse_yob_2digit="05", horse_foaling_year=2005, horse_age=4))
    result = V.validate([2009], records=rows, progress=False)
    assert result["summary"]["row_checks"]["races_with_dead_heat"] == 1
    assert result["summary"]["rows_written"] == 4
    assert any(i["check"] == "dead_heat" and i["severity"] == "info"
               for i in result["findings"].issues)


def test_sort_is_chronological_then_place():
    later = field(3, date="05 November 2022", date_iso="2022-11-05",
                  race_year=2022, race_id="9", racepid="9",
                  race_name="Breeders' Cup Classic Powered by Dodge",
                  horse_name="Flightline")
    result = V.validate([2009, 2022], records=field(3) + later, progress=False)
    dates = [r["Date (ISO)"] for r in result["rows"]]
    assert dates == sorted(dates)
    first_race = [r for r in result["rows"] if r["Date (ISO)"] == "2009-11-07"]
    assert [r["Place"] for r in first_race] == ["1", "2", "3"]


def test_sparse_years_are_classified_as_expected():
    few = field(3, date="01 January 2003", date_iso="2003-01-01", race_year=2003,
                race_id="1", racepid="1")
    many = []
    for year in (2004, 2005, 2006):
        for n in range(8):
            many.extend(field(3, date=f"01 June {year}", date_iso=f"{year}-06-01",
                              race_year=year, race_id=f"{year}{n}", racepid=f"{year}{n}",
                              race_name=f"Some S. {year} {n}"))
    result = V.validate([2003, 2004, 2005, 2006], records=few + many, progress=False)
    by_year = {a["year"]: a for a in result["summary"]["coverage"]["anomalies"]}
    assert 2003 in by_year
    assert by_year[2003]["expected"] is True


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #


def test_write_csv_is_utf8_sig_with_na_and_accents(tmp_path):
    path = tmp_path / "out.csv"
    row = V.build_row(rec(horse_name="José", jockey=None,
                          horse_country_suffix=None), "hybrid")
    V.write_csv([row], path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        got = list(csv.DictReader(fh))
    assert list(got[0]) == V.COLUMNS
    assert got[0]["Horse Name"] == "José"
    assert got[0]["Jockey"] == "N/A"
    assert got[0]["Horse Country Suffix"] == "N/A"
    assert "N/A" in path.read_text(encoding="utf-8-sig")


def test_render_report_labels_provisional():
    result = V.validate([2009], records=field(3), progress=False)
    text = V.render_report(result["summary"], result["findings"], True,
                           [Path("out.csv")], cache_files=15152)
    assert "PROVISIONAL" in text
    assert "FINAL" not in text.split("generated")[0]
    assert "hybrid" in text


def test_main_dry_run_writes_nothing(tmp_path, monkeypatch):
    real = V.validate

    def fake(years, **kwargs):
        return real([2009], records=field(3),
                    purse_source=kwargs.get("purse_source", "hybrid"),
                    progress=False)

    monkeypatch.setattr(V, "validate", fake)
    out = tmp_path / "a.csv"
    rc = V.main(["--years", "2009", "--dry-run", "--quiet",
                 "--out", str(out), "--repo-out", str(tmp_path / "b.csv")])
    assert rc == 0
    assert not out.exists()


def test_main_writes_all_artifacts(tmp_path, monkeypatch):
    real = V.validate

    def fake(years, **kwargs):
        return real([2009], records=field(3),
                    purse_source=kwargs.get("purse_source", "hybrid"),
                    progress=False)

    monkeypatch.setattr(V, "validate", fake)
    out = tmp_path / "deliverable.csv"
    repo = tmp_path / "repo.csv"
    report = tmp_path / "VALIDATION_REPORT.md"
    issues = tmp_path / "validation_issues.csv"
    summary = tmp_path / "validation_summary.json"
    rc = V.main([
        "--years", "2009", "--quiet", "--provisional",
        "--out", str(out), "--repo-out", str(repo),
        "--report-out", str(report), "--issues-out", str(issues),
        "--summary-out", str(summary),
        "--purse-source", "hybrid",
    ])
    assert rc == 0
    assert out.exists() and repo.exists()
    assert out.read_bytes()[:3] == b"\xef\xbb\xbf"
    assert "PROVISIONAL" in report.read_text(encoding="utf-8")
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["rows_written"] == 3
    assert payload["provisional"] is True


def test_cli_purse_source_normalized(tmp_path, monkeypatch):
    seen = {}
    real = V.validate

    def fake(years, **kwargs):
        seen["mode"] = kwargs.get("purse_source")
        record = rec(purse_currency="BRL", purse_usd_site=100_000,
                     purse_usd_normalized=70_000, purse_usd_delta_pct=42.9,
                     fx_provenance="ecb")
        return real([2009], records=[record],
                    purse_source=kwargs.get("purse_source", "hybrid"),
                    progress=False)

    monkeypatch.setattr(V, "validate", fake)
    out = tmp_path / "out.csv"
    rc = V.main(["--years", "2009", "--quiet", "--purse-source", "normalized",
                 "--out", str(out), "--repo-out", str(tmp_path / "b.csv"),
                 "--report-out", str(tmp_path / "r.md"),
                 "--issues-out", str(tmp_path / "i.csv"),
                 "--summary-out", str(tmp_path / "s.json")])
    assert rc == 0
    assert seen["mode"] == "normalized"
    with out.open(encoding="utf-8-sig") as fh:
        row = next(csv.DictReader(fh))
    assert row["Purse Source"] == "normalized"
    assert row["Purse"] == "$70,000"


# --------------------------------------------------------------------------- #
# optional: real 2015 page, skipped if uncached
# --------------------------------------------------------------------------- #


def test_build_row_against_a_real_2015_parse():
    import agent2_parse as P
    records, _ = P.parse_one("59931")
    if not records:
        pytest.skip("racepid 59931 is not cached yet")
    row = V.build_row(records[0], "hybrid")
    assert row["Horse Name"] == "Liberal"
    assert row["Last 2 digits of year Foaled"] == "11"
    assert row["Age"].isdigit()
    assert row["Race Conditions"] != row["Age"]
    assert row["race_id"] == "59931"
    assert "(E)" not in row["Distance"]
    assert list(row) == V.COLUMNS
