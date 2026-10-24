"""Normalization helpers for the IFHA worldwide Group/Graded stakes pipeline.

IFHA publishes distances in METRES and purses in each jurisdiction's LOCAL
CURRENCY.  This module converts those to the conventions used by the existing
spreadsheet ``USA GSWs (2003-) - Sheet1.csv``:

    Distance  ->  ``8 Furlongs (D)`` / ``6.5 Furlongs (T)``
    Purse     ->  ``$400,000``
    Date      ->  ``27 September 2025`` (plus ISO ``2025-09-27``)
    Sex       ->  single letter ``H`` / ``M`` / ``G`` / ``C`` / ``F`` / ``R``
    Track     ->  short code (``CD``, ``SAR``, ``KD``) for North America,
                  otherwise the full track name unchanged

Nothing in here touches the network at import time, and no function raises on
malformed input -- unparseable fields come back as ``None`` or ``"N/A"``.


FX RATE PROVENANCE  (read this before trusting a USD purse)
-----------------------------------------------------------
Rates are "units of local currency per 1 USD", annual averages, 2003-2026.
Three tiers, distinguishable at runtime via :func:`rate_provenance`:

``"ecb"``
    REAL DATA.  Unweighted mean of every daily ECB reference rate published in
    the calendar year, fetched from the Frankfurter API and cached in
    ``fx_rates.json``.  Covers AUD BRL CAD CHF CNY CZK DKK EUR GBP HKD HUF IDR
    ILS INR ISK JPY KRW MXN MYR NOK NZD PHP PLN RON SEK SGD THB TRY ZAR.
    Note: 2026 is a partial year (averaged over rates published so far), and
    ISK is missing 2009-2017 because the ECB suspended it during Iceland's
    capital controls -- those nine years fall back to tier 3.

``"peg"``
    Hardcoded OFFICIAL PEGS, not fetched.  Exact for the whole period:
    AED 3.6725, SAR 3.75, QAR 3.64, BHD 0.376, OMR 0.3845, BBD 2.0,
    PAB/USD 1.0.  MOP is derived as the ECB HKD rate x 1.03 (its own peg).

``"approximate"``
    *** APPROXIMATIONS.  NOT SOURCED FROM A LIVE FEED. ***
    Hand-entered annual averages from the author's own knowledge, for
    currencies the ECB does not publish: ARS, CLP, PEN, UYU, COP, RUB, MAD,
    TND, KWD, MUR, JMD, TTD (plus ISK 2009-2017).  Expect a few percent of
    error in normal years and considerably more for ARS (hyperinflation /
    multiple official rates) and for 2025-2026 across the board.  Do not use
    these for anything financial without checking them.

``FALLBACK_RATES`` is a fourth, normally-dormant table of approximations for the
major Group-racing currencies the ECB *does* publish.  It is consulted only if
``fx_rates.json`` is missing or corrupt, so that losing the cache degrades to a
rough figure (flagged ``"approximate"``) rather than blanking every purse.  The
test suite asserts it stays within 1% of the real series.

Years outside 2003-2026 clamp to the nearest available year; the year actually
used is reported as ``rate_year`` by :func:`purse_detail`.
"""

from __future__ import annotations

import html
import json
import os
import re
import unicodedata
from typing import NamedTuple, Optional

__all__ = [
    # distance / surface
    "metres_to_furlongs",
    "surface_code",
    "distance_with_surface",
    "Distance",
    "SPREADSHEET_AW_CODE",
    # currency
    "currency_for",
    "purse_to_usd",
    "purse_detail",
    "parse_amount",
    "fx_rate",
    "rate_provenance",
    "available_fx_years",
    "Purse",
    # horse descriptor
    "parse_horse_descriptor",
    "sex_code",
    "colour_name",
    "foaling_year",
    "Foaling",
    # text / date / track
    "clean_text",
    "normalize_date",
    "DateParts",
    "track_name",
    "track_code",
    "track_info",
    "Track",
    # constants
    "NOT_AVAILABLE",
    "FURLONG_METRES",
]

NOT_AVAILABLE = "N/A"
FURLONG_METRES = 201.168


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

_DASHES = dict.fromkeys(
    map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2043\uFE58\uFE63\uFF0D"), "-"
)
_APOSTROPHES = dict.fromkeys(map(ord, "\u2018\u2019\u201A\u201B\u2032\u00B4\u02BC"), "'")
_QUOTES = dict.fromkeys(map(ord, "\u201C\u201D\u201E\u201F\u2033\u00AB\u00BB"), '"')
_PUNCT_TRANSLATION = {**_DASHES, **_APOSTROPHES, **_QUOTES}

# Every whitespace-ish codepoint HTML/Windows-1252 scraping tends to produce.
_SPACEY = (
    "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008"
    "\u2009\u200a\u202f\u205f\u3000\u200b\u200c\u200d\ufeff\u180e"
)
_SPACE_TRANSLATION = dict.fromkeys(map(ord, _SPACEY), " ")

_WS_RUN = re.compile(r"\s+")
# Stray trailing separators to shave off.  Deliberately NOT "." -- the style
# reference keeps race-name periods ("Ack Ack S.", "Beverly D. S.").
_TRAILING_JUNK = re.compile(r"[,;:\u2022\-\s]+$")
_LEADING_JUNK = re.compile(r"^[,;:\u2022\-\s]+")


def clean_text(s) -> str:
    """Scrub scraped text: HTML entities, odd whitespace, unicode punctuation.

    Returns ``"N/A"`` when nothing survives.  Trailing periods are preserved
    because they are meaningful in race names.
    """
    if s is None:
        return NOT_AVAILABLE
    if not isinstance(s, str):
        s = str(s)

    # Entities can be double-escaped (&amp;nbsp;), so unescape until stable.
    for _ in range(3):
        unescaped = html.unescape(s)
        if unescaped == s:
            break
        s = unescaped

    s = unicodedata.normalize("NFC", s)
    s = s.translate(_SPACE_TRANSLATION).translate(_PUNCT_TRANSLATION)
    s = _WS_RUN.sub(" ", s).strip()

    # Peel wrapping quotes, then stray edge punctuation, repeatedly: scraped
    # cells arrive as things like  '"Ack Ack S.",'
    for _ in range(4):
        before = s
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        s = s.strip("\"'").strip()
        s = _LEADING_JUNK.sub("", s)
        s = _TRAILING_JUNK.sub("", s)
        if s == before:
            break

    s = _WS_RUN.sub(" ", s).strip()
    if not s or s.lower() in {"n/a", "na", "none", "null", "-", "--", "?", "tbc", "tba"}:
        return NOT_AVAILABLE
    return s


def _clean_or_none(s) -> Optional[str]:
    out = clean_text(s)
    return None if out == NOT_AVAILABLE else out


# ---------------------------------------------------------------------------
# Distance
# ---------------------------------------------------------------------------

class Distance(NamedTuple):
    """Result of :func:`metres_to_furlongs`.  ``str()`` gives ``display``."""

    display: str          # "8 Furlongs"
    furlongs: Optional[float]      # snapped, e.g. 8.0
    raw_furlongs: Optional[float]  # unsnapped, e.g. 7.9545
    metres: Optional[float]        # as supplied

    def __str__(self) -> str:
        return self.display


# Distances races are actually run at, in furlongs.  Checked before the generic
# quarter-furlong snap so that round metric trips land on the right name
# (1600m -> 8f "a mile", 2400m -> 12f, 3200m -> 16f).
CONVENTIONAL_FURLONGS = (
    2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5,
    8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0,
    13.5, 14.0, 15.0, 16.0, 17.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0,
)

# 0.15f ~ 30m.  Wide enough for every round-metre trip (worst case 4800m ->
# 24f, off by 0.14f), tight enough that a genuine 1670m stays at 8.25f.
_CONVENTIONAL_TOLERANCE = 0.15

_NUMBER_IN_TEXT = re.compile(r"(\d[\d,.\s]*)")


def _coerce_metres(metres) -> Optional[float]:
    if metres is None or isinstance(metres, bool):
        return None
    if isinstance(metres, (int, float)):
        value = float(metres)
    else:
        text = clean_text(metres)
        if text == NOT_AVAILABLE:
            return None
        match = _NUMBER_IN_TEXT.search(text.replace(",", ""))
        if not match:
            return None
        try:
            value = float(match.group(1).replace(" ", ""))
        except ValueError:
            return None
    if value <= 0 or value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _format_furlongs(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def metres_to_furlongs(metres) -> Distance:
    """Convert metres to a snapped furlong display plus the raw values.

    >>> metres_to_furlongs(1600).display
    '8 Furlongs'
    >>> metres_to_furlongs(1300).display
    '6.5 Furlongs'
    """
    value = _coerce_metres(metres)
    if value is None:
        return Distance(NOT_AVAILABLE, None, None, None)

    raw = value / FURLONG_METRES

    best = min(CONVENTIONAL_FURLONGS, key=lambda f: abs(f - raw))
    if abs(best - raw) <= _CONVENTIONAL_TOLERANCE:
        snapped = best
    else:
        snapped = round(raw * 4.0) / 4.0
        if snapped <= 0:
            snapped = 0.25

    label = "Furlong" if snapped == 1 else "Furlongs"
    return Distance(
        f"{_format_furlongs(snapped)} {label}",
        snapped,
        round(raw, 4),
        value,
    )


# Synthetic surfaces are checked first; brand names are the reliable signal.
_AW_PATTERNS = (
    "all weather", "all-weather", "allweather", "awt", "synthetic", "polytrack",
    "poly track", "tapeta", "fibresand", "fibre sand", "cushion track",
    "cushiontrack", "pro-ride", "proride", "equitrack", "safetrack",
    "safe track", "viscoride", "dirt mix", "woodchip", "wood chip",
)
_TURF_PATTERNS = (
    "turf", "grass", "lawn", "gazon", "herbe", "rasen", "erba", "césped",
    "cesped", "inner turf", "outer turf", "hurdle", "steeple",
)
_DIRT_PATTERNS = (
    "dirt", "sand", "sable", "arena", "pista de arena", "main track",
    "inner dirt", "outer dirt", "sloppy", "muddy", "fast track",
)


def surface_code(surface_text) -> str:
    """Map free-text surface to ``D`` / ``T`` / ``AW`` / ``N/A``."""
    text = clean_text(surface_text)
    if text == NOT_AVAILABLE:
        return NOT_AVAILABLE
    low = text.lower()

    for needle in _AW_PATTERNS:
        if needle in low:
            return "AW"
    for needle in _TURF_PATTERNS:
        if needle in low:
            return "T"
    for needle in _DIRT_PATTERNS:
        if needle in low:
            return "D"

    # Bare codes: "D", "T", "AW", "(T)", "A".  "E" is the style reference's
    # own all-weather code, accepted so our output can be re-read.
    bare = re.sub(r"[^a-z]", "", low)
    if bare in {"aw", "a", "s", "p", "e"}:
        return "AW"
    if bare in {"t", "g"}:
        return "T"
    if bare in {"d", "dt"}:
        return "D"
    return NOT_AVAILABLE


#: The style-reference spreadsheet writes all-weather as "(E)", not "(AW)" --
#: its one synthetic row is "6.5 Furlongs (E)" at Presque Isle Downs (Tapeta).
#: Pass this to :func:`distance_with_surface` to reproduce that exactly.
SPREADSHEET_AW_CODE = "E"


def distance_with_surface(metres, surface_text, aw_code: str = "AW") -> str:
    """``8 Furlongs (D)`` -- the combined form used by the spreadsheet.

    ``aw_code`` controls how all-weather is rendered.  Defaults to ``"AW"``;
    pass ``SPREADSHEET_AW_CODE`` ("E") to match the existing sheet.
    """
    distance = metres_to_furlongs(metres)
    code = surface_code(surface_text)
    if distance.display == NOT_AVAILABLE:
        return NOT_AVAILABLE
    if code == NOT_AVAILABLE:
        return distance.display
    if code == "AW" and aw_code:
        code = str(aw_code)
    return f"{distance.display} ({code})"


# ---------------------------------------------------------------------------
# Jurisdiction -> currency
# ---------------------------------------------------------------------------

#: IFHA country abbreviations and full names -> ISO 4217.
JURISDICTION_CURRENCY = {
    # --- North America -------------------------------------------------
    "USA": "USD", "US": "USD", "UNITED STATES": "USD",
    "UNITED STATES OF AMERICA": "USD", "AMERICA": "USD",
    "PR": "USD", "PUR": "USD", "PUERTO RICO": "USD",
    "CAN": "CAD", "CA": "CAD", "CAN.": "CAD", "CANADA": "CAD",
    "MEX": "MXN", "MX": "MXN", "MEXICO": "MXN",
    "PAN": "PAB", "PANAMA": "PAB",
    "JAM": "JMD", "JAMAICA": "JMD",
    "TRI": "TTD", "TTO": "TTD", "TRINIDAD": "TTD",
    "TRINIDAD AND TOBAGO": "TTD",
    "BAR": "BBD", "BARBADOS": "BBD",
    # --- South America -------------------------------------------------
    "ARG": "ARS", "AR": "ARS", "ARGENTINA": "ARS",
    "BRZ": "BRL", "BRA": "BRL", "BR": "BRL", "BRAZIL": "BRL", "BRASIL": "BRL",
    "CHI": "CLP", "CHL": "CLP", "CHILE": "CLP",
    "PER": "PEN", "PE": "PEN", "PERU": "PEN",
    "URU": "UYU", "URY": "UYU", "UY": "UYU", "URUGUAY": "UYU",
    "COL": "COP", "COLOMBIA": "COP",
    "ECU": "USD", "ECUADOR": "USD",  # dollarized since 2000
    "VEN": "VES", "VENEZUELA": "VES",
    # --- Western Europe (euro) -----------------------------------------
    "GB": "GBP", "GBR": "GBP", "UK": "GBP", "ENG": "GBP",
    "GREAT BRITAIN": "GBP", "ENGLAND": "GBP", "UNITED KINGDOM": "GBP",
    "SCO": "GBP", "SCOTLAND": "GBP", "WAL": "GBP", "WALES": "GBP",
    "IRE": "EUR", "IRL": "EUR", "IR": "EUR", "IRELAND": "EUR",
    "FR": "EUR", "FRA": "EUR", "FRANCE": "EUR",
    "GER": "EUR", "DEU": "EUR", "GERMANY": "EUR", "DEUTSCHLAND": "EUR",
    "ITY": "EUR", "ITA": "EUR", "IT": "EUR", "ITALY": "EUR", "ITALIA": "EUR",
    "SPA": "EUR", "ESP": "EUR", "SPAIN": "EUR", "ESPANA": "EUR",
    "POR": "EUR", "PRT": "EUR", "PORTUGAL": "EUR",
    "NED": "EUR", "NLD": "EUR", "HOL": "EUR",
    "NETHERLANDS": "EUR", "HOLLAND": "EUR",
    "BEL": "EUR", "BELGIUM": "EUR",
    "AUT": "EUR", "AUSTRIA": "EUR",
    "FIN": "EUR", "FINLAND": "EUR",
    "GRE": "EUR", "GREECE": "EUR",
    "CYP": "EUR", "CYPRUS": "EUR",
    "MLT": "EUR", "MALTA": "EUR",
    "SVK": "EUR", "SLOVAKIA": "EUR",
    "SVN": "EUR", "SLOVENIA": "EUR",
    "CRO": "EUR", "HRV": "EUR", "CROATIA": "EUR",  # HRK before 2023
    # --- Rest of Europe ------------------------------------------------
    "SWE": "SEK", "SWEDEN": "SEK",
    "NOR": "NOK", "NORWAY": "NOK",
    "DEN": "DKK", "DNK": "DKK", "DENMARK": "DKK",
    "SWI": "CHF", "SUI": "CHF", "CHE": "CHF", "SWITZERLAND": "CHF",
    "CZE": "CZK", "CZ": "CZK", "CZECH REPUBLIC": "CZK", "CZECHIA": "CZK",
    "POL": "PLN", "PL": "PLN", "POLAND": "PLN",
    "HUN": "HUF", "HU": "HUF", "HUNGARY": "HUF",
    "RUS": "RUB", "RU": "RUB", "RUSSIA": "RUB",
    "ROM": "RON", "ROU": "RON", "ROMANIA": "RON",
    "ICE": "ISK", "ISL": "ISK", "ICELAND": "ISK",
    "TUR": "TRY", "TR": "TRY", "TURKEY": "TRY", "TURKIYE": "TRY",
    # --- Asia / Oceania ------------------------------------------------
    "JPN": "JPY", "JP": "JPY", "JPA": "JPY", "JAPAN": "JPY",
    "AUS": "AUD", "AU": "AUD", "AUSTRALIA": "AUD",
    "NZ": "NZD", "NZL": "NZD", "NEW ZEALAND": "NZD",
    "HK": "HKD", "HKG": "HKD", "HONG KONG": "HKD",
    "SIN": "SGD", "SGP": "SGD", "SINGAPORE": "SGD",
    "MAC": "MOP", "MO": "MOP", "MACAU": "MOP", "MACAO": "MOP",
    "MAL": "MYR", "MAS": "MYR", "MYS": "MYR", "MALAYSIA": "MYR",
    "KOR": "KRW", "KR": "KRW", "SOUTH KOREA": "KRW",
    "KOREA": "KRW", "REPUBLIC OF KOREA": "KRW",
    "CHN": "CNY", "CN": "CNY", "CHINA": "CNY",
    "IND": "INR", "INDIA": "INR",
    "PHI": "PHP", "PHL": "PHP", "PHILIPPINES": "PHP",
    "THA": "THB", "THAILAND": "THB",
    "INA": "IDR", "IDN": "IDR", "INDONESIA": "IDR",
    # --- Middle East ---------------------------------------------------
    "UAE": "AED", "ARE": "AED", "UNITED ARAB EMIRATES": "AED",
    "DUBAI": "AED", "ABU DHABI": "AED",
    "SAU": "SAR", "SAUDI ARABIA": "SAR", "KSA": "SAR",
    "QA": "QAR", "QAT": "QAR", "QATAR": "QAR",
    "BHR": "BHD", "BRN": "BHD", "BAHRAIN": "BHD",
    "KUW": "KWD", "KWT": "KWD", "KUWAIT": "KWD",
    "OMA": "OMR", "OMN": "OMR", "OMAN": "OMR",
    "ISR": "ILS", "ISRAEL": "ILS",
    # --- Africa --------------------------------------------------------
    "SAF": "ZAR", "RSA": "ZAR", "ZAF": "ZAR", "SOUTH AFRICA": "ZAR",
    "MOR": "MAD", "MAR": "MAD", "MOROCCO": "MAD",
    "TUN": "TND", "TUNISIA": "TND",
    "MAU": "MUR", "MUS": "MUR", "MAURITIUS": "MUR",
    "ZIM": "USD", "ZIMBABWE": "USD",  # USD-denominated racing
}

_KNOWN_CURRENCIES = set(JURISDICTION_CURRENCY.values())


def currency_for(country_or_currency) -> Optional[str]:
    """Resolve an IFHA country code, country name, or ISO currency to ISO 4217."""
    text = _clean_or_none(country_or_currency)
    if text is None:
        return None

    # "GB", "(GB)", "Great Britain", "GBP", "USA - Kentucky"
    key = text.upper().strip()
    key = re.sub(r"^\(|\)$", "", key).strip()
    key = re.sub(r"[\u2013\u2014]", "-", key)
    key = re.sub(r"\s*[-/,|].*$", "", key).strip()  # drop state/region suffix
    key = re.sub(r"\.", "", key)
    key = _WS_RUN.sub(" ", key)

    if key in JURISDICTION_CURRENCY:
        return JURISDICTION_CURRENCY[key]
    if key in _KNOWN_CURRENCIES or (len(key) == 3 and key.isalpha() and key in _ALL_RATE_CURRENCIES):
        return key
    # Last chance: strip "THE ", trailing "RACING"
    alt = re.sub(r"^THE\s+", "", key)
    return JURISDICTION_CURRENCY.get(alt)


# ---------------------------------------------------------------------------
# FX rates
# ---------------------------------------------------------------------------

FX_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fx_rates.json")

FX_FIRST_YEAR = 2003
FX_LAST_YEAR = 2026

#: Official pegs, flat across 2003-2026.  Exact, but hardcoded rather than fetched.
PEGGED_RATES = {
    "USD": 1.0,
    "AED": 3.6725,   # peg since Nov 1997
    "SAR": 3.75,     # peg since 1986
    "QAR": 3.64,     # peg since 2001
    "BHD": 0.376,    # peg since 1980
    "OMR": 0.3845,   # peg since 1986
    "PAB": 1.0,      # balboa at par with USD
    "BBD": 2.0,      # peg since 1975
}

#: MOP is pegged to HKD, so track the real HKD series instead of guessing.
_DERIVED_FROM_HKD = {"MOP": 1.03}

# *** APPROXIMATIONS -- author's own knowledge, not a live feed. ***
# Units of local currency per 1 USD, annual average.  See module docstring.
APPROXIMATE_RATES = {
    "ARS": {  # Argentina: multiple official rates + hyperinflation; weakest data
        2003: 2.95, 2004: 2.92, 2005: 2.92, 2006: 3.07, 2007: 3.12, 2008: 3.16,
        2009: 3.73, 2010: 3.90, 2011: 4.13, 2012: 4.55, 2013: 5.48, 2014: 8.12,
        2015: 9.27, 2016: 14.78, 2017: 16.56, 2018: 28.09, 2019: 48.15,
        2020: 70.54, 2021: 94.99, 2022: 130.6, 2023: 296.3, 2024: 913.0,
        2025: 1300.0, 2026: 1500.0,
    },
    "CLP": {
        2003: 691.0, 2004: 609.0, 2005: 560.0, 2006: 530.0, 2007: 522.0,
        2008: 522.0, 2009: 560.0, 2010: 510.0, 2011: 484.0, 2012: 486.0,
        2013: 495.0, 2014: 570.0, 2015: 654.0, 2016: 677.0, 2017: 649.0,
        2018: 641.0, 2019: 703.0, 2020: 792.0, 2021: 759.0, 2022: 873.0,
        2023: 840.0, 2024: 944.0, 2025: 960.0, 2026: 930.0,
    },
    "PEN": {
        2003: 3.48, 2004: 3.41, 2005: 3.30, 2006: 3.27, 2007: 3.13, 2008: 2.92,
        2009: 3.01, 2010: 2.83, 2011: 2.75, 2012: 2.64, 2013: 2.70, 2014: 2.84,
        2015: 3.19, 2016: 3.38, 2017: 3.26, 2018: 3.29, 2019: 3.34, 2020: 3.50,
        2021: 3.88, 2022: 3.84, 2023: 3.74, 2024: 3.74, 2025: 3.60, 2026: 3.50,
    },
    "UYU": {
        2003: 28.2, 2004: 28.7, 2005: 24.5, 2006: 24.1, 2007: 23.5, 2008: 20.9,
        2009: 22.6, 2010: 20.1, 2011: 19.3, 2012: 20.3, 2013: 20.5, 2014: 23.2,
        2015: 27.3, 2016: 30.2, 2017: 28.7, 2018: 30.7, 2019: 35.3, 2020: 42.0,
        2021: 43.6, 2022: 41.2, 2023: 38.8, 2024: 40.0, 2025: 41.0, 2026: 41.0,
    },
    "COP": {
        2003: 2878.0, 2004: 2628.0, 2005: 2321.0, 2006: 2358.0, 2007: 2076.0,
        2008: 1967.0, 2009: 2158.0, 2010: 1899.0, 2011: 1848.0, 2012: 1798.0,
        2013: 1869.0, 2014: 2001.0, 2015: 2742.0, 2016: 3055.0, 2017: 2951.0,
        2018: 2956.0, 2019: 3281.0, 2020: 3693.0, 2021: 3744.0, 2022: 4256.0,
        2023: 4326.0, 2024: 4072.0, 2025: 4100.0, 2026: 3900.0,
    },
    "RUB": {  # ECB stopped publishing RUB in 2022; whole series is approximate
        2003: 30.7, 2004: 28.8, 2005: 28.3, 2006: 27.2, 2007: 25.6, 2008: 24.9,
        2009: 31.7, 2010: 30.4, 2011: 29.4, 2012: 31.1, 2013: 31.8, 2014: 38.4,
        2015: 61.0, 2016: 67.0, 2017: 58.3, 2018: 62.7, 2019: 64.7, 2020: 72.1,
        2021: 73.7, 2022: 68.5, 2023: 85.2, 2024: 92.5, 2025: 85.0, 2026: 85.0,
    },
    "MAD": {
        2003: 9.57, 2004: 8.87, 2005: 8.87, 2006: 8.80, 2007: 8.19, 2008: 7.75,
        2009: 8.06, 2010: 8.42, 2011: 8.09, 2012: 8.63, 2013: 8.41, 2014: 8.41,
        2015: 9.76, 2016: 9.81, 2017: 9.69, 2018: 9.39, 2019: 9.62, 2020: 9.50,
        2021: 8.99, 2022: 10.16, 2023: 10.13, 2024: 9.94, 2025: 9.40, 2026: 9.20,
    },
    "TND": {
        2003: 1.29, 2004: 1.25, 2005: 1.30, 2006: 1.33, 2007: 1.28, 2008: 1.23,
        2009: 1.35, 2010: 1.43, 2011: 1.41, 2012: 1.56, 2013: 1.62, 2014: 1.70,
        2015: 1.96, 2016: 2.15, 2017: 2.42, 2018: 2.65, 2019: 2.93, 2020: 2.81,
        2021: 2.79, 2022: 3.10, 2023: 3.11, 2024: 3.11, 2025: 2.95, 2026: 2.90,
    },
    "KWD": {  # basket peg, drifts slightly
        2003: 0.2995, 2004: 0.2947, 2005: 0.2917, 2006: 0.2900, 2007: 0.2840,
        2008: 0.2692, 2009: 0.2877, 2010: 0.2862, 2011: 0.2757, 2012: 0.2796,
        2013: 0.2840, 2014: 0.2829, 2015: 0.3022, 2016: 0.3017, 2017: 0.3022,
        2018: 0.3020, 2019: 0.3037, 2020: 0.3072, 2021: 0.3018, 2022: 0.3063,
        2023: 0.3076, 2024: 0.3070, 2025: 0.3065, 2026: 0.3050,
    },
    "MUR": {
        2003: 27.9, 2004: 27.5, 2005: 29.5, 2006: 31.7, 2007: 31.1, 2008: 28.5,
        2009: 31.9, 2010: 30.8, 2011: 28.7, 2012: 30.1, 2013: 30.7, 2014: 30.6,
        2015: 35.5, 2016: 35.5, 2017: 34.5, 2018: 34.0, 2019: 35.5, 2020: 39.3,
        2021: 41.6, 2022: 44.0, 2023: 45.3, 2024: 46.4, 2025: 46.0, 2026: 46.0,
    },
    "JMD": {
        2003: 57.7, 2004: 61.2, 2005: 62.5, 2006: 65.9, 2007: 69.0, 2008: 72.2,
        2009: 88.3, 2010: 87.4, 2011: 85.9, 2012: 89.0, 2013: 100.7, 2014: 111.2,
        2015: 117.2, 2016: 125.1, 2017: 128.4, 2018: 129.0, 2019: 134.3,
        2020: 142.5, 2021: 150.0, 2022: 153.4, 2023: 154.6, 2024: 156.5,
        2025: 158.0, 2026: 160.0,
    },
    "TTD": {
        2003: 6.30, 2004: 6.30, 2005: 6.29, 2006: 6.31, 2007: 6.33, 2008: 6.29,
        2009: 6.32, 2010: 6.37, 2011: 6.40, 2012: 6.40, 2013: 6.42, 2014: 6.38,
        2015: 6.35, 2016: 6.66, 2017: 6.78, 2018: 6.78, 2019: 6.76, 2020: 6.76,
        2021: 6.78, 2022: 6.78, 2023: 6.78, 2024: 6.78, 2025: 6.78, 2026: 6.78,
    },
    # ECB suspended ISK during Iceland's capital controls.
    "ISK": {
        2009: 123.6, 2010: 122.2, 2011: 116.0, 2012: 125.1, 2013: 122.2,
        2014: 116.8, 2015: 131.9, 2016: 120.8, 2017: 106.8,
    },
}

# *** APPROXIMATIONS, LAST RESORT ONLY. ***
# Shadow table for the main Group-racing currencies that the ECB *does* publish.
# Normally unused -- the merge below prefers the real cached rate.  This exists
# only so that deleting/corrupting fx_rates.json degrades to a rough number
# instead of turning every non-US purse into "N/A".  Provenance still reports
# "approximate" when one of these is used, so the fallback is never silent.
FALLBACK_RATES = {
    "GBP": {
        2003: 0.612, 2004: 0.546, 2005: 0.550, 2006: 0.543, 2007: 0.500,
        2008: 0.544, 2009: 0.641, 2010: 0.648, 2011: 0.624, 2012: 0.631,
        2013: 0.640, 2014: 0.608, 2015: 0.654, 2016: 0.741, 2017: 0.777,
        2018: 0.750, 2019: 0.783, 2020: 0.780, 2021: 0.727, 2022: 0.811,
        2023: 0.805, 2024: 0.782, 2025: 0.759, 2026: 0.744,
    },
    "EUR": {
        2003: 0.886, 2004: 0.805, 2005: 0.804, 2006: 0.797, 2007: 0.731,
        2008: 0.684, 2009: 0.719, 2010: 0.756, 2011: 0.719, 2012: 0.778,
        2013: 0.753, 2014: 0.754, 2015: 0.902, 2016: 0.904, 2017: 0.887,
        2018: 0.847, 2019: 0.893, 2020: 0.877, 2021: 0.845, 2022: 0.951,
        2023: 0.925, 2024: 0.924, 2025: 0.887, 2026: 0.862,
    },
    "JPY": {
        2003: 115.9, 2004: 108.2, 2005: 110.2, 2006: 116.3, 2007: 117.8,
        2008: 103.4, 2009: 93.6, 2010: 87.7, 2011: 79.8, 2012: 79.8,
        2013: 97.6, 2014: 105.9, 2015: 121.0, 2016: 108.8, 2017: 112.2,
        2018: 110.4, 2019: 109.0, 2020: 106.7, 2021: 109.8, 2022: 131.5,
        2023: 140.5, 2024: 151.4, 2025: 149.7, 2026: 158.5,
    },
    "AUD": {
        2003: 1.542, 2004: 1.360, 2005: 1.311, 2006: 1.328, 2007: 1.195,
        2008: 1.192, 2009: 1.282, 2010: 1.090, 2011: 0.970, 2012: 0.966,
        2013: 1.036, 2014: 1.109, 2015: 1.331, 2016: 1.345, 2017: 1.305,
        2018: 1.338, 2019: 1.439, 2020: 1.452, 2021: 1.331, 2022: 1.442,
        2023: 1.506, 2024: 1.517, 2025: 1.552, 2026: 1.422,
    },
    "NZD": {
        2003: 1.722, 2004: 1.509, 2005: 1.420, 2006: 1.543, 2007: 1.361,
        2008: 1.422, 2009: 1.600, 2010: 1.388, 2011: 1.266, 2012: 1.234,
        2013: 1.219, 2014: 1.205, 2015: 1.435, 2016: 1.436, 2017: 1.408,
        2018: 1.448, 2019: 1.518, 2020: 1.542, 2021: 1.414, 2022: 1.577,
        2023: 1.627, 2024: 1.650, 2025: 1.720, 2026: 1.711,
    },
    "HKD": {
        2003: 7.787, 2004: 7.788, 2005: 7.777, 2006: 7.768, 2007: 7.801,
        2008: 7.787, 2009: 7.752, 2010: 7.769, 2011: 7.784, 2012: 7.757,
        2013: 7.757, 2014: 7.754, 2015: 7.752, 2016: 7.762, 2017: 7.793,
        2018: 7.839, 2019: 7.836, 2020: 7.756, 2021: 7.773, 2022: 7.831,
        2023: 7.830, 2024: 7.803, 2025: 7.796, 2026: 7.830,
    },
    "SGD": {
        2003: 1.742, 2004: 1.690, 2005: 1.664, 2006: 1.589, 2007: 1.507,
        2008: 1.415, 2009: 1.454, 2010: 1.364, 2011: 1.257, 2012: 1.250,
        2013: 1.251, 2014: 1.267, 2015: 1.375, 2016: 1.382, 2017: 1.381,
        2018: 1.349, 2019: 1.364, 2020: 1.380, 2021: 1.344, 2022: 1.379,
        2023: 1.343, 2024: 1.337, 2025: 1.307, 2026: 1.282,
    },
    "CAD": {
        2003: 1.401, 2004: 1.301, 2005: 1.212, 2006: 1.134, 2007: 1.074,
        2008: 1.067, 2009: 1.141, 2010: 1.030, 2011: 0.989, 2012: 1.000,
        2013: 1.030, 2014: 1.105, 2015: 1.279, 2016: 1.325, 2017: 1.298,
        2018: 1.296, 2019: 1.327, 2020: 1.341, 2021: 1.254, 2022: 1.302,
        2023: 1.350, 2024: 1.370, 2025: 1.385, 2026: 1.386,
    },
    "ZAR": {
        2003: 7.567, 2004: 6.460, 2005: 6.360, 2006: 6.772, 2007: 7.045,
        2008: 8.261, 2009: 8.470, 2010: 7.321, 2011: 7.261, 2012: 8.209,
        2013: 9.655, 2014: 10.853, 2015: 12.758, 2016: 14.710, 2017: 13.324,
        2018: 13.234, 2019: 14.448, 2020: 16.436, 2021: 14.779, 2022: 16.356,
        2023: 18.450, 2024: 18.330, 2025: 17.882, 2026: 16.371,
    },
    "KRW": {
        2003: 1191.0, 2004: 1145.0, 2005: 1024.0, 2006: 955.0, 2007: 929.0,
        2008: 1102.0, 2009: 1276.0, 2010: 1157.0, 2011: 1108.0, 2012: 1127.0,
        2013: 1095.0, 2014: 1053.0, 2015: 1133.0, 2016: 1160.0, 2017: 1130.0,
        2018: 1100.0, 2019: 1165.0, 2020: 1179.0, 2021: 1144.0, 2022: 1292.0,
        2023: 1306.0, 2024: 1364.0, 2025: 1422.0, 2026: 1460.0,
    },
    "TRY": {
        2003: 1.502, 2004: 1.426, 2005: 1.343, 2006: 1.431, 2007: 1.303,
        2008: 1.303, 2009: 1.550, 2010: 1.508, 2011: 1.675, 2012: 1.796,
        2013: 1.904, 2014: 2.188, 2015: 2.720, 2016: 3.020, 2017: 3.648,
        2018: 4.828, 2019: 5.674, 2020: 7.028, 2021: 8.886, 2022: 16.566,
        2023: 23.74, 2024: 32.80, 2025: 39.55, 2026: 45.79,
    },
    "INR": {
        2003: 46.54, 2004: 45.28, 2005: 44.10, 2006: 45.31, 2007: 41.35,
        2008: 43.51, 2009: 48.41, 2010: 45.73, 2011: 46.67, 2012: 53.44,
        2013: 58.60, 2014: 61.03, 2015: 64.15, 2016: 67.20, 2017: 65.12,
        2018: 68.39, 2019: 70.42, 2020: 74.10, 2021: 73.94, 2022: 78.60,
        2023: 82.59, 2024: 83.67, 2025: 87.16, 2026: 93.97,
    },
    "BRL": {
        2003: 3.078, 2004: 2.926, 2005: 2.435, 2006: 2.175, 2007: 1.948,
        2008: 1.834, 2009: 1.994, 2010: 1.759, 2011: 1.675, 2012: 1.955,
        2013: 2.161, 2014: 2.353, 2015: 3.333, 2016: 3.490, 2017: 3.192,
        2018: 3.654, 2019: 3.945, 2020: 5.150, 2021: 5.396, 2022: 5.165,
        2023: 4.996, 2024: 5.393, 2025: 5.592, 2026: 5.150,
    },
    "CHF": {
        2003: 1.346, 2004: 1.243, 2005: 1.245, 2006: 1.254, 2007: 1.200,
        2008: 1.083, 2009: 1.086, 2010: 1.043, 2011: 0.887, 2012: 0.938,
        2013: 0.927, 2014: 0.915, 2015: 0.962, 2016: 0.985, 2017: 0.985,
        2018: 0.978, 2019: 0.994, 2020: 0.939, 2021: 0.914, 2022: 0.955,
        2023: 0.899, 2024: 0.882, 2025: 0.831, 2026: 0.796,
    },
    "SEK": {
        2003: 8.09, 2004: 7.35, 2005: 7.47, 2006: 7.38, 2007: 6.76,
        2008: 6.58, 2009: 7.65, 2010: 7.21, 2011: 6.49, 2012: 6.78,
        2013: 6.51, 2014: 6.86, 2015: 8.43, 2016: 8.56, 2017: 8.55,
        2018: 8.69, 2019: 9.46, 2020: 9.21, 2021: 8.58, 2022: 10.12,
        2023: 10.61, 2024: 10.58, 2025: 9.82, 2026: 9.40,
    },
    "NOK": {
        2003: 7.08, 2004: 6.74, 2005: 6.44, 2006: 6.41, 2007: 5.86,
        2008: 5.64, 2009: 6.29, 2010: 6.04, 2011: 5.61, 2012: 5.82,
        2013: 5.88, 2014: 6.30, 2015: 8.07, 2016: 8.40, 2017: 8.27,
        2018: 8.13, 2019: 8.80, 2020: 9.42, 2021: 8.59, 2022: 9.61,
        2023: 10.57, 2024: 10.76, 2025: 10.39, 2026: 9.56,
    },
    "DKK": {
        2003: 6.60, 2004: 5.99, 2005: 5.99, 2006: 5.94, 2007: 5.44,
        2008: 5.10, 2009: 5.36, 2010: 5.63, 2011: 5.36, 2012: 5.79,
        2013: 5.62, 2014: 5.62, 2015: 6.73, 2016: 6.73, 2017: 6.60,
        2018: 6.31, 2019: 6.67, 2020: 6.54, 2021: 6.29, 2022: 7.08,
        2023: 6.89, 2024: 6.89, 2025: 6.62, 2026: 6.43,
    },
    "MYR": {
        2003: 3.80, 2004: 3.80, 2005: 3.79, 2006: 3.67, 2007: 3.44,
        2008: 3.34, 2009: 3.52, 2010: 3.22, 2011: 3.06, 2012: 3.09,
        2013: 3.15, 2014: 3.27, 2015: 3.91, 2016: 4.15, 2017: 4.30,
        2018: 4.04, 2019: 4.14, 2020: 4.20, 2021: 4.14, 2022: 4.40,
        2023: 4.56, 2024: 4.57, 2025: 4.28, 2026: 4.01,
    },
    "MXN": {
        2003: 10.79, 2004: 11.29, 2005: 10.90, 2006: 10.90, 2007: 10.93,
        2008: 11.14, 2009: 13.51, 2010: 12.63, 2011: 12.42, 2012: 13.17,
        2013: 12.77, 2014: 13.30, 2015: 15.85, 2016: 18.67, 2017: 18.93,
        2018: 19.24, 2019: 19.26, 2020: 21.47, 2021: 20.28, 2022: 20.13,
        2023: 17.74, 2024: 18.33, 2025: 19.22, 2026: 17.41,
    },
}

#: Currencies we deliberately refuse to convert (redenominations/hyperinflation
#: make any single annual average meaningless).
UNSUPPORTED_CURRENCIES = {"VES", "VEF"}


def _load_cached_rates() -> tuple[dict, dict]:
    """Read ``fx_rates.json`` -> ({year: {cur: rate}}, meta). Never raises."""
    try:
        with open(FX_CACHE_PATH, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return {}, {}

    raw = payload.get("rates", payload) if isinstance(payload, dict) else {}
    out: dict[int, dict[str, float]] = {}
    for year, per_currency in (raw or {}).items():
        if not isinstance(per_currency, dict):
            continue
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            continue
        clean: dict[str, float] = {}
        for code, rate in per_currency.items():
            try:
                rate_f = float(rate)
            except (TypeError, ValueError):
                continue
            if rate_f > 0:
                clean[str(code).upper()] = rate_f
        if clean:
            out[year_int] = clean
    meta = payload.get("_meta", {}) if isinstance(payload, dict) else {}
    return out, meta


_LIVE_RATES, FX_META = _load_cached_rates()

# Merge the three tiers into one table, remembering where each number came from.
_RATES: dict[int, dict[str, float]] = {}
_PROVENANCE: dict[int, dict[str, str]] = {}

_years = sorted(set(_LIVE_RATES) | set(range(FX_FIRST_YEAR, FX_LAST_YEAR + 1)))
for _year in _years:
    _row: dict[str, float] = {}
    _prov: dict[str, str] = {}
    for _code, _rate in _LIVE_RATES.get(_year, {}).items():
        _row[_code] = _rate
        _prov[_code] = "ecb"
    for _code, _rate in PEGGED_RATES.items():
        _row.setdefault(_code, _rate)
        _prov.setdefault(_code, "peg")
    for _code, _factor in _DERIVED_FROM_HKD.items():
        if "HKD" in _row and _code not in _row:
            _row[_code] = _row["HKD"] * _factor
            _prov[_code] = "peg"
    for _table in (APPROXIMATE_RATES, FALLBACK_RATES):
        for _code, _series in _table.items():
            if _code not in _row and _year in _series:
                _row[_code] = float(_series[_year])
                _prov[_code] = "approximate"
    _RATES[_year] = _row
    _PROVENANCE[_year] = _prov

_ALL_RATE_CURRENCIES = {c for row in _RATES.values() for c in row} | {"USD"}


def _currencies_with_provenance(kind: str) -> frozenset:
    return frozenset(
        code
        for row in _PROVENANCE.values()
        for code, prov in row.items()
        if prov == kind
    )


#: Derived from the merged table, so they tell the truth about what actually
#: loaded rather than about what tables exist.
REAL_RATE_CURRENCIES = _currencies_with_provenance("ecb")
APPROXIMATE_CURRENCIES = _currencies_with_provenance("approximate")
PEGGED_CURRENCIES = _currencies_with_provenance("peg")


def available_fx_years() -> list[int]:
    return sorted(_RATES)


def _resolve_year(year) -> Optional[int]:
    if year is None or isinstance(year, bool):
        return None
    try:
        year_int = int(str(year).strip()[:4]) if isinstance(year, str) else int(year)
    except (TypeError, ValueError, OverflowError):
        return None
    if not _RATES:
        return None
    years = available_fx_years()
    if year_int in _RATES:
        return year_int
    # 2026 (or any out-of-range year) falls back to the closest year we have.
    return max(years) if year_int > max(years) else min(years)


def fx_rate(currency, year) -> tuple[Optional[float], Optional[int]]:
    """Units of ``currency`` per 1 USD for ``year``.

    Returns ``(rate, year_actually_used)``; ``(None, None)`` if unknown.
    """
    code = currency_for(currency)
    if code is None or code in UNSUPPORTED_CURRENCIES:
        return None, None
    used = _resolve_year(year)
    if used is None:
        return None, None

    if code in _RATES[used]:
        return _RATES[used][code], used
    # Currency absent for that year (e.g. ISK outside the approximate window):
    # walk outwards to the nearest year that has it.
    for offset in range(1, len(_RATES) + 1):
        for candidate in (used - offset, used + offset):
            if candidate in _RATES and code in _RATES[candidate]:
                return _RATES[candidate][code], candidate
    return None, None


def rate_provenance(currency, year) -> Optional[str]:
    """``"ecb"`` (real), ``"peg"`` (official peg), ``"approximate"``, or None."""
    code = currency_for(currency)
    if code is None or code in UNSUPPORTED_CURRENCIES:
        return None
    used = _resolve_year(year)
    if used is None:
        return None
    if code in _PROVENANCE[used]:
        return _PROVENANCE[used][code]
    for offset in range(1, len(_RATES) + 1):
        for candidate in (used - offset, used + offset):
            if candidate in _PROVENANCE and code in _PROVENANCE[candidate]:
                return _PROVENANCE[candidate][code]
    return None


# ---------------------------------------------------------------------------
# Purse
# ---------------------------------------------------------------------------

class Purse(NamedTuple):
    """Full result of :func:`purse_detail`."""

    usd: Optional[float]
    display: str                  # "$400,000"
    amount: Optional[float]       # original local amount
    currency: Optional[str]       # original ISO currency
    rate: Optional[float]         # local units per USD
    rate_year: Optional[int]      # year the rate came from
    provenance: Optional[str]     # "ecb" | "peg" | "approximate"

    def __str__(self) -> str:
        return self.display


_AMOUNT_CHARS = re.compile(r"[^\d.,\-]")


def parse_amount(amount) -> Optional[float]:
    """Parse a purse figure out of messy text. Handles ``$400,000``,
    ``1.000.000`` (European grouping), ``AED 10,000,000``, ``¥1 0000``."""
    if amount is None or isinstance(amount, bool):
        return None
    if isinstance(amount, (int, float)):
        value = float(amount)
        return value if value >= 0 else None

    text = clean_text(amount)
    if text == NOT_AVAILABLE:
        return None
    text = _AMOUNT_CHARS.sub("", text).strip()
    text = text.lstrip("-")  # negative purses are nonsense
    if not text or not any(ch.isdigit() for ch in text):
        return None

    has_dot, has_comma = "." in text, "," in text
    if has_dot and has_comma:
        # Whichever separator comes last is the decimal point.
        if text.rfind(".") > text.rfind(","):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif has_comma:
        parts = text.split(",")
        # "1,5" is decimal; "1,500" / "1,500,000" is grouping.
        if len(parts) == 2 and len(parts[1]) != 3:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_dot:
        parts = text.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3
                              and parts[0] != "0"):
            text = text.replace(".", "")

    try:
        value = float(text)
    except ValueError:
        return None
    return value if value >= 0 else None


def _format_usd(usd: float) -> str:
    return f"${round(usd):,.0f}"


def purse_detail(amount, country_or_currency, year) -> Purse:
    """Convert a local purse to USD, keeping every raw input for audit columns."""
    local = parse_amount(amount)
    code = currency_for(country_or_currency)

    if local is None:
        return Purse(None, NOT_AVAILABLE, None, code, None, None, None)
    if code is None:
        return Purse(None, NOT_AVAILABLE, local, None, None, None, None)
    if code == "USD":
        return Purse(float(local), _format_usd(local), local, "USD", 1.0,
                     _resolve_year(year), "peg")

    rate, used_year = fx_rate(code, year)
    if rate is None or rate <= 0:
        return Purse(None, NOT_AVAILABLE, local, code, None, None, None)

    usd = local / rate
    return Purse(
        float(usd), _format_usd(usd), local, code, rate, used_year,
        rate_provenance(code, year),
    )


def purse_to_usd(amount, country_or_currency, year) -> tuple[Optional[float], str]:
    """``(usd_float, "$400,000")``.  ``(None, "N/A")`` when not convertible."""
    detail = purse_detail(amount, country_or_currency, year)
    return detail.usd, detail.display


# ---------------------------------------------------------------------------
# Horse descriptor
# ---------------------------------------------------------------------------

#: Abbreviation (normalized: upper, no spaces/periods) -> expanded colour.
COLOUR_NAMES = {
    "B": "Bay",
    "BAY": "Bay",
    "BR": "Brown",
    "BRN": "Brown",
    "BROWN": "Brown",
    "CH": "Chestnut",
    "CHE": "Chestnut",
    "CHES": "Chestnut",
    "CHESTNUT": "Chestnut",
    "GR": "Grey",
    "GRY": "Grey",
    "GREY": "Grey",
    "GRAY": "Grey",
    "BLK": "Black",
    "BL": "Black",
    "BLACK": "Black",
    "RO": "Roan",
    "ROAN": "Roan",
    "WH": "White",
    "WHT": "White",
    "WHITE": "White",
    "PAL": "Palomino",
    "DUN": "Dun",
    "B/BR": "Bay or Brown",
    "BBR": "Bay or Brown",
    "BAYORBROWN": "Bay or Brown",
    "BAY OR BROWN": "Bay or Brown",
    "DKB": "Dark Bay",
    "DK B": "Dark Bay",
    "DARK BAY": "Dark Bay",
    "DKBAY": "Dark Bay",
    "DKB/BR": "Dark Bay or Brown",
    "DKBBR": "Dark Bay or Brown",
    "DK B/BR": "Dark Bay or Brown",
    "DARK BAY OR BROWN": "Dark Bay or Brown",
    "GR/RO": "Grey or Roan",
    "GRRO": "Grey or Roan",
    "GREY OR ROAN": "Grey or Roan",
    "BL/BR": "Black or Brown",
    "BLBR": "Black or Brown",
    "CH/RO": "Chestnut or Roan",
    "CHRO": "Chestnut or Roan",
    "DKBR": "Dark Brown",
    "DARKBROWN": "Dark Brown",
    "DKCH": "Dark Chestnut",
    "LTB": "Light Bay",
}

#: Colours written as several tokens.  Kept separate from COLOUR_NAMES (which
#: strips whitespace) so that the descriptor walk cannot read an adjacent sex
#: token as part of a colour -- "B R" is bay + ridgling, not "BR" = brown.
MULTI_TOKEN_COLOURS = {
    "DARK BAY OR BROWN": "Dark Bay or Brown",
    "DK BAY OR BROWN": "Dark Bay or Brown",
    "DARK BAY/BROWN": "Dark Bay or Brown",
    "DK B/BR": "Dark Bay or Brown",
    "BAY OR BROWN": "Bay or Brown",
    "GREY OR ROAN": "Grey or Roan",
    "GRAY OR ROAN": "Grey or Roan",
    "BLACK OR BROWN": "Black or Brown",
    "CHESTNUT OR ROAN": "Chestnut or Roan",
    "DARK BAY": "Dark Bay",
    "DK B": "Dark Bay",
    "DARK BROWN": "Dark Brown",
    "DK BR": "Dark Brown",
    "DARK CHESTNUT": "Dark Chestnut",
    "DK CH": "Dark Chestnut",
    "LIGHT BAY": "Light Bay",
}

#: Longest multi-token colour, so the descriptor walk knows how far to look back.
_MAX_COLOUR_TOKENS = max(len(key.split(" ")) for key in MULTI_TOKEN_COLOURS)


def _multi_token_colour(tokens) -> Optional[str]:
    """Strict multi-word colour lookup; whitespace between tokens is significant."""
    key = " ".join(tokens).upper().replace(".", "")
    key = re.sub(r"\s*/\s*", "/", key)
    key = _WS_RUN.sub(" ", key).strip()
    return MULTI_TOKEN_COLOURS.get(key)

#: Normalized token -> single-letter sex code in the style of the reference CSV.
SEX_CODES = {
    "H": "H", "HORSE": "H", "STALLION": "H", "ST": "H", "S": "H", "ENTIRE": "H",
    "M": "M", "MARE": "M",
    "G": "G", "GELDING": "G", "GELD": "G",
    "C": "C", "COLT": "C",
    "F": "F", "FILLY": "F", "FILLIES": "F",
    "R": "R", "RIG": "R", "RIDGLING": "R", "RIDGELING": "R", "RIDGLIN": "R",
}


def _norm_token(token: str) -> str:
    return re.sub(r"[.\s]", "", token).upper()


def sex_code(text) -> Optional[str]:
    """Single-letter sex code, or None."""
    value = _clean_or_none(text)
    if value is None:
        return None
    return SEX_CODES.get(_norm_token(value))


def colour_name(text) -> Optional[str]:
    """Expanded colour name (``B`` -> ``Bay``), or None."""
    value = _clean_or_none(text)
    if value is None:
        return None
    return COLOUR_NAMES.get(_norm_token(value)) or COLOUR_NAMES.get(value.upper())


_COUNTRY_SUFFIX = re.compile(r"\(\s*([A-Za-z]{2,3})\s*\)")
_AGE_TOKEN = re.compile(r"^(\d{1,2})(?:YO|Y/O|YRS?|Y)?$")


def _age_from_token(token: str) -> Optional[int]:
    match = _AGE_TOKEN.match(_norm_token(token))
    if not match:
        return None
    age = int(match.group(1))
    return age if 1 <= age <= 30 else None


def parse_horse_descriptor(text) -> dict:
    """Split an IFHA horse string into its parts.  Never raises.

    Handles ``"5 B H"``, ``"3 Ch F"``, ``"4 B/Br G"``, ``"Enable (GB) 5 B M"``,
    all-caps input, non-breaking spaces, and varying token order.

    Returns ``{"name", "country_suffix", "age", "colour", "sex"}`` with None for
    anything that could not be determined.
    """
    result = {"name": None, "country_suffix": None, "age": None,
              "colour": None, "sex": None}

    value = _clean_or_none(text)
    if value is None:
        return result

    # "(GB)" etc. may sit anywhere; pull it out before tokenizing.
    suffix_match = _COUNTRY_SUFFIX.search(value)
    if suffix_match:
        result["country_suffix"] = suffix_match.group(1).upper()
        value = (value[: suffix_match.start()] + " " + value[suffix_match.end():])

    # Tighten "B / Br" and "4yo" so they tokenize as single units.
    value = re.sub(r"\s*/\s*", "/", value)
    value = re.sub(r"(?<=\d)\s*(?:y\.?o\.?|yrs?\.?|y/o)\b", "", value, flags=re.I)
    value = _WS_RUN.sub(" ", value).strip()
    if not value:
        return result

    tokens = value.split(" ")

    # The descriptor (age / colour / sex) is a trailing run of tokens. Walk
    # backwards consuming anything classifiable; stop at the first token that
    # isn't, which marks the end of the horse's name.
    index = len(tokens)
    while index > 0:
        consumed = False

        if result["colour"] is None:
            # Longest multi-word colour first ("Dark Bay or Brown" before "Dark Bay").
            for width in range(min(_MAX_COLOUR_TOKENS, index), 1, -1):
                found = _multi_token_colour(tokens[index - width:index])
                if found:
                    result["colour"] = found
                    index -= width
                    consumed = True
                    break

        if not consumed:
            token = tokens[index - 1]
            if result["age"] is None and _age_from_token(token) is not None:
                result["age"] = _age_from_token(token)
                index -= 1
                consumed = True
            elif result["sex"] is None and sex_code(token):
                result["sex"] = sex_code(token)
                index -= 1
                consumed = True
            elif result["colour"] is None and colour_name(token):
                result["colour"] = colour_name(token)
                index -= 1
                consumed = True

        if not consumed:
            break

    # Guard against eating a real name: "Winter Grey" with no age/sex present is
    # a name, not a colour.  Only trust a lone colour if nothing precedes it.
    if (result["colour"] is not None and result["age"] is None
            and result["sex"] is None and index > 0):
        result["colour"] = None
        index = len(tokens)

    name = " ".join(tokens[:index]).strip()
    result["name"] = _clean_or_none(name)
    return result


# ---------------------------------------------------------------------------
# Foaling year
# ---------------------------------------------------------------------------

class Foaling(NamedTuple):
    year: Optional[int]
    short: Optional[str]   # "20", "05"

    def __str__(self) -> str:
        return str(self.year) if self.year is not None else NOT_AVAILABLE


def foaling_year(race_year, horse_age) -> Foaling:
    """``race_year - horse_age`` plus its 2-digit form (2005 -> ``"05"``).

    Southern Hemisphere caveat: SH foals are born Aug-Dec and are aged from
    1 August, so for a race run in the first half of a NH calendar year an
    AUS/NZ/SAF/ARG/BRZ/CHI/URU/PER horse can come out one year off here.  IFHA
    reports the local official age, so we do not try to correct for it.
    """
    if isinstance(race_year, bool) or isinstance(horse_age, bool):
        return Foaling(None, None)
    try:
        year_int = int(str(race_year).strip()[:4]) if isinstance(race_year, str) else int(race_year)
        age_int = int(horse_age)
    except (TypeError, ValueError, OverflowError):
        return Foaling(None, None)
    if not (1700 <= year_int <= 2200) or not (0 <= age_int <= 40):
        return Foaling(None, None)

    foaled = year_int - age_int
    return Foaling(foaled, f"{foaled % 100:02d}")


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

class DateParts(NamedTuple):
    iso: str        # "2025-09-27"
    display: str    # "27 September 2025"

    def __str__(self) -> str:
        return self.iso


_MONTHS = {
    "JAN": 1, "JANUARY": 1, "JANV": 1,
    "FEB": 2, "FEBRUARY": 2, "FEBR": 2, "FEV": 2,
    "MAR": 3, "MARCH": 3, "MARS": 3, "MRZ": 3,
    "APR": 4, "APRIL": 4, "AVR": 4, "APL": 4,
    "MAY": 5, "MAI": 5, "MAG": 5,
    "JUN": 6, "JUNE": 6, "JUIN": 6, "GIU": 6,
    "JUL": 7, "JULY": 7, "JUIL": 7, "LUG": 7,
    "AUG": 8, "AUGUST": 8, "AOU": 8, "AGO": 8,
    "SEP": 9, "SEPT": 9, "SEPTEMBER": 9, "SET": 9,
    "OCT": 10, "OCTOBER": 10, "OKT": 10, "OTT": 10,
    "NOV": 11, "NOVEMBER": 11,
    "DEC": 12, "DECEMBER": 12, "DEZ": 12, "DIC": 12, "DIC.": 12,
}
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

_ORDINAL = re.compile(r"(?<=\d)(st|nd|rd|th)\b", re.I)
_ISO_LIKE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_NUMERIC = re.compile(r"^(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})$")
_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DAY_MONTH_YEAR = re.compile(r"^(\d{1,2})\s+([A-Za-zÀ-ÿ.]+)\s+(\d{2,4})$")
_MONTH_DAY_YEAR = re.compile(r"^([A-Za-zÀ-ÿ.]+)\s+(\d{1,2})\s+(\d{2,4})$")
_MONTH_YEAR_ONLY = re.compile(r"^([A-Za-zÀ-ÿ.]+)\s+(\d{4})$")


def _month_number(token: str) -> Optional[int]:
    key = re.sub(r"[^A-Z]", "", token.upper())
    if not key:
        return None
    if key in _MONTHS:
        return _MONTHS[key]
    for name, number in _MONTHS.items():
        if name.startswith(key) and len(key) >= 3:
            return number
    return None


def _expand_year(year: int) -> int:
    if year >= 100:
        return year
    # 2-digit years: racing data here is 2003-2026, so <= 70 is 20xx.
    return 2000 + year if year <= 70 else 1900 + year


def _build(year: Optional[int], month: Optional[int], day: Optional[int]) -> Optional[DateParts]:
    if not year or not month or not day:
        return None
    if not (1 <= month <= 12) or not (1 <= day <= _DAYS_IN_MONTH[month - 1]):
        return None
    if month == 2 and day == 29 and not (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return None
    if not (1700 <= year <= 2200):
        return None
    return DateParts(
        f"{year:04d}-{month:02d}-{day:02d}",
        f"{day:02d} {_MONTH_NAMES[month - 1]} {year:04d}",
    )


def normalize_date(text, dayfirst: bool = True) -> Optional[DateParts]:
    """Parse almost any date spelling into ISO + ``27 September 2025`` display.

    ``dayfirst`` only matters for fully ambiguous all-numeric dates such as
    ``12/05/2015``.  It defaults to True because IFHA is an international
    (day-first) source; pass ``dayfirst=False`` for US-sourced feeds.
    Returns None if the text cannot be parsed.
    """
    value = _clean_or_none(text)
    if value is None:
        return None

    value = _ORDINAL.sub("", value)
    value = re.sub(r"^[A-Za-z]{3,9},\s*", "", value)      # "Saturday, 27 Sept 2025"
    value = re.sub(r"\s*\d{1,2}:\d{2}(:\d{2})?.*$", "", value)  # trailing time
    value = value.replace(",", " ")
    value = _WS_RUN.sub(" ", value).strip()
    if not value:
        return None

    match = _COMPACT.match(value)
    if match:
        return _build(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    match = _ISO_LIKE.match(value)
    if match:
        return _build(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    match = _NUMERIC.match(value)
    if match:
        a, b, c = (int(g) for g in match.groups())
        if c >= 1000 or len(match.group(3)) > 2:   # d/m/yyyy or m/d/yyyy
            candidates = [(c, b, a), (c, a, b)] if dayfirst else [(c, a, b), (c, b, a)]
        else:                                      # d/m/yy or m/d/yy
            candidates = (
                [(_expand_year(c), b, a), (_expand_year(c), a, b)]
                if dayfirst else
                [(_expand_year(c), a, b), (_expand_year(c), b, a)]
            )
        for year, month, day in candidates:
            built = _build(year, month, day)
            if built:
                return built
        return None

    match = _DAY_MONTH_YEAR.match(value)
    if match:
        month = _month_number(match.group(2))
        if month:
            return _build(_expand_year(int(match.group(3))), month, int(match.group(1)))

    match = _MONTH_DAY_YEAR.match(value)
    if match:
        month = _month_number(match.group(1))
        if month:
            return _build(_expand_year(int(match.group(3))), month, int(match.group(2)))

    # "27 September" with no year, or "September 2025" -- not enough to be safe.
    if _MONTH_YEAR_ONLY.match(value):
        return None
    return None


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

class Track(NamedTuple):
    name: str                  # cleaned full name
    code: str                  # short code, or the full name if unknown
    is_known: bool             # True when a real code was found

    def __str__(self) -> str:
        return self.code


#: North American tracks only.  Keys are lowercase canonical names; aliases are
#: folded in by :func:`_track_key`.  International tracks are intentionally
#: absent -- there is no accepted short-code standard for them, so they pass
#: through as full names rather than getting invented codes.
TRACK_CODES = {
    # New York
    "aqueduct": "AQU",
    "belmont at the big a": "BAQ",
    "belmont park": "BEL",
    "saratoga": "SAR",
    "finger lakes": "FL",
    # Kentucky
    "churchill downs": "CD",
    "keeneland": "KEE",
    "kentucky downs": "KD",
    "turfway park": "TP",
    "ellis park": "ELP",
    # Mid-Atlantic
    "laurel park": "LRL",
    "pimlico": "PIM",
    "timonium": "TIM",
    "delaware park": "DEL",
    "parx racing": "PRX",
    "philadelphia park": "PHA",
    "penn national": "PEN",
    "presque isle downs": "PID",
    "monmouth park": "MTH",
    "meadowlands": "MED",
    "atlantic city": "ATL",
    "colonial downs": "CNL",
    "great meadow": "GRM",
    "charles town": "CT",
    "mountaineer": "MNR",
    # Florida / Southeast
    "gulfstream park": "GP",
    "gulfstream park west": "GPW",
    "calder": "CRC",
    "hialeah park": "HIA",
    "tampa bay downs": "TAM",
    # Gulf / South Central
    "fair grounds": "FG",
    "louisiana downs": "LAD",
    "evangeline downs": "EVD",
    "delta downs": "DED",
    "oaklawn park": "OP",
    "lone star park": "LS",
    "sam houston race park": "HOU",
    "retama park": "RET",
    "remington park": "RP",
    "will rogers downs": "WRD",
    "fair meadows": "FMT",
    # Midwest
    "arlington park": "AP",
    "hawthorne": "HAW",
    "fairmount park": "FP",
    "indiana grand": "IND",
    "horseshoe indianapolis": "IND",
    "ellis": "ELP",
    "thistledown": "TDN",
    "mahoning valley": "MVR",
    "belterra park": "BTP",
    "river downs": "RD",
    "prairie meadows": "PRM",
    "canterbury park": "CBY",
    "fonner park": "FON",
    "columbus": "CLS",
    "horsemens park": "HPO",
    # Mountain / Southwest
    "arapahoe park": "ARP",
    "sunland park": "SUN",
    "zia park": "ZIA",
    "ruidoso downs": "RUI",
    "albuquerque": "ALB",
    "sunray park": "SRP",
    "turf paradise": "TUP",
    "rillito park": "RIL",
    # California / Northwest
    "santa anita park": "SA",
    "del mar": "DMR",
    "hollywood park": "HOL",
    "golden gate fields": "GG",
    "los alamitos": "LRC",
    "bay meadows": "BM",
    "pleasanton": "PLN",
    "santa rosa": "SR",
    "sacramento": "SAC",
    "stockton": "STK",
    "fresno": "FNO",
    "ferndale": "FER",
    "emerald downs": "EMD",
    "portland meadows": "PM",
    "grants pass": "GRP",
    # New England
    "suffolk downs": "SUF",
    "rockingham park": "RKM",
    # Canada
    "woodbine": "WO",
    "fort erie": "FE",
    "hastings racecourse": "HST",
    "assiniboia downs": "ASD",
    "northlands park": "NP",
    "century mile": "CTM",
    "century downs": "CTD",
    "marquis downs": "MD",
    "ajax downs": "AJX",
}

#: Spellings IFHA / Equibase / chart callers use for the same track.
TRACK_ALIASES = {
    "churchill": "churchill downs",
    "churchill downs racetrack": "churchill downs",
    "saratoga race course": "saratoga",
    "saratoga racecourse": "saratoga",
    "saratoga springs": "saratoga",
    "belmont": "belmont park",
    "the big a": "belmont at the big a",
    "aqueduct racetrack": "aqueduct",
    "big a": "belmont at the big a",
    "santa anita": "santa anita park",
    "del mar thoroughbred club": "del mar",
    "delmar": "del mar",
    "keeneland race course": "keeneland",
    "kentucky downs racecourse": "kentucky downs",
    "oaklawn": "oaklawn park",
    "gulfstream": "gulfstream park",
    "laurel": "laurel park",
    "pimlico race course": "pimlico",
    "parx": "parx racing",
    "monmouth": "monmouth park",
    "arlington international": "arlington park",
    "arlington international racecourse": "arlington park",
    "arlington": "arlington park",
    "woodbine racetrack": "woodbine",
    "los alamitos race course": "los alamitos",
    "lone star": "lone star park",
    "sam houston": "sam houston race park",
    "fair grounds race course": "fair grounds",
    "colonial": "colonial downs",
    "turfway": "turfway park",
    "indiana downs": "indiana grand",
    "hoosier park": "indiana grand",
    "calder race course": "calder",
    "hialeah": "hialeah park",
    "golden gate": "golden gate fields",
    "hastings park": "hastings racecourse",
    "horsemen's park": "horsemens park",
}

_TRACK_NOISE = re.compile(
    r"\b(racetrack|race track|racecourse|race course|racing|raceway|"
    r"thoroughbred club|turf club|downs racetrack)\b"
)


def _track_key(name: str) -> str:
    key = name.lower()
    key = re.sub(r"\(.*?\)", " ", key)                 # drop "(USA)" / "(inner)"
    key = key.replace("&", "and")
    key = re.sub(r"[.'’`]", "", key)
    key = re.sub(r"[^a-z0-9 ]", " ", key)
    key = _WS_RUN.sub(" ", key).strip()
    key = re.sub(r"^the\s+", "", key)
    stripped = _WS_RUN.sub(" ", _TRACK_NOISE.sub(" ", key)).strip()
    # Only use the noise-stripped form if it still names something.
    return stripped if stripped else key


def _resolve_track(raw) -> Track:
    name = _clean_or_none(raw)
    if name is None:
        return Track(NOT_AVAILABLE, NOT_AVAILABLE, False)

    for key in (_track_key(name), _WS_RUN.sub(" ", re.sub(r"[^a-z0-9 ]", " ", name.lower())).strip()):
        if not key:
            continue
        key = TRACK_ALIASES.get(key, key)
        if key in TRACK_CODES:
            return Track(name, TRACK_CODES[key], True)
        # Already a code? ("CD", "SAR")
        upper = name.upper()
        if upper in set(TRACK_CODES.values()):
            return Track(name, upper, True)

    return Track(name, name, False)


def track_info(raw) -> Track:
    """``Track(name, code, is_known)``."""
    return _resolve_track(raw)


def track_name(raw) -> str:
    """Cleaned full track name."""
    return _resolve_track(raw).name


def track_code(raw) -> str:
    """Short code for known North American tracks, else the full name unchanged."""
    return _resolve_track(raw).code
