#!/usr/bin/env python3
"""Parse cached IFHA ``area=20`` race-result pages into one record per finisher.

Reads only the on-disk cache written by :mod:`agent1_fetch` -- never the
network -- so it can run while a fetch is still in progress. Years that are
not yet cached are skipped with a warning.

Every normalization (metres/furlongs, local currency -> USD, colour and sex
expansion, date standardization, text scrubbing, track codes) is delegated to
:mod:`normalize`. The handful of IFHA-specific codes that module does not yet
know about are patched in via the small adapter tables below; see
``NORMALIZE_GAPS`` for the list.

Usage:
    python3 agent2_parse.py --years 2015
    python3 agent2_parse.py --years 2003-2026 --out parsed_records.jsonl

Downstream:
    from agent2_parse import parse_all
    records, issues = parse_all([2015])
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence

from bs4 import BeautifulSoup

import normalize as N
from agent1_fetch import (
    DETAIL_URL,
    HtmlCache,
    IfhaFetcher,
    LISTING_URL,
    cache_key,
    iter_race_details,
    listing_payload,
    parse_years,
)

ROOT = Path(__file__).resolve().parent
RECORDS_PATH = ROOT / "parsed_records.jsonl"
ISSUES_PATH = ROOT / "parse_issues.jsonl"
SUMMARY_PATH = ROOT / "parse_summary.json"

NA = N.NOT_AVAILABLE  # "N/A"


# --------------------------------------------------------------------------- #
# adapters for things normalize.py does not cover (report these upstream)
# --------------------------------------------------------------------------- #

#: Equibase-style colour codes IFHA emits that ``normalize.colour_name`` misses.
#: ``DK B/`` alone is 649 of 4,796 finisher rows in 2015.
EXTRA_COLOUR_NAMES = {
    "DK B/": "Dark Bay or Brown",
    "DKB/": "Dark Bay or Brown",
    "GR/B": "Grey or Black",
    "BR/BL": "Brown or Black",
    "B/GR": "Bay or Grey",
}
# Still unmapped on purpose: the bare codes "DK" and "R" appear a handful of
# times in 2003-2007 and are truncated beyond recovery ("DK" could be Dark
# Bay / Dark Brown / Dark Chestnut). The raw code is kept in
# ``horse_colour_code`` and a ``colour_unmapped`` issue is logged.

#: IFHA country codes ``normalize.currency_for`` does not resolve.
EXTRA_JURISDICTION_CURRENCY = {
    "KOA": "KRW",  # IFHA's code for the Republic of Korea
}

#: Full country name on the detail page -> the IFHA code the listing uses.
#: Only needed when a race is parsed without its listing row (e.g. parse_one).
COUNTRY_NAME_TO_CODE = {
    "ARGENTINA": "ARG", "AUSTRALIA": "AUS", "BAHRAIN": "BHR", "BRAZIL": "BRZ",
    "CANADA": "CAN", "CHILE": "CHI", "DENMARK": "DEN", "FRANCE": "FR",
    "GERMANY": "GER", "GREAT BRITAIN": "ENG", "HONG KONG": "HK",
    "IRELAND": "IRE", "ITALY": "ITY", "JAPAN": "JPN", "NEW ZEALAND": "NZ",
    "NORWAY": "NOR", "PERU": "PER", "REPUBLIC OF KOREA": "KOA",
    "SOUTH KOREA": "KOA", "KOREA": "KOA", "SAUDI ARABIA": "KSA",
    "SINGAPORE": "SIN", "SOUTH AFRICA": "SAF", "SWEDEN": "SWE",
    "TURKEY": "TUR", "UNITED ARAB EMIRATES": "UAE", "URUGUAY": "URU",
    "UNITED STATES": "USA", "UNITED STATES OF AMERICA": "USA",
}

#: Symbols that identify exactly one currency. These BEAT the race's country,
#: because IFHA sometimes cards a race in a currency other than the host
#: country's: the three Turkish internationals are printed in euros.
UNAMBIGUOUS_SYMBOL_CURRENCY = {
    "\u20ac": "EUR", "\u00a3": "GBP", "\u00a5": "JPY",
    "$A": "AUD", "CN$": "CAD", "HK$": "HKD", "NZ$": "NZD", "S$": "SGD",
    "$U": "UYU", "S/": "PEN",
    "AED": "AED", "SEK": "SEK", "NOK": "NOK", "DKK": "DKK",
    "TL": "TRY", "BD": "BHD", "SR": "SAR",
}

#: Symbols shared by several jurisdictions, so the country has to decide:
#: "$" is USA/UAE, "R" is Brazil (R$) and South Africa, "Ps" is Argentina
#: (peso) and Chile (peso).
AMBIGUOUS_SYMBOLS = {"$", "R", "PS"}

NORMALIZE_GAPS = [
    "colour_name() does not know the Equibase codes 'DK B/' (649 of 4,796 "
    "2015 rows), 'GR/B', 'BR/BL', 'B/GR'",
    "currency_for() does not know IFHA's Korea code 'KOA'",
    "currency_for() cannot resolve a bare currency SYMBOL ('\u20ac', '\u00a3', "
    "'\u00a5', '$A', 'HK$', 'S/', '$U', 'Ps', 'CN$'), only codes and country names",
    "no furlongs_to_metres() inverse of metres_to_furlongs()",
    "parse_horse_descriptor() reads the leading 2 digits as AGE; on IFHA they "
    "are the 2-digit YEAR OF BIRTH, and it also whitespace-tokenizes a "
    "fixed-width field",
    "no helper to turn a 2-digit year of birth into a full year / age",
]


def colour_name(code: str):
    """``normalize.colour_name`` plus the IFHA/Equibase codes it is missing."""
    expanded = N.colour_name(code)
    if expanded:
        return expanded
    key = re.sub(r"\s+", " ", (code or "")).strip().upper()
    return EXTRA_COLOUR_NAMES.get(key) or EXTRA_COLOUR_NAMES.get(key.replace(" ", ""))


def resolve_currency(symbol, country_code, country_name) -> str | None:
    """Decide the purse currency from the printed symbol and the host country.

    An unambiguous symbol wins; otherwise the country decides. Falls back to
    ``normalize.currency_for`` for anything else.
    """
    key = (symbol or "").strip().upper()
    if key and key not in AMBIGUOUS_SYMBOLS:
        for candidate in (symbol, key):
            if candidate in UNAMBIGUOUS_SYMBOL_CURRENCY:
                return UNAMBIGUOUS_SYMBOL_CURRENCY[candidate]

    for candidate in (country_code, country_name):
        if not candidate or candidate == NA:
            continue
        code = N.currency_for(candidate)
        if code:
            return code
        upper = str(candidate).strip().upper()
        if upper in EXTRA_JURISDICTION_CURRENCY:
            return EXTRA_JURISDICTION_CURRENCY[upper]
    return N.currency_for(symbol) if symbol else None


def furlongs_to_metres(furlongs: float) -> float:
    """Inverse of ``normalize.metres_to_furlongs``; not provided by normalize."""
    return float(furlongs) * N.FURLONG_METRES


def foaling_from_two_digit_yob(yob2: str, race_year: int | None):
    """Expand a 2-digit year of birth and derive the horse's age.

    IFHA prints the horse's year of birth, not its age (the site's own help
    text is wrong about this). Century pivot: assume 20xx unless that would
    put the foaling year after the race, in which case 19xx.

    Returns ``(foaling_year, age)``, either of which may be None.
    """
    if not yob2 or not yob2.isdigit() or len(yob2) != 2:
        return None, None
    two = int(yob2)
    if race_year is None:
        return None, None
    foaled = 2000 + two
    if foaled > race_year:
        foaled = 1900 + two
    age = race_year - foaled
    if not (0 <= age <= 30):
        return foaled, None
    return foaled, age


# --------------------------------------------------------------------------- #
# cache-only fetcher
# --------------------------------------------------------------------------- #

CACHE_MISS = ""  # an empty string can never be a real page


class CacheOnlyFetcher(IfhaFetcher):
    """An :class:`IfhaFetcher` that reads the cache and never hits the network.

    A miss returns ``CACHE_MISS`` instead of raising so that one uncached page
    cannot abort a whole run.
    """

    def __init__(self, cache_dir: Path | None = None):
        super().__init__(concurrency=1, delay=0.0,
                         cache_dir=cache_dir or (ROOT / "cache"))
        self.missed: list[str] = []

    async def fetch(self, method: str, url: str, data: dict | None = None) -> str:
        html = self.cache.get(cache_key(method, url, data))
        if html is None:
            self.missed.append(url)
            return CACHE_MISS
        self.stats.cache_hits += 1
        return html

    def is_cached(self, method: str, url: str, data: dict | None = None) -> bool:
        return self.cache.path_for(cache_key(method, url, data)).is_file()

    def listing_cached(self, year: int) -> bool:
        return self.is_cached("POST", LISTING_URL, listing_payload(year, ""))


def detail_url(pid: str) -> str:
    return DETAIL_URL.format(pid=pid)


# --------------------------------------------------------------------------- #
# detail-page parsing
# --------------------------------------------------------------------------- #

BEGIN_MARK = "BEGIN RACE DATA HERE"
END_MARK = "END RACE DATA"

GROUP_RE = re.compile(r"\bGroup\s*([123])\b", re.I)
# "HAR Hipodromo Argentino De Palermo - Argentina", and the SIN/SWE/URU shape
# "SIN Singapore -" where the country name is simply absent.
TRACK_RE = re.compile(
    r"^(?P<code>[A-Za-z0-9&'.\-]{1,6})\s+(?P<name>.+?)\s+-\s*(?P<country>.*)$"
)
DIST_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>Meters|Metres|Furlongs|Yards)", re.I)
SURFACE_RE = re.compile(r"\bon the\b\s*(?P<surface>.*)$", re.I)
SITE_USD_RE = re.compile(r"\(\s*\*?\s*\$\s*(?P<usd>[\d.,]+)\s*\)")
LOCAL_PURSE_RE = re.compile(r"^(?P<symbol>[^\d]*?)\s*(?P<amount>\d[\d.,\s]*?)\s*$")
# Fixed width: 2-digit YOB, one space, 6-char colour field (may be blank or
# contain spaces), 1-char sex. NEVER whitespace-split this.
DESC_RE = re.compile(r"^(?P<yob>\d{2})\s(?P<colour>.{6})(?P<sex>[A-Za-z])$")
DESC_LOOSE_RE = re.compile(r"^(?P<yob>\d{2})\s+(?P<colour>.*?)\s*(?P<sex>[A-Za-z])$")
HORSE_RE = re.compile(r"^(?P<name>.*?)\s*\(\s*(?P<cc>[A-Za-z]{2,4})\s*\)\s*,?\s*$")

POSITIONS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}


def race_data_block(html: str) -> str | None:
    """Slice the page between the BEGIN/END RACE DATA comments.

    Future-dated races return HTTP 200 with the whole block absent, so a
    None return is expected and not an error.
    """
    start = html.find(BEGIN_MARK)
    if start < 0:
        return None
    end = html.find(END_MARK, start)
    if end < 0:
        return None
    block = html[start + len(BEGIN_MARK):end]
    return block if "resultsInfo" in block or "resultsPosition" in block else None


def _br_lines(tag) -> list[str]:
    """Split a tag's rendered text on its ``<br>`` children.

    The header cell is one <td> whose six logical fields are separated only by
    <BR>, so get_text() alone would run them together.
    """
    lines, current = [], []
    for node in tag.descendants:
        name = getattr(node, "name", None)
        if name == "br":
            lines.append("".join(current))
            current = []
        elif name is None:  # NavigableString
            current.append(str(node))
    lines.append("".join(current))
    return [re.sub(r"\s+", " ", ln.replace("\xa0", " ")).strip() for ln in lines]


def parse_header(block_soup) -> dict:
    """Pull the six header fields out of the ``resultsInfo`` cell.

    Classification is by pattern rather than position: the order is stable in
    every sample, but old records drop fields (e.g. a blank distance line),
    which would shift a positional reader.
    """
    out = {
        "race_name": None, "group_label": None, "group": None,
        "purse_raw": None, "date_raw": None, "track_raw": None,
        "distance_raw": None, "header_found": False,
    }
    cell = block_soup.find(attrs={"class": "resultsInfo"})
    if cell is None:
        return out
    out["header_found"] = True

    # Pull the name and group out of their own tags and remove them, so the
    # remaining <BR>-separated lines are only purse / date / track / distance.
    # Some GB race names contain digits ("(Class 1)"), which would otherwise
    # be misread as the purse line.
    span = cell.find("span", class_="Heleven")
    if span is not None:
        out["race_name"] = span.get_text(" ", strip=True)
        span.extract()
    bold = cell.find("b")
    if bold is not None:
        label = bold.get_text(" ", strip=True)
        match = GROUP_RE.search(label)
        if match:
            out["group_label"] = label
            out["group"] = f"G{match.group(1)}"
            bold.extract()

    for line in _br_lines(cell):
        if not line:
            continue
        if out["distance_raw"] is None and (DIST_RE.search(line) or SURFACE_RE.search(line)):
            out["distance_raw"] = line
            continue
        if out["date_raw"] is None and N.normalize_date(line) is not None:
            out["date_raw"] = line
            continue
        if out["track_raw"] is None and TRACK_RE.match(line):
            out["track_raw"] = line
            continue
        if out["purse_raw"] is None and any(ch.isdigit() for ch in line):
            out["purse_raw"] = line
    return out


def parse_finisher_cells(block_soup) -> list[tuple[str, str, str, str]]:
    """Return ``(label, horse_html_name, descriptor, jockey)`` per finisher row.

    Row count is 0, 3 or 4 in practice (two 2015 dead heats produce 4), so it
    is never assumed.
    """
    rows = []
    for label_cell in block_soup.find_all(attrs={"class": "resultsPosition"}):
        tr = label_cell.find_parent("tr")
        if tr is None:
            continue
        cells = tr.find_all("td")
        try:
            idx = cells.index(label_cell)
        except ValueError:
            idx = 0
        horse_cell = cells[idx + 1] if len(cells) > idx + 1 else None
        jockey_cell = cells[idx + 2] if len(cells) > idx + 2 else None

        label = label_cell.get_text(" ", strip=True).replace("\xa0", " ").strip(": ")
        name_raw, descriptor = "", ""
        if horse_cell is not None:
            bold = horse_cell.find("b")
            if bold is not None:
                name_raw = bold.get_text(" ", strip=True)
                descriptor = "".join(
                    node if isinstance(node, str) else node.get_text()
                    for node in bold.next_siblings
                )
            else:
                name_raw = horse_cell.get_text(" ", strip=True)
        jockey = jockey_cell.get_text(" ", strip=True) if jockey_cell is not None else ""
        rows.append((label, name_raw, descriptor, jockey))
    return rows


def split_descriptor(raw: str) -> tuple[dict, str | None]:
    """Fixed-width split of ``"11 DK B/ H"`` into YOB / colour / sex.

    Returns ``(parts, problem)``. Colour may legitimately be empty.
    """
    text = (raw or "").replace("\xa0", " ").replace("&nbsp;", " ")
    text = text.strip("\r\n\t ")
    if not text:
        return {"yob2": None, "colour_code": None, "sex_code": None}, "descriptor_empty"

    match = DESC_RE.match(text)
    problem = None
    if match is None:
        match = DESC_LOOSE_RE.match(text)
        problem = "descriptor_not_fixed_width"
    if match is None:
        return {"yob2": None, "colour_code": None, "sex_code": None}, "descriptor_malformed"

    return (
        {
            "yob2": match.group("yob"),
            "colour_code": match.group("colour").strip() or None,
            "sex_code": match.group("sex").upper(),
        },
        problem,
    )


def split_horse_name(raw: str) -> tuple[str | None, str | None]:
    """``"Liberal (PER), "`` -> ``("Liberal", "PER")``; no suffix -> ``(name, None)``."""
    text = (raw or "").replace("\xa0", " ").strip()
    match = HORSE_RE.match(text)
    if match:
        return N._clean_or_none(match.group("name")), match.group("cc").upper()
    return N._clean_or_none(text), None


# --------------------------------------------------------------------------- #
# record construction
# --------------------------------------------------------------------------- #


def _na(value):
    """Coerce None / blank to the literal string ``"N/A"`` the user asked for."""
    if value is None:
        return NA
    if isinstance(value, str):
        text = value.strip()
        return text if text else NA
    return value


def _round(value, digits=2):
    return None if value is None else round(float(value), digits)


class IssueLog:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, racepid, issue: str, detail: str = "") -> None:
        self.items.append({"racepid": str(racepid), "issue": issue,
                           "detail": str(detail)[:300]})

    def counts(self) -> dict[str, int]:
        return dict(collections.Counter(i["issue"] for i in self.items))


def parse_race(meta: dict, html: str, issues: IssueLog) -> list[dict]:
    """Parse one cached detail page into one record per finisher.

    Races with no published result still produce a single row with ``N/A``
    finisher fields, so that every race survives into the output.
    """
    return [_finalize(r) for r in _parse_race_rows(meta, html, issues)]


def _finalize(record: dict) -> dict:
    """Drop the private keys used to pass race context to the finisher half."""
    for key in ("_race_year", "_country_code"):
        record.pop(key, None)
    return record


def _parse_race_rows(meta: dict, html: str, issues: IssueLog) -> list[dict]:
    pid = str(meta.get("racepid") or meta.get("pid") or "")

    if html == CACHE_MISS:
        issues.add(pid, "detail_not_cached", detail_url(pid))
        race = _race_fields(meta, {}, pid, issues, audit=False)
        return [{**race, **BLANK_FINISHER}]

    block = race_data_block(html)
    if block is None:
        issues.add(pid, "empty_race_data",
                   "no BEGIN/END RACE DATA block (expected for future-dated races)")
        race = _race_fields(meta, {}, pid, issues, audit=False)
        return [{**race, **BLANK_FINISHER}]

    soup = BeautifulSoup(block, "lxml")
    header = parse_header(soup)
    if not header["header_found"]:
        issues.add(pid, "header_block_missing", "no resultsInfo cell inside race-data block")

    finishers = parse_finisher_cells(soup)
    race = _race_fields(meta, header, pid, issues)
    race["n_finishers"] = len(finishers)

    if not finishers:
        issues.add(pid, "no_results_published", header.get("race_name") or "")
        return [{**race, **BLANK_FINISHER}]
    if len(finishers) != 3:
        issues.add(pid, "unexpected_finisher_count",
                   f"{len(finishers)} rows (3 is normal; 4 means a dead heat)")

    return [
        {**race, **_finisher_fields(fin, i, race, pid, issues)}
        for i, fin in enumerate(finishers)
    ]


def _race_fields(meta, header, pid, issues, audit: bool = True) -> dict:
    """Build the race-level half of a record.

    ``audit=False`` suppresses missing-field issues for pages that have no
    race-data block at all; their absence is already reported once.
    """
    header = header or {}
    cached = audit
    # iter_race_details merges the listing row into meta; "pid" is its marker.
    # Without it (e.g. parse_one) the listing-only fields are simply absent and
    # must not be reported as missing data.
    has_listing = "pid" in meta
    if audit and not has_listing and meta.get("kind") == "race_detail":
        issues.add(pid, "listing_row_missing", "pid not matched to a listing row")
    listing_country = (meta.get("country") or "").strip()
    listing_track = (meta.get("track") or "").strip()
    listing_distance = (meta.get("distance") or "").strip()
    listing_purse = (meta.get("purse") or "").strip()
    listing_agesex = (meta.get("agesex") or "").strip()

    # ---- race name / group ------------------------------------------------
    race_name = header.get("race_name") or meta.get("race")
    race_name = N._clean_or_none(race_name)
    if cached and not race_name:
        issues.add(pid, "missing_race_name", "")

    group = header.get("group")
    if not group:
        listing_group = (meta.get("group") or "").strip().upper()
        group = listing_group if re.fullmatch(r"G[123]", listing_group) else None
    if cached and not group:
        issues.add(pid, "missing_group", header.get("group_label") or "")

    # ---- date -------------------------------------------------------------
    date_text = header.get("date_raw") or meta.get("date")
    parsed_date = N.normalize_date(date_text)
    if parsed_date is None and date_text:
        parsed_date = N.normalize_date(meta.get("date"))
    race_year = None
    if parsed_date is not None:
        race_year = int(parsed_date.iso[:4])
    elif isinstance(meta.get("query_year"), int):
        race_year = meta["query_year"]
    if cached and parsed_date is None:
        issues.add(pid, "missing_date", str(date_text or ""))

    # ---- track / country --------------------------------------------------
    track_code = track_name = country_name = None
    match = TRACK_RE.match(header.get("track_raw") or "")
    if match:
        track_code = match.group("code").strip()
        track_name = N._clean_or_none(match.group("name"))
        country_name = N._clean_or_none(match.group("country"))
    if not track_code and listing_track:
        track_code = listing_track
    if cached and not track_name:
        issues.add(pid, "missing_track_name", header.get("track_raw") or "")
    if cached and not country_name:
        issues.add(pid, "missing_country_name", header.get("track_raw") or "")
    country_code = listing_country or None
    if not country_code and country_name:
        country_code = COUNTRY_NAME_TO_CODE.get(country_name.upper())
    if cached and not country_code:
        issues.add(pid, "missing_country", country_name or "")

    resolved = N.track_info(track_name) if track_name else None

    # ---- distance / surface ----------------------------------------------
    distance_value = distance_unit = None
    surface_raw = None
    dist_text = header.get("distance_raw") or ""
    match = DIST_RE.search(dist_text)
    if match:
        distance_value = float(match.group("value"))
        unit = match.group("unit").lower()
        distance_unit = {"meters": "Meters", "metres": "Meters",
                         "furlongs": "Furlongs", "yards": "Yards"}[unit]
    match = SURFACE_RE.search(dist_text)
    if match:
        surface_raw = N._clean_or_none(match.group("surface"))

    if distance_value is None and listing_distance:
        match = DIST_RE.search(listing_distance)
        if match:
            distance_value = float(match.group("value"))
            distance_unit = match.group("unit").title()
            issues.add(pid, "distance_from_listing", listing_distance)
    if cached and distance_value is None:
        issues.add(pid, "missing_distance", dist_text or listing_distance)

    metres = None
    if distance_value is not None:
        if distance_unit == "Meters":
            metres = distance_value
        elif distance_unit == "Furlongs":
            metres = furlongs_to_metres(distance_value)
        elif distance_unit == "Yards":
            metres = distance_value * 0.9144
    distance = N.metres_to_furlongs(metres)

    # Listing's (D)/(T) is authoritative; the detail text only adds AW/course.
    listing_surface = None
    match = re.search(r"\(([A-Za-z]{1,2})\)\s*$", listing_distance)
    if match:
        listing_surface = match.group(1)
    code_from_listing = N.surface_code(listing_surface) if listing_surface else NA
    code_from_detail = N.surface_code(surface_raw) if surface_raw else NA
    if code_from_detail == "AW":
        surface = "AW"
    elif code_from_listing != NA:
        surface = code_from_listing
    else:
        surface = code_from_detail
    if cached and surface == NA:
        issues.add(pid, "missing_surface", f"listing={listing_surface} detail={surface_raw}")

    # ---- purse ------------------------------------------------------------
    purse_raw = header.get("purse_raw") or listing_purse
    purse_local = purse_symbol = purse_usd_site = None
    if purse_raw:
        match = SITE_USD_RE.search(purse_raw)
        if match:
            purse_usd_site = N.parse_amount(match.group("usd"))
        local_part = SITE_USD_RE.sub("", purse_raw).strip()
        match = LOCAL_PURSE_RE.match(local_part)
        if match:
            purse_symbol = match.group("symbol").strip() or None
            purse_local = N.parse_amount(match.group("amount"))
        else:
            purse_local = N.parse_amount(local_part)

    currency = resolve_currency(purse_symbol, country_code, country_name)

    # IFHA mislabels some purses that are really in USD. Two giveaways:
    # its own USD conversion equals the "local" amount, or a bare "$" with no
    # conversion offered at all (the site only converts non-USD amounts).
    if currency and currency != "USD" and purse_local:
        if purse_usd_site and abs(purse_usd_site - purse_local) <= max(1.0, purse_local * 0.005):
            currency = "USD"
            if cached:
                issues.add(pid, "purse_local_is_usd",
                           f"{purse_raw!r}: site USD equals the {purse_symbol!r} amount")
        elif purse_symbol == "$" and purse_usd_site is None:
            currency = "USD"
            if cached:
                issues.add(pid, "purse_dollar_sign_assumed_usd",
                           f"{purse_raw!r} in {country_code}, no conversion offered")

    if cached and purse_local is None:
        issues.add(pid, "missing_purse", purse_raw or "")
    elif cached and purse_local == 0:
        issues.add(pid, "zero_purse", purse_raw or "")
    if cached and purse_local is not None and currency is None:
        issues.add(pid, "unknown_currency",
                   f"symbol={purse_symbol!r} country={country_code!r}/{country_name!r}")
    if cached and purse_usd_site is None and currency not in (None, "USD") and purse_local:
        issues.add(pid, "site_usd_missing", purse_raw or "")

    purse = N.purse_detail(purse_local, currency, race_year)
    usd_delta_pct = None
    if purse.usd and purse_usd_site:
        usd_delta_pct = round((purse_usd_site - purse.usd) / purse.usd * 100.0, 1)
        # A few percent is just annual-average vs race-day FX. An order of
        # magnitude means the local amount is mislabelled -- IFHA prints some
        # UAE purses as USD figures under an "AED" symbol.
        if cached and abs(usd_delta_pct) > 25:
            issues.add(pid, "purse_usd_disagrees",
                       f"site=${purse_usd_site:,.0f} vs normalized={purse.display} "
                       f"({usd_delta_pct:+.0f}%) raw={purse_raw!r}")

    # ---- eligibility conditions ------------------------------------------
    age_condition = sex_condition = None
    if listing_agesex:
        parts = [p.strip() for p in listing_agesex.split("|") if p.strip()]
        if parts:
            age_condition = parts[0]
        if len(parts) > 1:
            sex_condition = parts[1]
    if cached and has_listing and not age_condition:
        issues.add(pid, "missing_conditions", listing_agesex)

    record = {
        # ---- race ----
        "race_id": pid or NA,
        "racepid": pid or NA,
        "race_name": _na(race_name),
        "group": _na(group),
        "group_label": _na(header.get("group_label")),
        "date": _na(parsed_date.display if parsed_date else None),
        "date_iso": _na(parsed_date.iso if parsed_date else None),
        "race_year": _na(race_year),
        "country_code": _na(country_code),
        "country_name": _na(country_name),
        "track_code": _na(track_code),
        "track_name": _na(track_name),
        "track_code_normalized": _na(resolved.code if resolved else None),
        "distance_value": _na(_round(distance_value, 3)),
        "distance_unit": _na(distance_unit),
        "distance_metres": _na(_round(metres, 1)),
        "distance_furlongs": _na(distance.furlongs),
        "distance_display": _na(distance.display if distance.furlongs else None),
        "surface": _na(surface if surface != NA else None),
        "surface_raw": _na(surface_raw),
        "purse_raw": _na(purse_raw),
        "purse_local_amount": _na(_round(purse_local)),
        "purse_currency_symbol": _na(purse_symbol),
        "purse_currency": _na(currency),
        "purse_usd_site": _na(_round(purse_usd_site)),
        "purse_usd_normalized": _na(_round(purse.usd)),
        "purse_usd_display": _na(purse.display if purse.usd else None),
        "purse_usd_delta_pct": _na(usd_delta_pct),
        "fx_rate": _na(purse.rate),
        "fx_rate_year": _na(purse.rate_year),
        "fx_provenance": _na(purse.provenance),
        "age_condition": _na(age_condition),
        "sex_condition": _na(sex_condition),
        "n_finishers": 0,
        "has_results": False,
        "source_url": detail_url(pid) if pid else NA,
    }
    record["_race_year"] = race_year
    record["_country_code"] = country_code
    return record


#: Finisher half of a record for a race with no published result.
BLANK_FINISHER = {
    "finish_position": NA, "finish_position_label": NA, "horse_name": NA,
    "horse_country_suffix": NA, "horse_origin_country": NA,
    "horse_origin_inferred": False, "horse_yob_2digit": NA,
    "horse_foaling_year": NA, "horse_age": NA, "horse_colour_code": NA,
    "horse_colour": NA, "horse_sex_code": NA, "horse_sex": NA,
    "horse_descriptor_raw": NA, "jockey": NA,
}


def _finisher_fields(finisher, index, race, pid, issues) -> dict:
    """Build the finisher half of a record from one results row."""
    label, name_raw, descriptor_raw, jockey_raw = finisher
    race_year = race.get("_race_year")
    country_code = race.get("_country_code")

    position = POSITIONS.get(label.strip().lower().rstrip(":"))
    if position is None:
        position = index + 1
        issues.add(pid, "unknown_position_label", label)

    horse_name, suffix = split_horse_name(name_raw)
    if not horse_name:
        issues.add(pid, "missing_horse_name", name_raw)

    parts, problem = split_descriptor(descriptor_raw)
    if problem:
        issues.add(pid, problem, f"{horse_name!r} desc={descriptor_raw!r}")

    foaled, age = foaling_from_two_digit_yob(parts["yob2"], race_year)
    if parts["yob2"] and foaled is None:
        issues.add(pid, "yob_unresolvable", f"{horse_name!r} yob={parts['yob2']!r}")
    elif foaled is not None and age is None:
        issues.add(pid, "implausible_age", f"{horse_name!r} foaled={foaled} race={race_year}")

    colour = colour_name(parts["colour_code"]) if parts["colour_code"] else None
    if parts["colour_code"] and colour is None:
        issues.add(pid, "colour_unmapped", parts["colour_code"])
    if not parts["colour_code"]:
        issues.add(pid, "colour_blank", f"{horse_name!r} desc={descriptor_raw!r}")

    sex = N.sex_code(parts["sex_code"]) if parts["sex_code"] else None
    if parts["sex_code"] and sex is None:
        issues.add(pid, "sex_unmapped", parts["sex_code"])

    jockey = N._clean_or_none(jockey_raw)
    if not jockey:
        issues.add(pid, "missing_jockey", f"{horse_name!r}")

    return {
        "has_results": True,
        "finish_position": position,
        "finish_position_label": _na(label.strip().rstrip(":")),
        "horse_name": _na(horse_name),
        "horse_country_suffix": _na(suffix),
        # No suffix means bred in the publishing authority's own country --
        # usually, but NOT always, the USA. Flagged so it can be audited.
        "horse_origin_country": _na(suffix or country_code),
        "horse_origin_inferred": suffix is None,
        "horse_yob_2digit": _na(parts["yob2"]),
        "horse_foaling_year": _na(foaled),
        "horse_age": _na(age),
        "horse_colour_code": _na(parts["colour_code"]),
        "horse_colour": _na(colour),
        "horse_sex_code": _na(parts["sex_code"]),
        "horse_sex": _na(sex),
        "horse_descriptor_raw": _na((descriptor_raw or "").replace("\xa0", " ").strip()),
        "jockey": _na(jockey),
    }


FIELDS = [
    "race_id", "racepid", "race_name", "group", "group_label", "date", "date_iso",
    "race_year", "country_code", "country_name", "track_code", "track_name",
    "track_code_normalized", "distance_value", "distance_unit", "distance_metres",
    "distance_furlongs", "distance_display", "surface", "surface_raw", "purse_raw",
    "purse_local_amount", "purse_currency_symbol", "purse_currency",
    "purse_usd_site", "purse_usd_normalized", "purse_usd_display",
    "purse_usd_delta_pct", "fx_rate", "fx_rate_year", "fx_provenance",
    "age_condition", "sex_condition", "n_finishers", "has_results", "source_url",
    "finish_position", "finish_position_label", "horse_name",
    "horse_country_suffix", "horse_origin_country", "horse_origin_inferred",
    "horse_yob_2digit", "horse_foaling_year", "horse_age", "horse_colour_code",
    "horse_colour", "horse_sex_code", "horse_sex", "horse_descriptor_raw", "jockey",
]


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #


async def _aparse_all(years, cache_dir=None, limit=0, progress=True):
    records: list[dict] = []
    issues = IssueLog()
    years = list(years)

    async with CacheOnlyFetcher(cache_dir=cache_dir) as fetcher:
        wanted = []
        for year in years:
            if fetcher.listing_cached(year):
                wanted.append(year)
            else:
                print(f"  warning: {year} listing not cached yet -- skipping",
                      file=sys.stderr)
                issues.add(f"year:{year}", "year_not_cached", str(year))
        if not wanted:
            return records, issues.items

        seen = 0
        async for meta, html in iter_race_details(fetcher, wanted, ("",)):
            pid = str(meta.get("racepid", ""))
            try:
                records.extend(parse_race(meta, html, issues))
            except Exception as exc:  # one bad page must never kill the run
                issues.add(pid, "parse_exception", f"{type(exc).__name__}: {exc}")
            seen += 1
            if progress and seen % 250 == 0:
                print(f"  ... {seen} races, {len(records)} rows", file=sys.stderr)
            if limit and seen >= limit:
                break

    records.sort(key=lambda r: (str(r.get("date_iso")), str(r.get("race_id")),
                                r.get("finish_position") if isinstance(
                                    r.get("finish_position"), int) else 99))
    return records, issues.items


def parse_all(years: Iterable[int], cache_dir: str | Path | None = None,
              limit: int = 0, progress: bool = True
              ) -> tuple[list[dict], list[dict]]:
    """Parse every cached race for ``years``.

    Returns ``(records, issues)``. One record per finisher (plus one all-``N/A``
    placeholder row for a race with no published result). Each issue is
    ``{"racepid", "issue", "detail"}``. Uncached years are skipped, not fatal.
    """
    return asyncio.run(_aparse_all(years, cache_dir=cache_dir, limit=limit,
                                   progress=progress))


def parse_one(pid: str, cache_dir: str | Path | None = None
              ) -> tuple[list[dict], list[dict]]:
    """Parse a single cached racepid. Handy for tests and spot checks."""
    issues = IssueLog()
    cache = HtmlCache(Path(cache_dir) if cache_dir else ROOT / "cache")
    html = cache.get(cache_key("GET", detail_url(pid)))
    meta = {"racepid": str(pid)}
    if html is None:
        issues.add(pid, "detail_not_cached", detail_url(pid))
        return [], issues.items
    return parse_race(meta, html, issues), issues.items


def write_jsonl(rows: Sequence[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def summarize(records: Sequence[dict], issues: Sequence[dict]) -> dict:
    races = {r["race_id"] for r in records if r["race_id"] != NA}
    with_results = {r["race_id"] for r in records if r.get("has_results")}
    finisher_rows = [r for r in records if r.get("has_results")]
    failures = {i["racepid"] for i in issues
                if i["issue"] in {"parse_exception", "detail_not_cached"}}
    return {
        "races_seen": len(races),
        "races_with_results": len(with_results),
        "races_without_results": len(races) - len(with_results),
        "finisher_rows": len(finisher_rows),
        "total_rows_written": len(records),
        "parse_failures": len(failures),
        "issues_total": len(issues),
        "issue_types": dict(sorted(collections.Counter(
            i["issue"] for i in issues).items(), key=lambda kv: -kv[1])),
        "group_breakdown": dict(sorted(collections.Counter(
            r["group"] for r in finisher_rows).items())),
        "distance_units": dict(sorted(collections.Counter(
            r["distance_unit"] for r in finisher_rows).items())),
        "surfaces": dict(sorted(collections.Counter(
            r["surface"] for r in finisher_rows).items())),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", default="2015", help="e.g. 2015, 2003-2026, 2015,2020")
    ap.add_argument("--out", default=str(RECORDS_PATH))
    ap.add_argument("--issues-out", default=str(ISSUES_PATH))
    ap.add_argument("--summary-out", default=str(SUMMARY_PATH))
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--limit", type=int, default=0, help="stop after N races")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    years = parse_years(args.years)
    t0 = time.perf_counter()
    records, issues = parse_all(years, cache_dir=args.cache_dir, limit=args.limit,
                                progress=not args.quiet)
    elapsed = time.perf_counter() - t0

    write_jsonl(records, Path(args.out))
    write_jsonl(issues, Path(args.issues_out))
    summary = summarize(records, issues)
    summary["years_requested"] = years
    summary["elapsed_seconds"] = round(elapsed, 2)
    summary["normalize_gaps_worked_around"] = NORMALIZE_GAPS
    Path(args.summary_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"\nwrote {len(records)} rows -> {args.out}")
    print(f"wrote {len(issues)} issues -> {args.issues_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
