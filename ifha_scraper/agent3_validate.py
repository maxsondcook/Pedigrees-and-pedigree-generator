#!/usr/bin/env python3
"""Audit the parsed IFHA records and build the user's deliverable CSV.

Consumes :func:`agent2_parse.parse_all` -- no network, no HTML. Everything here
is validation plus presentation:

* collapses races that IFHA publishes twice under different ``racepid``\\ s
  (the ``(Date + Track + Race Name + Group)`` key the user asked for),
* picks a USD purse per row under one of three ``--purse-source`` policies and
  records the choice in a ``Purse Source`` column so it is never silent,
* re-runs :func:`normalize.clean_text` over every text field,
* writes the CSV as **utf-8-sig** so Excel and Sheets render ``£ ¥ €`` and
  accented names instead of mojibake,
* spot-checks famous results against known history, so the output is checked
  for being CORRECT and not merely well-formed.

Usage:
    python3 agent3_validate.py --years 2003-2026
    python3 agent3_validate.py --years 2015 --purse-source normalized
    python3 agent3_validate.py --years 2003-2010 --provisional

Outputs (paths are defaults, all overridable):
    ~/Desktop/graded_stakes_results - Sheet1.csv   the deliverable
    ifha_graded_stakes_2003_2026.csv               identical repo copy
    VALIDATION_REPORT.md                           human-readable findings
    validation_issues.csv                          one row per flagged row
    validation_summary.json                        machine-readable findings
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Iterable, Sequence

import normalize as N
from agent1_fetch import parse_years
from agent2_parse import parse_all

ROOT = Path(__file__).resolve().parent
DESKTOP = Path.home() / "Desktop"

#: The deliverable. Note the space and the hyphen -- this is the file the user
#: already has open; we only fill in the rows under their header.
DELIVERABLE_PATH = DESKTOP / "graded_stakes_results - Sheet1.csv"
REPO_CSV_PATH = ROOT / "ifha_graded_stakes_2003_2026.csv"
REPORT_PATH = ROOT / "VALIDATION_REPORT.md"
ISSUES_PATH = ROOT / "validation_issues.csv"
SUMMARY_PATH = ROOT / "validation_summary.json"

NA = N.NOT_AVAILABLE  # "N/A"

FIRST_YEAR, LAST_YEAR = 2003, 2026

#: Years whose low counts are known source-data facts, not pipeline bugs.
#: Keyed by year -> the explanation that goes straight into the report.
EXPECTED_SPARSE = {
    2003: "IFHA holds only ~24 G2 and ~10 G3 races for 2003 (324 total vs "
          "~1,400 in later years). Source-data gap, confirmed by Agent 1's "
          "per-year x group census.",
    2020: "COVID-19 cancellations. IFHA lists 976 races for 2020, so the "
          "shortfall against other years is real racing history, not a scrape bug.",
    2026: "Partial year: 760 races carded, and races dated after the scrape "
          "have no published result yet.",
}

#: Plausible range for a Thoroughbred's age in a Group/Graded race.
AGE_MIN, AGE_MAX = 2, 12

#: Hybrid rule: fall back to normalize.py's figure only when IFHA's own USD
#: number is this far out AND we have real ECB data to contradict it.
HYBRID_DELTA_PCT = 25.0
HYBRID_TRUSTED_PROVENANCE = {"ecb"}

PURSE_SOURCES = ("site", "normalized", "hybrid")


# --------------------------------------------------------------------------- #
# output schema
# --------------------------------------------------------------------------- #

#: The user's original 11 columns, in their original relative order, with
#: ``Race Name`` prepended and ``race_id`` last, per the approved changes.
#: Everything between ``Group`` and ``race_id`` is additive context.
COLUMNS = [
    "Race Name",                     # added, first (ties finishers to a race)
    "Horse Name",
    "Last 2 digits of year Foaled",
    "Sex",
    "Place",
    "Country",
    "Track",
    "Date",
    "Distance",
    "Age",                           # the HORSE's age (numeric)
    "Purse",
    "Group",
    # ---- additive ----
    "Race Conditions",               # the "3U" / "02 f" eligibility string
    "Date (ISO)",
    "Purse Source",
    "Purse (Local)",
    "Purse Currency",
    "Distance (Metres)",
    "Colour",
    "Jockey",
    "Horse Country Suffix",
    "Foaling Year",
    "race_id",                       # added, last
]

ISSUE_COLUMNS = [
    "check", "severity", "year", "race_id", "racepid", "Date (ISO)",
    "Track", "Race Name", "Group", "Place", "Horse Name", "detail",
]


# --------------------------------------------------------------------------- #
# independent correctness fixtures
# --------------------------------------------------------------------------- #

class SpotCheck(dict):
    """A result the author knows independently of this pipeline."""


#: Famous results, deliberately spread across years OTHER than 2015 (Agent 2
#: already verified 2015). ``name`` is matched as a normalized substring
#: because IFHA carries sponsor names ("Breeders' Cup Classic Powered by
#: Dodge"). Any check whose year is not in the run is skipped, so this table
#: also covers the eventual full 2003-2026 pass.
SPOT_CHECKS: list[dict] = [
    # --- Northern Hemisphere championship races ---
    {"year": 2003, "name": "breeders' cup classic", "winner": "Pleasantly Perfect",
     "date": "2003-10-25", "country": "USA"},
    {"year": 2004, "name": "breeders' cup classic", "winner": "Ghostzapper",
     "date": "2004-10-30", "country": "USA"},
    {"year": 2009, "name": "breeders' cup classic", "winner": "Zenyatta",
     "date": "2009-11-07", "country": "USA"},
    {"year": 2010, "name": "breeders' cup classic", "winner": "Blame",
     "date": "2010-11-06", "country": "USA"},
    {"year": 2022, "name": "breeders' cup classic", "winner": "Flightline",
     "date": "2022-11-05", "country": "USA"},
    # --- Classics ---
    {"year": 2005, "name": "kentucky derby", "winner": "Giacomo",
     "date": "2005-05-07", "country": "USA"},
    {"year": 2007, "name": "kentucky derby", "winner": "Street Sense",
     "date": "2007-05-05", "country": "USA"},
    {"year": 2008, "name": "kentucky derby", "winner": "Big Brown",
     "date": "2008-05-03", "country": "USA"},
    {"year": 2009, "name": "preakness", "winner": "Rachel Alexandra",
     "date": "2009-05-16", "country": "USA"},
    {"year": 2009, "name": "belmont s", "winner": "Summer Bird",
     "date": "2009-06-06", "country": "USA"},
    {"year": 2004, "name": "derby s", "winner": "North Light",
     "date": "2004-06-05", "country": "ENG"},
    # --- Europe ---
    {"year": 2007, "name": "arc de triomphe", "winner": "Dylan Thomas",
     "date": "2007-10-07", "country": "FR"},
    {"year": 2008, "name": "arc de triomphe", "winner": "Zarkava",
     "date": "2008-10-05", "country": "FR"},
    {"year": 2009, "name": "arc de triomphe", "winner": "Sea The Stars",
     "date": "2009-10-04", "country": "FR"},
    {"year": 2010, "name": "arc de triomphe", "winner": "Workforce",
     "date": "2010-10-03", "country": "FR"},
    {"year": 2012, "name": "queen anne", "winner": "Frankel",
     "date": "2012-06-19", "country": "ENG"},
    {"year": 2012, "name": "diamond jubilee", "winner": "Black Caviar",
     "date": "2012-06-23", "country": "ENG"},
    # --- Middle East / Asia / Oceania ---
    {"year": 2005, "name": "dubai world cup", "winner": "Roses In May",
     "date": "2005-03-26", "country": "UAE"},
    {"year": 2006, "name": "dubai world cup", "winner": "Electrocutionist",
     "date": "2006-03-25", "country": "UAE"},
    {"year": 2007, "name": "dubai world cup", "winner": "Invasor",
     "date": "2007-03-31", "country": "UAE"},
    {"year": 2009, "name": "dubai world cup", "winner": "Well Armed",
     "date": "2009-03-28", "country": "UAE"},
    {"year": 2007, "name": "japan cup", "winner": "Admire Moon",
     "date": "2007-11-25", "country": "JPN"},
    {"year": 2006, "name": "melbourne cup", "winner": "Delta Blues",
     "date": "2006-11-07", "country": "AUS"},
    {"year": 2008, "name": "melbourne cup", "winner": "Viewed",
     "date": "2008-11-04", "country": "AUS"},
    {"year": 2009, "name": "cox plate", "winner": "So You Think",
     "date": "2009-10-24", "country": "AUS"},
    {"year": 2017, "name": "cox plate", "winner": "Winx",
     "date": "2017-10-28", "country": "AUS"},
]


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def text(value) -> str:
    """Clean a scraped value for display. ``N/A`` for anything empty.

    Deliberately routed through :func:`normalize.clean_text`, which strips HTML
    entities and non-breaking spaces but **keeps trailing periods** -- race
    names legitimately end in them (``Ack Ack S.``).
    """
    if value is None:
        return NA
    if isinstance(value, bool):
        return NA
    if isinstance(value, (int, float)):
        return str(value)
    return N.clean_text(value)


def num(value):
    """Return ``value`` as a float, or None for ``N/A`` / unparseable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = N.clean_text(value)
    if cleaned == NA:
        return None
    try:
        return float(cleaned.replace(",", ""))
    except ValueError:
        return None


def intish(value):
    value = num(value)
    return None if value is None else int(round(value))


def money(usd) -> str:
    """``$400,000``. ``$0`` is a real value in this source, not a blank."""
    return NA if usd is None else f"${round(usd):,.0f}"


def key_text(value) -> str:
    """Fold a value for use inside a dedup key.

    Case, punctuation and whitespace differences must not create two keys for
    one physical race, but we never write this form into the CSV.
    """
    cleaned = N.clean_text(value)
    if cleaned == NA:
        return ""
    folded = re.sub(r"[^0-9a-z]+", " ", cleaned.casefold())
    return re.sub(r"\s+", " ", folded).strip()


def race_key(record: dict) -> tuple:
    """The user's stated dedup key: Date + Track + Race Name + Group."""
    return (
        text(record.get("date_iso")),
        key_text(record.get("track_code_normalized")) or key_text(record.get("track_code")),
        key_text(record.get("race_name")),
        text(record.get("group")),
    )


def pid_sort_key(pid: str) -> tuple:
    """Order racepids numerically so "lower racepid" means what it says."""
    value = num(pid)
    return (0, value, "") if value is not None else (1, 0.0, str(pid))


def record_year(record: dict):
    year = intish(record.get("race_year"))
    if year is not None:
        return year
    iso = text(record.get("date_iso"))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso):
        return int(iso[:4])
    return None


# --------------------------------------------------------------------------- #
# purse policy
# --------------------------------------------------------------------------- #

def choose_purse(record: dict, mode: str) -> tuple:
    """Pick the USD purse for one row under ``mode``.

    Returns ``(usd_or_None, source_label)``. ``source_label`` goes into the
    ``Purse Source`` column so the policy is auditable row by row.

    ``hybrid`` (the default) trusts IFHA's contemporaneous figure except where
    it disagrees with :mod:`normalize` by more than 25% *and* the normalized
    rate came from real ECB data -- the Brazil-2015 case, where IFHA converted
    every BRL purse at the 2014 average of ~2.657 instead of 2015's 3.336.
    """
    if mode not in PURSE_SOURCES:
        raise ValueError(f"unknown purse source {mode!r}; expected one of {PURSE_SOURCES}")

    site = num(record.get("purse_usd_site"))
    normalized = num(record.get("purse_usd_normalized"))
    currency = text(record.get("purse_currency"))
    provenance = text(record.get("fx_provenance"))

    # A USD-denominated purse needs no conversion at all; IFHA only prints a
    # "(*$...)" figure for non-USD races, so its absence here is not a gap.
    if currency == "USD" and normalized is not None:
        return normalized, "usd_native"

    if mode == "site":
        if site is not None:
            return site, "site"
        return (normalized, "normalized_site_missing") if normalized is not None else (None, NA)

    if mode == "normalized":
        if normalized is not None:
            return normalized, "normalized"
        return (site, "site_normalized_missing") if site is not None else (None, NA)

    # ---- hybrid ----
    if site is None:
        return (normalized, "normalized_site_missing") if normalized is not None else (None, NA)
    if normalized is None:
        return site, "site_normalized_missing"

    delta = num(record.get("purse_usd_delta_pct"))
    if delta is None and normalized:
        delta = (site - normalized) / normalized * 100.0
    if (delta is not None and abs(delta) > HYBRID_DELTA_PCT
            and provenance in HYBRID_TRUSTED_PROVENANCE):
        return normalized, "normalized_stale_site"
    return site, "site"


# --------------------------------------------------------------------------- #
# row construction
# --------------------------------------------------------------------------- #

def race_conditions(record: dict) -> str:
    """The ``3U`` / ``02 f`` eligibility string, kept out of the ``Age`` column."""
    age = text(record.get("age_condition"))
    sex = text(record.get("sex_condition"))
    parts = [p for p in (age, sex) if p != NA]
    return " ".join(parts) if parts else NA


def distance_display(record: dict) -> str:
    """``8 Furlongs (D)`` -- surfaces D / T / AW (the user chose AW over E)."""
    metres = num(record.get("distance_metres"))
    if metres is not None:
        return N.distance_with_surface(metres, record.get("surface"), aw_code="AW")
    display = text(record.get("distance_display"))
    if display == NA:
        return NA
    surface = text(record.get("surface"))
    return f"{display} ({surface})" if surface != NA else display


def foaled_two_digit(record: dict) -> str:
    short = text(record.get("horse_yob_2digit"))
    if re.fullmatch(r"\d{2}", short):
        return short
    foaled = intish(record.get("horse_foaling_year"))
    return f"{foaled % 100:02d}" if foaled is not None else NA


def build_row(record: dict, mode: str) -> dict:
    """Turn one parser record into one deliverable CSV row."""
    usd, purse_source = choose_purse(record, mode)
    local = num(record.get("purse_local_amount"))
    place = intish(record.get("finish_position"))
    track = text(record.get("track_code_normalized"))
    if track == NA:
        track = text(record.get("track_code"))

    return {
        "Race Name": text(record.get("race_name")),
        "Horse Name": text(record.get("horse_name")),
        "Last 2 digits of year Foaled": foaled_two_digit(record),
        "Sex": text(record.get("horse_sex")) if text(record.get("horse_sex")) != NA
               else text(record.get("horse_sex_code")),
        "Place": str(place) if place is not None else NA,
        "Country": text(record.get("country_code")),
        "Track": track,
        "Date": text(record.get("date")),
        "Distance": distance_display(record),
        "Age": str(intish(record.get("horse_age")))
               if intish(record.get("horse_age")) is not None else NA,
        "Purse": money(usd),
        "Group": text(record.get("group")),
        "Race Conditions": race_conditions(record),
        "Date (ISO)": text(record.get("date_iso")),
        "Purse Source": purse_source,
        "Purse (Local)": f"{local:,.0f}" if local is not None else NA,
        "Purse Currency": text(record.get("purse_currency")),
        "Distance (Metres)": (f"{num(record.get('distance_metres')):,.0f}"
                              if num(record.get("distance_metres")) is not None else NA),
        "Colour": text(record.get("horse_colour")) if text(record.get("horse_colour")) != NA
                  else text(record.get("horse_colour_code")),
        "Jockey": text(record.get("jockey")),
        "Horse Country Suffix": text(record.get("horse_country_suffix")),
        "Foaling Year": str(intish(record.get("horse_foaling_year")))
                        if intish(record.get("horse_foaling_year")) is not None else NA,
        "race_id": text(record.get("race_id")),
    }


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #

class Findings:
    """Accumulates flagged rows plus the counters the report is built from."""

    def __init__(self):
        self.issues: list[dict] = []
        self.collapses: list[dict] = []
        self.spot_checks: list[dict] = []
        self.counters: collections.Counter = collections.Counter()

    def flag(self, check: str, record: dict, detail: str = "",
             severity: str = "warning") -> None:
        self.counters[check] += 1
        record = record or {}
        year = record_year(record)
        self.issues.append({
            "check": check,
            "severity": severity,
            "year": "" if year is None else year,
            "race_id": text(record.get("race_id")),
            "racepid": text(record.get("racepid")),
            "Date (ISO)": text(record.get("date_iso")),
            "Track": text(record.get("track_code_normalized")),
            "Race Name": text(record.get("race_name")),
            "Group": text(record.get("group")),
            "Place": text(record.get("finish_position")),
            "Horse Name": text(record.get("horse_name")),
            "detail": str(detail)[:400],
        })

    def counts(self) -> dict:
        return dict(sorted(self.counters.items(), key=lambda kv: (-kv[1], kv[0])))


def group_by_race(records: Sequence[dict]) -> "collections.OrderedDict[str, list[dict]]":
    """Bucket records by ``race_id``, preserving first-seen order."""
    races: collections.OrderedDict[str, list[dict]] = collections.OrderedDict()
    for record in records:
        races.setdefault(text(record.get("race_id")), []).append(record)
    return races


def finisher_signature(rows: Sequence[dict]) -> tuple:
    """Place + horse name, so we can tell a true duplicate from a split race."""
    return tuple(sorted(
        (intish(r.get("finish_position")) or 0, key_text(r.get("horse_name")))
        for r in rows if r.get("has_results")
    ))


def _log_collapse(findings: Findings, dropped_rows: Sequence[dict],
                  dropped_id: str, kept_id: str, key: tuple, same: bool) -> None:
    findings.collapses.append({
        "dropped_race_id": dropped_id,
        "kept_race_id": kept_id,
        "date_iso": key[0],
        "track": text(dropped_rows[0].get("track_code_normalized")),
        "race_name": text(dropped_rows[0].get("race_name")),
        "group": key[3],
        "identical_results": same,
        "rows_dropped": len(dropped_rows),
    })
    findings.flag(
        "duplicate_race_collapsed", dropped_rows[0],
        f"racepid {dropped_id} duplicates {kept_id} on "
        f"(date+track+name+group); results identical={same}; "
        f"{len(dropped_rows)} row(s) dropped",
        severity="info" if same else "warning",
    )
    if not same:
        findings.flag(
            "duplicate_race_results_differ", dropped_rows[0],
            f"racepid {dropped_id} and kept {kept_id} share the dedup key but "
            f"their finishers differ -- could be two divisions of one race "
            f"rather than a republished duplicate; REVIEW",
            severity="error",
        )


def deduplicate(records: Sequence[dict], findings: Findings) -> list[dict]:
    """Collapse races IFHA publishes twice under different ``racepid``\\ s.

    ``racepid`` is NOT a unique key for a physical race. The user's key is
    ``Date + Track + Race Name + Group``; within a cluster of *identical*
    finishers the lower racepid wins. Two pids that share the key but have
    different finishers are kept as distinct races (Blue Diamond Prelude
    colts vs fillies, etc.). An empty placeholder never beats a copy that
    actually has results.
    """
    races = group_by_race(records)
    kept_ids: set[str] = set()
    groups: dict[tuple, list[str]] = collections.OrderedDict()

    for race_id, rows in races.items():
        key = race_key(rows[0])
        if "" in key[:1] or key[0] == NA:
            kept_ids.add(race_id)
            continue
        groups.setdefault(key, []).append(race_id)

    for key, ids in groups.items():
        clusters: dict[tuple, list[str]] = collections.OrderedDict()
        empty: list[str] = []
        for race_id in ids:
            sig = finisher_signature(races[race_id])
            if sig:
                clusters.setdefault(sig, []).append(race_id)
            else:
                empty.append(race_id)

        if clusters:
            winners = []
            for cluster_ids in clusters.values():
                winner = min(cluster_ids, key=pid_sort_key)
                winners.append(winner)
                kept_ids.add(winner)
                for race_id in cluster_ids:
                    if race_id != winner:
                        _log_collapse(findings, races[race_id], race_id, winner,
                                      key, same=True)
            if len(clusters) > 1:
                findings.flag(
                    "duplicate_key_distinct_races", races[winners[0]][0],
                    f"{len(clusters)} distinct finisher lists share "
                    f"(date+track+name+group); keeping pids {winners} "
                    f"(likely divisions, not republishes)",
                    severity="warning",
                )
            fallback = min(winners, key=pid_sort_key)
            for race_id in empty:
                _log_collapse(findings, races[race_id], race_id, fallback,
                              key, same=False)
        else:
            winner = min(empty, key=pid_sort_key)
            kept_ids.add(winner)
            for race_id in empty:
                if race_id != winner:
                    _log_collapse(findings, races[race_id], race_id, winner,
                                  key, same=True)

    return [r for r in records if text(r.get("race_id")) in kept_ids]


def _uncached_years(parse_issues: Sequence[dict] | None) -> set[int]:
    out: set[int] = set()
    for issue in parse_issues or []:
        if issue.get("issue") != "year_not_cached":
            continue
        try:
            out.add(int(issue.get("detail")))
        except (TypeError, ValueError):
            continue
    return out


def check_year_coverage(records: Sequence[dict], years: Sequence[int],
                        findings: Findings,
                        parse_issues: Sequence[dict] | None = None) -> dict:
    """Counts by year and by year x group, with anomalous years classified."""
    by_year: collections.Counter = collections.Counter()
    by_year_group: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    races_by_year: dict[int, set] = collections.defaultdict(set)

    for record in records:
        year = record_year(record)
        if year is None:
            findings.flag("record_without_year", record, "no parseable date or race_year",
                          severity="error")
            continue
        by_year[year] += 1
        by_year_group[year][text(record.get("group"))] += 1
        races_by_year[year].add(text(record.get("race_id")))

    requested = [y for y in years if FIRST_YEAR <= y <= LAST_YEAR]
    present = [y for y in requested if by_year.get(y, 0) > 0]
    missing = [y for y in requested if by_year.get(y, 0) == 0]
    uncached = _uncached_years(parse_issues)

    # Only years we do not already expect to be sparse set the normal level.
    baseline_years = [y for y in present if y not in EXPECTED_SPARSE]
    baseline = statistics.median([by_year[y] for y in baseline_years]) if baseline_years else 0

    anomalies = []
    for year in requested:
        count = by_year.get(year, 0)
        if count == 0:
            if year in uncached:
                verdict = "Year listing is not in the cache yet; skipped by parse_all."
            elif year in EXPECTED_SPARSE:
                verdict = EXPECTED_SPARSE[year]
            else:
                verdict = ("NO RECORDS. Either the year is not cached yet or the "
                           "pipeline dropped it -- investigate before trusting.")
            anomalies.append({
                "year": year, "rows": 0, "races": 0, "ratio": 0.0,
                "expected": year in EXPECTED_SPARSE or year in uncached,
                "verdict": verdict,
            })
            continue
        ratio = (count / baseline) if baseline else 1.0
        if year in EXPECTED_SPARSE or ratio < 0.6:
            anomalies.append({
                "year": year, "rows": count, "races": len(races_by_year[year]),
                "ratio": round(ratio, 3),
                "expected": year in EXPECTED_SPARSE,
                "verdict": EXPECTED_SPARSE.get(
                    year, f"{count} rows is {ratio:.0%} of the {baseline:.0f}-row "
                          "median; not a documented source gap -- investigate."),
            })

    for year in missing:
        known = year in EXPECTED_SPARSE or year in uncached
        findings.flag("year_missing", {"race_year": year},
                      f"{year}: no records "
                      f"({EXPECTED_SPARSE.get(year, 'not cached yet, or a pipeline bug')})",
                      severity="info" if known or year > LAST_YEAR else "error")

    return {
        "rows_by_year": {y: by_year.get(y, 0) for y in requested},
        "races_by_year": {y: len(races_by_year.get(y, set())) for y in requested},
        "rows_by_year_group": {
            y: dict(sorted(by_year_group.get(y, collections.Counter()).items()))
            for y in requested
        },
        "years_present": present,
        "years_missing": missing,
        "baseline_rows_per_year": baseline,
        "anomalies": anomalies,
    }


def check_rows(records: Sequence[dict], findings: Findings) -> dict:
    """Per-row sanity: finisher counts, ages, blank names, zero purses."""
    races = group_by_race(records)

    finisher_counts: collections.Counter = collections.Counter()
    resultless, dead_heats, odd_fields = [], [], []
    for race_id, rows in races.items():
        scored = [r for r in rows if r.get("has_results")]
        finisher_counts[len(scored)] += 1
        places = sorted(p for p in (intish(r.get("finish_position")) for r in scored)
                        if p is not None)
        # A dead heat shows up two ways, both verified in the source HTML: as a
        # repeated position label ("First:/First:/Third:") in a 3-row race, or
        # as a 4th row ("First:/Second:/Third:/Third:").
        shared_place = len(set(places)) != len(places)

        if not scored:
            resultless.append(race_id)
            findings.flag("race_without_results", rows[0],
                          "no finishers published by the source authority "
                          "(expected for ~0.8% of races and for future-dated races)",
                          severity="info")
            continue

        if shared_place:
            dead_heats.append(race_id)
            findings.flag("dead_heat", rows[0],
                          f"dead heat: placings {places} -- the source itself "
                          f"repeats the position label; kept deliberately",
                          severity="info")
        if len(scored) not in (3, 4) or (len(scored) == 4 and not shared_place):
            odd_fields.append(race_id)
            findings.flag("unexpected_finisher_count", rows[0],
                          f"{len(scored)} finisher rows with placings {places} "
                          f"(3 is normal, 4 only for a dead heat)",
                          severity="warning")

    ages, age_outliers = [], 0
    blank_names = zero_purses = missing_purses = 0
    for record in records:
        has_results = bool(record.get("has_results"))
        name = text(record.get("horse_name"))

        if name == NA and has_results:
            blank_names += 1
            findings.flag("empty_horse_name_with_results", record,
                          "has_results is true but Horse Name is N/A", severity="error")

        if has_results:
            age = intish(record.get("horse_age"))
            if age is None:
                findings.flag("age_unknown", record,
                              f"descriptor={text(record.get('horse_descriptor_raw'))}",
                              severity="warning")
            else:
                ages.append(age)
                if not (AGE_MIN <= age <= AGE_MAX):
                    age_outliers += 1
                    findings.flag("age_implausible", record,
                                  f"age {age} outside {AGE_MIN}-{AGE_MAX} "
                                  f"(foaled {text(record.get('horse_foaling_year'))})",
                                  severity="warning")

        local = num(record.get("purse_local_amount"))
        if local is None:
            missing_purses += 1
            findings.flag("purse_missing", record,
                          f"raw={text(record.get('purse_raw'))}", severity="warning")
        elif local == 0:
            zero_purses += 1
            findings.flag("purse_zero", record,
                          "purse of 0 is present in the source itself; kept, not dropped",
                          severity="info")

        if num(record.get("distance_metres")) is None:
            findings.flag("distance_missing", record,
                          f"display={text(record.get('distance_display'))} "
                          f"raw_unit={text(record.get('distance_unit'))}",
                          severity="warning")
        if text(record.get("surface")) == NA:
            findings.flag("surface_missing", record,
                          f"raw={text(record.get('surface_raw'))}", severity="info")
        if text(record.get("group")) not in {"G1", "G2", "G3"}:
            findings.flag("group_missing", record,
                          f"group={text(record.get('group'))}", severity="warning")

    return {
        "races": len(races),
        "finisher_count_distribution": dict(sorted(finisher_counts.items())),
        "races_without_results": len(resultless),
        "races_with_dead_heat": len(dead_heats),
        "races_with_unexpected_field": len(odd_fields),
        "rows_with_blank_horse_name_despite_results": blank_names,
        "zero_purse_rows": zero_purses,
        "missing_purse_rows": missing_purses,
        "age_outliers": age_outliers,
        "age_min": min(ages) if ages else None,
        "age_max": max(ages) if ages else None,
        "age_median": statistics.median(ages) if ages else None,
    }


_ENTITY_RE = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]{1,8}|#[0-9]{1,6}|#x[0-9A-Fa-f]{1,6});")
_BAD_SPACE_RE = re.compile(r"[\u00a0\u2007\u202f\u200b\ufeff]")


def check_text_hygiene(rows: Sequence[dict], findings: Findings,
                       records_by_index: Sequence[dict]) -> dict:
    """Assert the written strings are already scrubbed.

    ``clean_text`` runs on every field in :func:`build_row`, so anything found
    here is a bug in this module, not dirty source data.
    """
    problems: collections.Counter = collections.Counter()
    for row, record in zip(rows, records_by_index):
        for column, value in row.items():
            if not isinstance(value, str) or not value:
                continue
            if _ENTITY_RE.search(value):
                problems["html_entity"] += 1
                findings.flag("text_html_entity", record, f"{column}={value!r}",
                              severity="error")
            if _BAD_SPACE_RE.search(value):
                problems["odd_whitespace"] += 1
                findings.flag("text_odd_whitespace", record, f"{column}={value!r}",
                              severity="error")
            if value != value.strip() or "  " in value:
                problems["untrimmed"] += 1
                findings.flag("text_untrimmed", record, f"{column}={value!r}",
                              severity="error")
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                problems["wrapping_quotes"] += 1
                findings.flag("text_wrapping_quotes", record, f"{column}={value!r}",
                              severity="warning")

    trailing_periods = sum(1 for row in rows if row["Race Name"].endswith("."))
    return {
        "problems": dict(problems),
        "race_names_ending_in_a_period_preserved": trailing_periods,
    }


def run_spot_checks(rows: Sequence[dict], years: Sequence[int],
                    findings: Findings) -> list[dict]:
    """Compare famous winners and dates against history, not against ourselves."""
    by_year: dict[int, list[dict]] = collections.defaultdict(list)
    for row in rows:
        iso = row["Date (ISO)"]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso):
            by_year[int(iso[:4])].append(row)

    requested = set(years)
    results = []
    for check in SPOT_CHECKS:
        year = check["year"]
        outcome = {**check, "status": "skipped", "found_winner": None,
                   "found_date": None, "found_race": None, "note": ""}
        if year not in requested or not by_year.get(year):
            outcome["note"] = f"{year} not in this run"
            results.append(outcome)
            continue

        needle = key_text(check["name"])
        candidates = [
            r for r in by_year[year]
            if needle in key_text(r["Race Name"])
            and (check.get("country") is None or r["Country"] == check["country"])
        ]
        if check.get("date"):
            dated = [r for r in candidates if r["Date (ISO)"] == check["date"]]
            if dated:
                candidates = dated
            elif candidates:
                outcome["status"] = "not_found"
                outcome["note"] = (
                    f"name matched {len(candidates)} row(s) but none on {check['date']}"
                )
                findings.flag("spot_check_race_not_found", {"race_year": year},
                              f"{year} {needle!r} ({check['winner']}) "
                              f"missing on {check['date']}",
                              severity="warning")
                results.append(outcome)
                continue
        if not candidates:
            outcome["status"] = "not_found"
            outcome["note"] = f"no {year} race whose name contains {needle!r}"
            findings.flag("spot_check_race_not_found", {"race_year": year},
                          f"{year} {needle!r} ({check['winner']})", severity="warning")
            results.append(outcome)
            continue

        # Shortest matching name wins so "belmont s" hits "Belmont S." rather
        # than "Belmont Sprint Championship".
        candidates.sort(key=lambda r: (len(key_text(r["Race Name"])), r["Race Name"]))
        winners = [r for r in candidates if r["Place"] == "1"]
        target = winners[0] if winners else candidates[0]
        outcome["found_race"] = target["Race Name"]
        outcome["found_winner"] = target["Horse Name"]
        outcome["found_date"] = target["Date (ISO)"]

        name_ok = key_text(target["Horse Name"]) == key_text(check["winner"])
        date_ok = check.get("date") in (None, target["Date (ISO)"])
        if name_ok and date_ok:
            outcome["status"] = "pass"
        else:
            outcome["status"] = "fail"
            outcome["note"] = (
                f"expected {check['winner']} on {check.get('date')}, "
                f"got {target['Horse Name']} on {target['Date (ISO)']}"
            )
            findings.flag("spot_check_failed", {},
                          f"{year} {target['Race Name']}: {outcome['note']}",
                          severity="error")
        results.append(outcome)
    return results


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #

def sort_rows(rows: list[dict]) -> list[dict]:
    """Chronological, then race, then finishing position."""
    def key(row):
        iso = row["Date (ISO)"]
        return (iso if re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso) else "9999-99-99",
                key_text(row["Race Name"]),
                pid_sort_key(row["race_id"]),
                intish(row["Place"]) if intish(row["Place"]) is not None else 99)
    return sorted(rows, key=key)


def write_csv(rows: Sequence[dict], path: Path, columns: Sequence[str] = COLUMNS) -> None:
    """Write utf-8-**sig**: the BOM is what makes Excel and Sheets show
    ``JOSÉ GUATHEMOZIN NOGUEIRA`` instead of mojibake."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def validate(years: Iterable[int], purse_source: str = "hybrid",
             cache_dir=None, limit: int = 0, progress: bool = True,
             records: Sequence[dict] | None = None,
             parse_issues: Sequence[dict] | None = None) -> dict:
    """Parse (or accept) records, audit them, and return rows plus findings.

    Pass ``records`` to audit an in-memory list instead of re-parsing; the test
    suite uses that to exercise the checks on synthetic data.
    """
    years = list(years)
    findings = Findings()

    if records is None:
        records, parse_issues = parse_all(years, cache_dir=cache_dir, limit=limit,
                                          progress=progress)
    records = list(records or [])
    parse_issues = list(parse_issues or [])

    # Placeholder rows for pages that are not on disk yet are not "races with
    # no published result" -- they are just unfinished fetch work. Drop them
    # so a provisional CSV is not padded with N/A finishers.
    not_cached_pids = {
        str(i.get("racepid") or "")
        for i in parse_issues if i.get("issue") == "detail_not_cached"
    }
    omitted_uncached = 0
    if not_cached_pids:
        before = len(records)
        records = [r for r in records if text(r.get("racepid")) not in not_cached_pids]
        omitted_uncached = before - len(records)

    raw_count = len(records)
    kept = deduplicate(records, findings)

    coverage = check_year_coverage(kept, years, findings, parse_issues)
    row_checks = check_rows(kept, findings)

    rows = [build_row(r, purse_source) for r in kept]
    hygiene = check_text_hygiene(rows, findings, kept)
    rows = sort_rows(rows)

    purse_usage = collections.Counter(r["Purse Source"] for r in rows)
    spot = run_spot_checks(rows, years, findings)

    summary = {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "years_requested": years,
        "purse_source_mode": purse_source,
        "rows_before_dedup": raw_count,
        "omitted_uncached_detail_rows": omitted_uncached,
        "rows_written": len(rows),
        "races_written": row_checks["races"],
        "duplicate_races_collapsed": len(findings.collapses),
        "rows_dropped_by_dedup": raw_count - len(kept),
        "coverage": coverage,
        "row_checks": row_checks,
        "text_hygiene": hygiene,
        "purse_source_usage": dict(sorted(purse_usage.items(), key=lambda kv: -kv[1])),
        "spot_checks": spot,
        "spot_check_tally": dict(collections.Counter(s["status"] for s in spot)),
        "validation_issue_counts": findings.counts(),
        "validation_issues_total": len(findings.issues),
        "parser_issue_counts": dict(sorted(
            collections.Counter(i["issue"] for i in parse_issues).items(),
            key=lambda kv: -kv[1])),
        "parser_issues_total": len(parse_issues),
    }
    return {"rows": rows, "findings": findings, "summary": summary,
            "records": kept, "parse_issues": parse_issues}


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

def _table(header: Sequence[str], body: Iterable[Sequence]) -> str:
    lines = ["| " + " | ".join(str(h) for h in header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    for row in body:
        lines.append("| " + " | ".join("" if c is None else str(c) for c in row) + " |")
    return "\n".join(lines)


def render_report(summary: dict, findings: Findings, provisional: bool,
                  csv_paths: Sequence[Path], cache_files: int | None = None) -> str:
    coverage = summary["coverage"]
    checks = summary["row_checks"]
    status = "PROVISIONAL" if provisional else "FINAL"

    groups = sorted({g for per in coverage["rows_by_year_group"].values() for g in per})
    year_rows = []
    for year in sorted(coverage["rows_by_year"]):
        per = coverage["rows_by_year_group"].get(year, {})
        year_rows.append([
            year,
            coverage["rows_by_year"][year],
            coverage["races_by_year"].get(year, 0),
            *[per.get(g, 0) for g in groups],
        ])

    spot = summary["spot_checks"]
    spot_rows = [
        [s["year"], s["name"], s["winner"], s["status"],
         s["found_winner"] or "", s["found_date"] or "", s["note"]]
        for s in spot
    ]

    collapse_rows = [
        [c["date_iso"], c["track"], c["race_name"], c["group"],
         c["kept_race_id"], c["dropped_race_id"],
         "yes" if c["identical_results"] else "**NO**", c["rows_dropped"]]
        for c in sorted(findings.collapses, key=lambda c: (c["date_iso"], c["race_name"]))
    ]

    parts = [
        "# AGENT 3 (\"Validator\") — validation report",
        "",
        f"**Status: {status}**  \u2014 generated {summary['generated_utc']}",
        "",
        f"- Years requested: `{summary['years_requested'][0]}`–"
        f"`{summary['years_requested'][-1]}` "
        f"({len(summary['years_requested'])} years)",
        f"- Years with data: {len(coverage['years_present'])} "
        f"({', '.join(str(y) for y in coverage['years_present']) or 'none'})",
        f"- Years with **no** data: "
        f"{', '.join(str(y) for y in coverage['years_missing']) or 'none'}",
        f"- Rows written: **{summary['rows_written']:,}** across "
        f"**{summary['races_written']:,}** races",
        f"- Uncached detail pages omitted: "
        f"**{summary.get('omitted_uncached_detail_rows', 0):,}**",
        f"- Purse policy: **`--purse-source {summary['purse_source_mode']}`**",
        f"- Output: " + ", ".join(f"`{p}`" for p in csv_paths),
        f"- Encoding: **UTF-8 with BOM** (`utf-8-sig`); missing values are the "
        f"literal string `N/A`",
    ]
    if cache_files is not None:
        parts.append(f"- Cache at report time: **{cache_files:,}** of 30,740 files")
    if provisional:
        parts += [
            "",
            "> ⚠ **PROVISIONAL.** The fetch cache is still filling, so the years "
            "below are only the ones available now. Re-run the same command once "
            "`find cache -type f | wc -l` reaches ~30,739 and stops growing to "
            "produce the final file.",
        ]

    parts += [
        "",
        "## 1. Per-year coverage",
        "",
        _table(["Year", "Rows", "Races", *groups], year_rows),
        "",
        f"Median rows/year across years not already known to be sparse: "
        f"**{coverage['baseline_rows_per_year']:,.0f}**.",
        "",
    ]

    if coverage["anomalies"]:
        parts += ["### Anomalous years", ""]
        parts.append(_table(
            ["Year", "Rows", "Races", "vs median", "Known/expected?", "Verdict"],
            [[a["year"], a["rows"], a["races"],
              f"{a['ratio']:.0%}" if a["ratio"] else "0%",
              "yes" if a["expected"] else "**no**", a["verdict"]]
             for a in coverage["anomalies"]]))
        parts.append("")
    else:
        parts += ["No year fell below 60% of the median.", ""]

    parts += [
        "## 2. Deduplication",
        "",
        f"Key: `Date + Track + Race Name + Group` (the user's stated key). "
        f"`racepid` is **not** a unique key for a physical race, so this step is "
        f"mandatory, not cosmetic.",
        "",
        f"- Duplicate races collapsed: **{summary['duplicate_races_collapsed']}**",
        f"- Rows dropped: **{summary['rows_dropped_by_dedup']}** "
        f"(of {summary['rows_before_dedup']:,} parsed)",
        f"- Collapses where the two pids had **identical** finishers: "
        f"{sum(1 for c in findings.collapses if c['identical_results'])}",
        f"- Collapses where the finishers **differed** (empty placeholder "
        f"dropped in favour of a copy with results): "
        f"{sum(1 for c in findings.collapses if not c['identical_results'])}",
        "",
        "Within a cluster of *identical* finishers the lower racepid is kept. "
        "Two pids that share the key but have different finishers are kept as "
        "distinct races (e.g. Blue Diamond Prelude colts vs fillies). An empty "
        "placeholder never replaces a copy that has results.",
        "",
    ]
    if collapse_rows:
        shown = collapse_rows[:60]
        parts.append(_table(["Date", "Track", "Race", "Grp", "Kept pid",
                             "Dropped pid", "Identical results", "Rows dropped"], shown))
        if len(collapse_rows) > len(shown):
            parts.append("")
            parts.append(f"_…and {len(collapse_rows) - len(shown)} more; the full list "
                         f"is in `validation_issues.csv` under "
                         f"`duplicate_race_collapsed`._")
        parts.append("")

    parts += [
        "## 3. Row-level sanity checks",
        "",
        _table(["Check", "Result"], [
            ["Races", f"{checks['races']:,}"],
            ["Finisher-row distribution",
             ", ".join(f"{k} rows: {v:,} races"
                       for k, v in checks["finisher_count_distribution"].items())],
            ["Races with no published result",
             f"{checks['races_without_results']:,} (source publishes none; kept with "
             f"`N/A` finishers)"],
            ["Races with a dead heat (repeated placing)",
             f"{checks['races_with_dead_heat']:,}"],
            ["Races with an unexpected field size",
             f"{checks['races_with_unexpected_field']:,}"],
            ["Rows with a blank Horse Name despite `has_results`",
             f"{checks['rows_with_blank_horse_name_despite_results']:,}"],
            ["Horse age range (min / median / max)",
             f"{checks['age_min']} / {checks['age_median']} / {checks['age_max']}"],
            ["Ages outside 2–12", f"{checks['age_outliers']:,}"],
            ["Rows with a $0 purse",
             f"{checks['zero_purse_rows']:,} (present in the source; flagged, kept)"],
            ["Rows with no purse at all", f"{checks['missing_purse_rows']:,}"],
        ]),
        "",
        "## 4. Text cleaning and encoding",
        "",
        f"Every field passes through `normalize.clean_text`: HTML entities "
        f"(`&nbsp;`, `&amp;`, numeric), non-breaking spaces, collapsed "
        f"whitespace, stray wrapping quotes. **Trailing periods are preserved** "
        f"— {summary['text_hygiene']['race_names_ending_in_a_period_preserved']:,} "
        f"race names legitimately end in one (`Ack Ack S.`).",
        "",
        f"Post-write audit of the output strings: "
        f"`{summary['text_hygiene']['problems'] or 'no problems found'}`.",
        "",
        f"The source is cp1252 and carries `£ ¥ €` plus accented names; the CSV is "
        f"written **UTF-8 with BOM** so Excel and Google Sheets auto-detect it.",
        "",
        "## 5. Purse source",
        "",
        "Three policies, selected with `--purse-source`:",
        "",
        "| Mode | Rule |",
        "|---|---|",
        "| `site` | always IFHA's own contemporaneous `(*$USD)` figure |",
        "| `normalized` | always `normalize.py`'s ECB annual-average conversion |",
        "| `hybrid` **(default)** | IFHA's figure, except fall back to the "
        "normalized one where the two disagree by >25% **and** the normalized "
        "rate's provenance is `ecb` |",
        "",
        "Why hybrid: IFHA converted every 2015 Brazilian purse at ~2.657 BRL/USD "
        "— the **2014** average — when the 2015 ECB average was 3.336. The site "
        "figure is stale there and we have real ECB data to prove it.",
        "",
        _table(["Purse Source value", "Rows", "Meaning"], [
            [k, f"{v:,}", {
                "site": "IFHA's own USD figure",
                "normalized": "normalize.py's ECB conversion",
                "usd_native": "purse already in USD; no conversion needed",
                "normalized_stale_site": "**hybrid override** — IFHA's figure "
                                         "contradicted by real ECB data",
                "normalized_site_missing": "IFHA offered no USD figure",
                "site_normalized_missing": "no FX rate available for that currency/year",
                NA: "no purse figure at all",
            }.get(k, "")]
            for k, v in summary["purse_source_usage"].items()]),
        "",
        "## 6. Independent correctness spot-checks",
        "",
        "These compare the CSV against results the author knows independently of "
        "this pipeline. Agent 2 already verified 2015, so every fixture here is "
        "from another year.",
        "",
        _table(["Year", "Race (match)", "Expected winner", "Status",
                "Winner in CSV", "Date in CSV", "Note"], spot_rows),
        "",
        f"Tally: `{summary['spot_check_tally']}`",
        "",
        "## 7. Flagged rows",
        "",
        f"`validation_issues.csv` holds **{summary['validation_issues_total']:,}** "
        f"flagged rows:",
        "",
        _table(["Check", "Count"],
               [[k, f"{v:,}"] for k, v in summary["validation_issue_counts"].items()]
               or [["(none)", 0]]),
        "",
        "### Issues raised by the parser itself (Agent 2)",
        "",
        _table(["Issue", "Count"],
               [[k, f"{v:,}"] for k, v in summary["parser_issue_counts"].items()]
               or [["(none)", 0]]),
        "",
        "## 8. What you must know before trusting this dataset",
        "",
        "1. **Only the first three finishers exist.** IFHA publishes no 4th place "
        "or below, and no trainer, owner, sire, dam, winning time, margin, "
        "weight, odds or field size. None of that is recoverable from this "
        "source.",
        "2. **`racepid` is not a race identity.** It is kept as `race_id` because "
        "it ties the three finishers of a race together, but the same physical "
        "race can carry two pids. Join on `Date + Track + Race Name + Group` if "
        "you merge this with anything else.",
        "3. **2003 is a source-data gap, not a bug** — IFHA holds ~24 G2 and ~10 "
        "G3 races for that year. 2020 is genuinely short (COVID). 2026 is "
        "partial.",
        "4. **Purses are annual-average conversions, not race-day rates.** A few "
        "percent of drift is normal. Rates for ARS, CLP, PEN and UYU are "
        "hand-entered approximations, not a live feed — see `fx_provenance` in "
        "`parsed_records.jsonl`. Argentine purses in particular should not be "
        "used for anything financial.",
        "5. **A horse with no country suffix is bred in the publishing "
        "authority's own country** — usually the USA, but not always. Those rows "
        "show `N/A` in `Horse Country Suffix` rather than a guess.",
        "6. **Southern-Hemisphere ages** are the local official age. SH foals are "
        "aged from 1 August, so an AUS/NZ/SAF/ARG/BRZ/CHI horse can appear one "
        "year off against a Northern-Hemisphere reading.",
        "7. **IFHA's own disclaimer** says it takes no responsibility for the "
        "accuracy of these data; the figures come from member racing "
        "authorities. Check the site's terms before republishing.",
        "",
    ]
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cache_file_count(cache_dir: Path) -> int:
    return sum(1 for p in cache_dir.rglob("*") if p.is_file()) if cache_dir.is_dir() else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", default="2003-2026", help="e.g. 2015, 2003-2026")
    ap.add_argument("--purse-source", choices=PURSE_SOURCES, default="hybrid",
                    help="which USD purse figure to publish (default: hybrid)")
    ap.add_argument("--out", default=str(DELIVERABLE_PATH), help="the deliverable CSV")
    ap.add_argument("--repo-out", default=str(REPO_CSV_PATH), help="identical repo copy")
    ap.add_argument("--report-out", default=str(REPORT_PATH))
    ap.add_argument("--issues-out", default=str(ISSUES_PATH))
    ap.add_argument("--summary-out", default=str(SUMMARY_PATH))
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--limit", type=int, default=0, help="stop after N races")
    ap.add_argument("--provisional", action="store_true",
                    help="label the report PROVISIONAL (cache still filling)")
    ap.add_argument("--dry-run", action="store_true",
                    help="run every check and print the summary, write nothing")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    years = parse_years(args.years)
    result = validate(years, purse_source=args.purse_source,
                      cache_dir=args.cache_dir, limit=args.limit,
                      progress=not args.quiet)
    rows, findings, summary = result["rows"], result["findings"], result["summary"]

    cache_dir = Path(args.cache_dir) if args.cache_dir else ROOT / "cache"
    summary["cache_files"] = cache_file_count(cache_dir)
    summary["provisional"] = bool(args.provisional)

    if args.dry_run:
        print(json.dumps(summary, indent=2, default=str))
        return 0

    out = Path(args.out).expanduser()
    repo_out = Path(args.repo_out).expanduser()
    write_csv(rows, out)
    write_csv(rows, repo_out)
    write_csv(findings.issues, Path(args.issues_out), ISSUE_COLUMNS)
    Path(args.report_out).write_text(
        render_report(summary, findings, args.provisional, [out, repo_out],
                      summary["cache_files"]),
        encoding="utf-8")
    Path(args.summary_out).write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")

    print(json.dumps({k: summary[k] for k in (
        "purse_source_mode", "rows_before_dedup", "rows_written", "races_written",
        "duplicate_races_collapsed", "rows_dropped_by_dedup",
        "omitted_uncached_detail_rows",
        "purse_source_usage", "spot_check_tally", "validation_issues_total",
        "provisional", "cache_files")}, indent=2, default=str))
    print(f"\nwrote {len(rows)} rows -> {out}")
    print(f"wrote {len(rows)} rows -> {repo_out}")
    print(f"wrote {len(findings.issues)} flagged rows -> {args.issues_out}")
    print(f"wrote report -> {args.report_out}")

    failures = [s for s in summary["spot_checks"] if s["status"] == "fail"]
    if failures:
        print(f"\nWARNING: {len(failures)} spot check(s) FAILED", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
