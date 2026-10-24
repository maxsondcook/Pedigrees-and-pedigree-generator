"""Tests for ifha_scraper.normalize.

Run from the project root:  python3 -m pytest ifha_scraper/test_normalize.py -q
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ifha_scraper import normalize as nz  # noqa: E402


# ---------------------------------------------------------------------------
# clean_text
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Ack&nbsp;Ack S.", "Ack Ack S."),          # race-name period survives
    ("Bed o&#39; Roses S.", "Bed o' Roses S."),
    ("Smith &amp; Jones", "Smith & Jones"),
    ("&amp;nbsp;Churchill", "Churchill"),        # double-escaped entity
    ("  Belmont\u00a0\u00a0Park \u200b", "Belmont Park"),
    ("Pre\u2013Akhal \u2014 Cup", "Pre-Akhal - Cup"),
    ("Enable\u2019s Race", "Enable's Race"),
    ('"Alabama S.",', "Alabama S."),
    ("Travers S. -", "Travers S."),
    ("\u201cQuoted\u201d", "Quoted"),
    ("", "N/A"),
    ("   ", "N/A"),
    (None, "N/A"),
    ("n/a", "N/A"),
    ("--", "N/A"),
    (1234, "1234"),
])
def test_clean_text(raw, expected):
    assert nz.clean_text(raw) == expected


def test_clean_text_never_raises_on_odd_types():
    for value in ([], {}, object(), 3.5, True):
        assert isinstance(nz.clean_text(value), str)


# ---------------------------------------------------------------------------
# metres_to_furlongs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metres, display", [
    (1609, "8 Furlongs"),     # exactly a mile
    (1600, "8 Furlongs"),     # metric mile snaps to 8f
    (1200, "6 Furlongs"),
    (1300, "6.5 Furlongs"),
    (1000, "5 Furlongs"),
    (1100, "5.5 Furlongs"),
    (1400, "7 Furlongs"),
    (1500, "7.5 Furlongs"),
    (1700, "8.5 Furlongs"),
    (1800, "9 Furlongs"),
    (1900, "9.5 Furlongs"),
    (2000, "10 Furlongs"),
    (2100, "10.5 Furlongs"),
    (2200, "11 Furlongs"),
    (2400, "12 Furlongs"),
    (2800, "14 Furlongs"),
    (3200, "16 Furlongs"),
    (4000, "20 Furlongs"),
    (201.168, "1 Furlong"),   # singular
])
def test_metres_to_furlongs_snaps_to_conventional(metres, display):
    assert nz.metres_to_furlongs(metres).display == display


def test_metres_to_furlongs_keeps_raw_values():
    result = nz.metres_to_furlongs(1600)
    assert result.metres == 1600.0
    assert result.furlongs == 8.0
    assert result.raw_furlongs == pytest.approx(7.9535, abs=1e-3)
    assert str(result) == "8 Furlongs"
    # NamedTuple so the caller can also unpack positionally.
    display, furlongs, raw, metres = result
    assert (display, furlongs, metres) == ("8 Furlongs", 8.0, 1600.0)


def test_metres_to_furlongs_odd_distance_uses_quarter_furlong():
    # 1670m is not near any conventional trip, so it must not be forced to 8.5f.
    result = nz.metres_to_furlongs(1670)
    assert result.display == "8.25 Furlongs"
    assert result.furlongs == 8.25


@pytest.mark.parametrize("bad", [None, "", "N/A", 0, -500, "abc", True, float("inf")])
def test_metres_to_furlongs_bad_input(bad):
    result = nz.metres_to_furlongs(bad)
    assert result.display == "N/A"
    assert result.furlongs is None
    assert result.metres is None


def test_metres_to_furlongs_parses_text():
    assert nz.metres_to_furlongs("2,400 m").display == "12 Furlongs"
    assert nz.metres_to_furlongs("1600 metres").display == "8 Furlongs"


# ---------------------------------------------------------------------------
# surface_code / distance_with_surface
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Dirt", "D"),
    ("DIRT", "D"),
    ("Main Track", "D"),
    ("Sand", "D"),
    ("D", "D"),
    ("Turf", "T"),
    ("turf (inner)", "T"),
    ("Grass", "T"),
    ("T", "T"),
    ("All Weather", "AW"),
    ("All-Weather Track", "AW"),
    ("Polytrack", "AW"),
    ("Tapeta", "AW"),
    ("Fibresand", "AW"),
    ("Synthetic", "AW"),
    ("Cushion Track", "AW"),
    ("AW", "AW"),
    ("", "N/A"),
    (None, "N/A"),
    ("unknown surface", "N/A"),
])
def test_surface_code(raw, expected):
    assert nz.surface_code(raw) == expected


def test_surface_code_prefers_synthetic_over_turf_or_dirt():
    # "Tapeta" and "all-weather dirt mix" must not be read as T or D.
    assert nz.surface_code("Tapeta Footings") == "AW"
    assert nz.surface_code("All Weather (dirt mix)") == "AW"


@pytest.mark.parametrize("metres, surface, expected", [
    (1609, "Dirt", "8 Furlongs (D)"),
    (1300, "Turf", "6.5 Furlongs (T)"),
    (1600, "Polytrack", "8 Furlongs (AW)"),
    (1609, None, "8 Furlongs"),       # no surface -> omit the bracket
    (None, "Dirt", "N/A"),
])
def test_distance_with_surface(metres, surface, expected):
    assert nz.distance_with_surface(metres, surface) == expected


def test_distance_with_surface_can_emit_the_sheets_e_code():
    # The reference sheet's only synthetic row is "6.5 Furlongs (E)".
    assert nz.SPREADSHEET_AW_CODE == "E"
    assert nz.distance_with_surface(
        1300, "Tapeta", aw_code=nz.SPREADSHEET_AW_CODE
    ) == "6.5 Furlongs (E)"
    # Dirt and turf are unaffected by aw_code.
    assert nz.distance_with_surface(1609, "Dirt", aw_code="E") == "8 Furlongs (D)"


def test_surface_code_reads_back_the_sheets_e_code():
    assert nz.surface_code("E") == "AW"


# ---------------------------------------------------------------------------
# currency_for
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("GB", "GBP"), ("Great Britain", "GBP"), ("UK", "GBP"), ("(GB)", "GBP"),
    ("IRE", "EUR"), ("FR", "EUR"), ("GER", "EUR"), ("ITY", "EUR"),
    ("JPN", "JPY"), ("AUS", "AUD"), ("NZ", "NZD"), ("HK", "HKD"),
    ("SIN", "SGD"), ("UAE", "AED"), ("CAN", "CAD"), ("SAF", "ZAR"),
    ("KOR", "KRW"), ("ARG", "ARS"), ("BRZ", "BRL"), ("CHI", "CLP"),
    ("PER", "PEN"), ("URU", "UYU"), ("TUR", "TRY"), ("IND", "INR"),
    ("SAU", "SAR"), ("QA", "QAR"), ("BHR", "BHD"), ("SWE", "SEK"),
    ("NOR", "NOK"), ("DEN", "DKK"), ("SWI", "CHF"), ("CZE", "CZK"),
    ("POL", "PLN"), ("HUN", "HUF"), ("RUS", "RUB"), ("MAC", "MOP"),
    ("MAL", "MYR"), ("PAN", "PAB"), ("MEX", "MXN"), ("PR", "USD"),
    ("USA", "USD"),
    ("GBP", "GBP"),                  # ISO code passthrough
    ("usa", "USD"),                  # case-insensitive
    ("USA - Kentucky", "USD"),       # region suffix dropped
    ("Hong Kong", "HKD"),
    ("South Africa", "ZAR"),
    ("United Arab Emirates", "AED"),
    (None, None), ("", None), ("Atlantis", None),
])
def test_currency_for(raw, expected):
    assert nz.currency_for(raw) == expected


# ---------------------------------------------------------------------------
# FX rates
# ---------------------------------------------------------------------------

def test_fx_cache_file_exists_and_covers_the_period():
    assert os.path.exists(nz.FX_CACHE_PATH)
    years = nz.available_fx_years()
    assert min(years) <= 2003 and max(years) >= 2026


def test_real_rates_are_historically_plausible():
    # Sanity-check the fetched ECB series against known annual averages.
    gbp_2003, _ = nz.fx_rate("GBP", 2003)
    jpy_2020, _ = nz.fx_rate("JPY", 2020)
    eur_2010, _ = nz.fx_rate("EUR", 2010)
    assert gbp_2003 == pytest.approx(0.61, abs=0.03)
    assert jpy_2020 == pytest.approx(106.8, abs=3.0)
    assert eur_2010 == pytest.approx(0.755, abs=0.02)
    assert nz.rate_provenance("GBP", 2003) == "ecb"


def test_pegged_currencies_are_flat_and_exact():
    for year in (2003, 2015, 2026):
        assert nz.fx_rate("AED", year)[0] == pytest.approx(3.6725)
        assert nz.fx_rate("SAR", year)[0] == pytest.approx(3.75)
        assert nz.fx_rate("QAR", year)[0] == pytest.approx(3.64)
        assert nz.fx_rate("BHD", year)[0] == pytest.approx(0.376)
        assert nz.rate_provenance("AED", year) == "peg"


def test_mop_tracks_the_real_hkd_rate():
    hkd, _ = nz.fx_rate("HKD", 2019)
    mop, _ = nz.fx_rate("MOP", 2019)
    assert mop == pytest.approx(hkd * 1.03)


def test_approximate_currencies_are_flagged_as_such():
    for code in ("ARS", "CLP", "PEN", "UYU", "RUB"):
        assert nz.rate_provenance(code, 2015) == "approximate"
        assert code in nz.APPROXIMATE_CURRENCIES


def test_every_year_has_a_rate_for_every_racing_currency():
    skip = nz.UNSUPPORTED_CURRENCIES
    currencies = {c for c in nz.JURISDICTION_CURRENCY.values() if c not in skip}
    for year in range(2003, 2027):
        for code in currencies:
            rate, used = nz.fx_rate(code, year)
            assert rate and rate > 0, f"missing {code} {year}"
            assert used is not None


def test_out_of_range_year_falls_back_to_nearest_available():
    rate_2099, used = nz.fx_rate("GBP", 2099)
    assert used == max(nz.available_fx_years())
    assert rate_2099 > 0
    assert nz.fx_rate("GBP", 1900)[1] == min(nz.available_fx_years())


def test_isk_gap_years_fall_back_without_failing():
    # ECB suspended ISK 2009-2017; approximations cover it.
    rate, used = nz.fx_rate("ISK", 2012)
    assert rate == pytest.approx(125.1)
    assert used == 2012
    assert nz.rate_provenance("ISK", 2012) == "approximate"


def test_fallback_table_agrees_with_the_real_ecb_series():
    """Cross-validate the hand-entered fallback numbers against fetched data.

    Guards against a typo in FALLBACK_RATES silently producing a wrong purse on
    the day fx_rates.json goes missing.
    """
    worst = (0.0, None)
    for code, series in nz.FALLBACK_RATES.items():
        for year, guess in series.items():
            real = nz._LIVE_RATES.get(year, {}).get(code)
            if real is None:
                continue
            error = abs(guess - real) / real
            if error > worst[0]:
                worst = (error, f"{code} {year}: table={guess} real={real:.4f}")
            assert error < 0.01, f"{code} {year}: table={guess} vs real={real:.4f}"
    assert worst[1] is not None, "no overlap to validate against"


def test_unsupported_currency_returns_none():
    assert nz.fx_rate("VEN", 2020) == (None, None)
    assert nz.rate_provenance("VEN", 2020) is None


@pytest.mark.parametrize("bad_year", [
    None, "", "abc", float("inf"), float("nan"), -float("inf"), True, [], object(),
])
def test_fx_lookup_survives_a_junk_year_with_a_valid_currency(bad_year):
    # Guards the int() coercion, which raises OverflowError (not ValueError) on inf.
    assert nz.fx_rate("GBP", bad_year) == (None, None)
    assert nz.rate_provenance("GBP", bad_year) is None
    assert nz.purse_to_usd(1_000_000, "GB", bad_year) == (None, "N/A")


# ---------------------------------------------------------------------------
# parse_amount / purse conversion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    (400000, 400000.0),
    ("400000", 400000.0),
    ("$400,000", 400000.0),
    ("400,000", 400000.0),
    ("1,500,000", 1500000.0),
    ("1.000.000", 1000000.0),        # European grouping
    ("1,234,567.89", 1234567.89),
    ("1.234.567,89", 1234567.89),    # European decimal
    ("AED 10,000,000", 10000000.0),
    ("\u00a5100,000,000", 100000000.0),
    ("0", 0.0),
    ("$0", 0.0),
    (None, None), ("", None), ("N/A", None), ("no purse", None),
])
def test_parse_amount(raw, expected):
    assert nz.parse_amount(raw) == expected


def test_purse_to_usd_usa_is_identity():
    usd, display = nz.purse_to_usd(400000, "USA", 2025)
    assert usd == 400000.0
    assert display == "$400,000"


def test_purse_to_usd_returns_two_tuple_as_documented():
    result = nz.purse_to_usd("£500,000", "GB", 2024)
    assert isinstance(result, tuple) and len(result) == 2
    usd, display = result
    assert 550_000 < usd < 750_000      # GBP ~0.78/USD in 2024
    assert display.startswith("$") and "," in display


def test_purse_to_usd_japan_rounds_and_formats():
    usd, display = nz.purse_to_usd(100_000_000, "JPN", 2020)
    assert usd == pytest.approx(936_000, rel=0.05)   # ~106.75 JPY/USD
    assert display == f"${round(usd):,}"
    assert "." not in display                        # whole dollars only


def test_purse_detail_preserves_raw_columns():
    detail = nz.purse_detail("AED 12,000,000", "UAE", 2023)
    assert detail.amount == 12_000_000.0
    assert detail.currency == "AED"
    assert detail.rate == pytest.approx(3.6725)
    assert detail.rate_year == 2023
    assert detail.provenance == "peg"
    assert detail.usd == pytest.approx(12_000_000 / 3.6725)
    assert detail.display == "$3,267,529"
    assert str(detail) == detail.display


def test_purse_detail_2026_notes_the_rate_year_used():
    detail = nz.purse_detail(1_000_000, "GB", 2026)
    assert detail.rate_year is not None
    assert detail.rate_year <= 2026
    assert detail.usd > 0


def test_purse_zero_formats_as_dollar_zero():
    # The reference spreadsheet contains "$0" rows.
    assert nz.purse_to_usd(0, "USA", 2025) == (0.0, "$0")


@pytest.mark.parametrize("amount, country, year", [
    (None, "GB", 2020),
    ("", "GB", 2020),
    ("400000", None, 2020),
    ("400000", "Atlantis", 2020),
    ("not a number", "GB", 2020),
])
def test_purse_to_usd_bad_input(amount, country, year):
    usd, display = nz.purse_to_usd(amount, country, year)
    assert usd is None and display == "N/A"


def test_purse_to_usd_missing_year_still_converts():
    usd, display = nz.purse_to_usd(1_000_000, "GB", None)
    assert usd is None and display == "N/A"


# ---------------------------------------------------------------------------
# parse_horse_descriptor
# ---------------------------------------------------------------------------

def test_parse_descriptor_basic():
    assert nz.parse_horse_descriptor("5 B H") == {
        "name": None, "country_suffix": None, "age": 5,
        "colour": "Bay", "sex": "H",
    }


def test_parse_descriptor_chestnut_filly():
    result = nz.parse_horse_descriptor("3 Ch F")
    assert (result["age"], result["colour"], result["sex"]) == (3, "Chestnut", "F")


def test_parse_descriptor_compound_colour():
    result = nz.parse_horse_descriptor("4 B/Br G")
    assert (result["age"], result["colour"], result["sex"]) == (4, "Bay or Brown", "G")


def test_parse_descriptor_spaced_compound_colour():
    result = nz.parse_horse_descriptor("4 B / Br G")
    assert result["colour"] == "Bay or Brown"


def test_parse_descriptor_two_token_colour():
    result = nz.parse_horse_descriptor("6 Dk B H")
    assert (result["age"], result["colour"], result["sex"]) == (6, "Dark Bay", "H")
    assert nz.parse_horse_descriptor("6 Dk B/Br R")["colour"] == "Dark Bay or Brown"


def test_parse_descriptor_with_name_and_country():
    assert nz.parse_horse_descriptor("Enable (GB) 5 B M") == {
        "name": "Enable", "country_suffix": "GB", "age": 5,
        "colour": "Bay", "sex": "M",
    }


def test_parse_descriptor_name_only_with_country():
    result = nz.parse_horse_descriptor("Enable (GB)")
    assert result["name"] == "Enable"
    assert result["country_suffix"] == "GB"
    assert result["age"] is None and result["sex"] is None and result["colour"] is None


def test_parse_descriptor_all_caps_and_nbsp():
    result = nz.parse_horse_descriptor("THORPEDO\u00a0ANNA (USA)\u00a04\u00a0B\u00a0M")
    assert result["name"] == "THORPEDO ANNA"
    assert result["country_suffix"] == "USA"
    assert (result["age"], result["colour"], result["sex"]) == (4, "Bay", "M")


def test_parse_descriptor_multiword_name_is_not_eaten():
    result = nz.parse_horse_descriptor("Bay Street Band 4 B M")
    assert result["name"] == "Bay Street Band"
    assert (result["age"], result["colour"], result["sex"]) == (4, "Bay", "M")


def test_parse_descriptor_colour_word_in_name_without_descriptor():
    # No age/sex present, so a trailing colour word must stay part of the name.
    result = nz.parse_horse_descriptor("Winter Grey")
    assert result["name"] == "Winter Grey"
    assert result["colour"] is None


def test_parse_descriptor_colour_word_name_with_descriptor():
    result = nz.parse_horse_descriptor("Grey Swallow (IRE) 4 Gr C")
    assert result["name"] == "Grey Swallow"
    assert result["country_suffix"] == "IRE"
    assert (result["age"], result["colour"], result["sex"]) == (4, "Grey", "C")


def test_parse_descriptor_varied_token_order():
    for text in ("5 B H", "B 5 H", "5 H B"):
        result = nz.parse_horse_descriptor(text)
        assert (result["age"], result["colour"], result["sex"]) == (5, "Bay", "H")


def test_parse_descriptor_missing_tokens():
    assert nz.parse_horse_descriptor("4 G")["colour"] is None
    assert nz.parse_horse_descriptor("4 G")["sex"] == "G"
    assert nz.parse_horse_descriptor("B H")["age"] is None
    assert nz.parse_horse_descriptor("7")["age"] == 7


def test_parse_descriptor_full_words():
    result = nz.parse_horse_descriptor("3 Chestnut Filly")
    assert (result["age"], result["colour"], result["sex"]) == (3, "Chestnut", "F")
    assert nz.parse_horse_descriptor("5 Bay Gelding")["sex"] == "G"


def test_parse_descriptor_age_with_yo_suffix():
    assert nz.parse_horse_descriptor("4yo B C")["age"] == 4


@pytest.mark.parametrize("bad", [None, "", "   ", "N/A", 12345, "???"])
def test_parse_descriptor_never_raises(bad):
    result = nz.parse_horse_descriptor(bad)
    assert set(result) == {"name", "country_suffix", "age", "colour", "sex"}


def test_parse_descriptor_all_sex_codes():
    expected = {"H": "H", "M": "M", "G": "G", "C": "C", "F": "F", "R": "R"}
    for letter, code in expected.items():
        assert nz.parse_horse_descriptor(f"4 B {letter}")["sex"] == code


def test_sex_code_and_colour_name_helpers():
    assert nz.sex_code("mare") == "M"
    assert nz.sex_code("RIDGLING") == "R"
    assert nz.sex_code("zebra") is None
    assert nz.colour_name("blk") == "Black"
    assert nz.colour_name("Ro") == "Roan"
    assert nz.colour_name(None) is None


# ---------------------------------------------------------------------------
# foaling_year
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("race_year, age, year, short", [
    (2025, 5, 2020, "20"),
    (2010, 5, 2005, "05"),       # leading zero preserved
    (2003, 3, 2000, "00"),
    (2025, 3, 2022, "22"),
    ("2025", "4", 2021, "21"),   # string inputs
])
def test_foaling_year(race_year, age, year, short):
    result = nz.foaling_year(race_year, age)
    assert result.year == year
    assert result.short == short


@pytest.mark.parametrize("race_year, age", [
    (None, 5), (2025, None), ("abc", 5), (2025, "abc"),
    (2025, -1), (2025, 99), (99, 5), (True, 5), (2025, True),
    (2025, float("inf")), (float("inf"), 5), (2025, float("nan")),
])
def test_foaling_year_bad_input(race_year, age):
    assert nz.foaling_year(race_year, age) == (None, None)


# ---------------------------------------------------------------------------
# normalize_date
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, iso, display", [
    ("2015-12-05", "2015-12-05", "05 December 2015"),
    ("2015/12/05", "2015-12-05", "05 December 2015"),
    ("20151205", "2015-12-05", "05 December 2015"),
    ("5 Dec 2015", "2015-12-05", "05 December 2015"),
    ("5 December 2015", "2015-12-05", "05 December 2015"),
    ("December 5, 2015", "2015-12-05", "05 December 2015"),
    ("Dec 5 2015", "2015-12-05", "05 December 2015"),
    ("27 September 2025", "2025-09-27", "27 September 2025"),
    ("27th September 2025", "2025-09-27", "27 September 2025"),
    ("Saturday, 27 Sept 2025", "2025-09-27", "27 September 2025"),
    ("03 August 2025", "2025-08-03", "03 August 2025"),
    ("3 Aug 2025 14:30", "2025-08-03", "03 August 2025"),
    ("29/02/2016", "2016-02-29", "29 February 2016"),
])
def test_normalize_date_formats(raw, iso, display):
    result = nz.normalize_date(raw)
    assert result is not None
    assert result.iso == iso
    assert result.display == display
    assert str(result) == iso


def test_normalize_date_ambiguous_numeric_is_day_first_by_default():
    # IFHA is an international source, so 12/05/2015 is 12 May.
    assert nz.normalize_date("12/05/2015").iso == "2015-05-12"
    assert nz.normalize_date("12/05/2015", dayfirst=False).iso == "2015-12-05"


def test_normalize_date_unambiguous_numeric_ignores_dayfirst():
    # Day 27 cannot be a month, so both readings agree.
    assert nz.normalize_date("27/09/2025").iso == "2025-09-27"
    assert nz.normalize_date("27/09/2025", dayfirst=False).iso == "2025-09-27"


def test_normalize_date_two_digit_year():
    assert nz.normalize_date("05/12/15").iso == "2015-12-05"


def test_normalize_date_display_day_is_zero_padded():
    # Matches the reference CSV ("03 August 2025").
    assert nz.normalize_date("2025-08-03").display == "03 August 2025"


@pytest.mark.parametrize("bad", [
    None, "", "   ", "N/A", "not a date", "2015-13-05", "2015-02-30",
    "29/02/2015", "September 2025", "27 September", "99/99/9999",
])
def test_normalize_date_bad_input(bad):
    assert nz.normalize_date(bad) is None


def test_normalize_date_handles_entities_and_nbsp():
    assert nz.normalize_date("27\u00a0September\u00a02025").iso == "2025-09-27"


# ---------------------------------------------------------------------------
# tracks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, code", [
    ("Churchill Downs", "CD"),
    ("Churchill Downs Racetrack", "CD"),
    ("Saratoga", "SAR"),
    ("Saratoga Race Course", "SAR"),
    ("Kentucky Downs", "KD"),
    ("Santa Anita Park", "SA"),
    ("Santa Anita", "SA"),
    ("Keeneland", "KEE"),
    ("Oaklawn Park", "OP"),
    ("Colonial Downs", "CNL"),
    ("Laurel Park", "LRL"),
    ("Del Mar", "DMR"),
    ("Belmont at the Big A", "BAQ"),
    ("Gulfstream Park", "GP"),
    ("Woodbine", "WO"),
    ("Aqueduct", "AQU"),
])
def test_track_code_known_north_american(raw, code):
    assert nz.track_code(raw) == code
    assert nz.track_info(raw).is_known is True


@pytest.mark.parametrize("raw", [
    "Longchamp", "Ascot", "Tokyo", "Sha Tin", "Flemington",
    "Meydan", "Curragh", "Leopardstown",
])
def test_track_code_international_passes_through_unchanged(raw):
    # No invented codes for international tracks.
    assert nz.track_code(raw) == raw
    assert nz.track_name(raw) == raw
    assert nz.track_info(raw).is_known is False


def test_track_name_is_cleaned_but_preserved():
    assert nz.track_name("Churchill&nbsp;Downs") == "Churchill Downs"
    assert nz.track_code("Churchill&nbsp;Downs") == "CD"


def test_track_code_accepts_an_existing_code():
    assert nz.track_code("CD") == "CD"
    assert nz.track_code("SAR") == "SAR"


def test_track_bad_input():
    for bad in (None, "", "   "):
        info = nz.track_info(bad)
        assert info.name == "N/A" and info.code == "N/A" and info.is_known is False


# ---------------------------------------------------------------------------
# end-to-end rows in the style of the reference spreadsheet
# ---------------------------------------------------------------------------

def test_end_to_end_usa_row_matches_reference_style():
    # "Ack Ack S.,2025,Tumbarumba,2020,G,USA,CD,27 September 2025,
    #  8 Furlongs (D),3U,$400,000,G3"
    assert nz.clean_text("Ack Ack&nbsp;S.") == "Ack Ack S."
    assert nz.track_code("Churchill Downs") == "CD"
    assert nz.normalize_date("27 September 2025").display == "27 September 2025"
    assert nz.distance_with_surface(1609, "Dirt") == "8 Furlongs (D)"
    assert nz.purse_to_usd("$400,000", "USA", 2025)[1] == "$400,000"
    assert nz.foaling_year(2025, 5).year == 2020
    assert nz.parse_horse_descriptor("Tumbarumba (USA) 5 B G")["sex"] == "G"


def test_end_to_end_international_row():
    # Japan Cup: Tokyo, 2400m turf, 400,000,000 JPY, 2023.
    assert nz.distance_with_surface(2400, "Turf") == "12 Furlongs (T)"
    assert nz.track_code("Tokyo") == "Tokyo"
    usd, display = nz.purse_to_usd("400,000,000", "JPN", 2023)
    assert 2_500_000 < usd < 3_200_000
    assert display.startswith("$")
    assert nz.normalize_date("26/11/2023").display == "26 November 2023"
