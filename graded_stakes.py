"""Load the worldwide IFHA Group/Graded stakes CSV used by hypomating and sales.

The file ``graded_stakes_winners.csv`` is the IFHA worldwide results export
(one row per 1st/2nd/3rd), not the old USA-winners-only sheet. This module is
the single reader for that file.

Normalization
-------------
- ``Race Year`` is derived from ``Date (ISO)`` (``YYYY-MM-DD``), then ``Date``
  (``27 September 2025``), then an existing ``Race Year`` column if present.
- ``Grade`` is an alias of ``Group`` (G1/G2/G3) so older callers keep working.
- Literal ``N/A`` strings are treated as missing. Object columns are filled
  with ``""``; numeric columns are left numeric (no ``fillna('')``).
- Rows with Horse Name ``N/A`` / blank are dropped (races with no result).

Winner-only vs all finishers
----------------------------
Default ``winners_only=True`` keeps ``Place == 1`` only. Every existing
feature (hypomating "won the X edition" summaries, sale analyzer, API stakes
index) is winner-oriented.

Pass ``winners_only=False`` if a future feature genuinely needs 2nd/3rd.
"""

from __future__ import annotations

import os
import re

import pandas as pd

STAKES_CSV_NAME = "graded_stakes_winners.csv"
MISSING_NAMES = {"", "N/A", "NAN", "NONE", "<NA>"}

_DATE_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")

_cached_frames = {}
_cached_records = {}


def _default_csv_path():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.getcwd(), STAKES_CSV_NAME),
        os.path.join(here, STAKES_CSV_NAME),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[0]


def _year_from_iso(series):
    iso = series.astype("string").str.strip()
    return pd.to_numeric(iso.str.slice(0, 4), errors="coerce").astype("Int64")


def _year_from_date_text(series):
    parsed = pd.to_datetime(series, errors="coerce")
    years = parsed.dt.year.astype("Int64")
    if years.isna().any():
        extracted = series.astype("string").str.extract(_DATE_YEAR_RE, expand=False)
        years = years.fillna(pd.to_numeric(extracted, errors="coerce"))
    return years.astype("Int64")


def _derive_race_year(df):
    years = pd.Series(pd.NA, index=df.index, dtype="Int64")
    if "Date (ISO)" in df.columns:
        years = _year_from_iso(df["Date (ISO)"])
    if years.isna().any() and "Date" in df.columns:
        years = years.fillna(_year_from_date_text(df["Date"]))
    if years.isna().any() and "Race Year" in df.columns:
        years = years.fillna(pd.to_numeric(df["Race Year"], errors="coerce"))
    df = df.copy()
    df["Race Year"] = years.astype("Int64")
    return df


def _stringify_year_col(series):
    nums = pd.to_numeric(series, errors="coerce")
    out = pd.Series("", index=series.index, dtype="object")
    ok = nums.notna()
    out.loc[ok] = nums.loc[ok].round().astype(int).astype(str)
    return out


def _read_and_normalize(path):
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    df = df.replace(to_replace=r"^\s*N/A\s*$", value=pd.NA, regex=True)

    df = _derive_race_year(df)

    if "Group" in df.columns:
        df["Grade"] = df["Group"]
    elif "Grade" not in df.columns:
        df["Grade"] = pd.NA

    if "Place" in df.columns:
        df["Place"] = pd.to_numeric(df["Place"], errors="coerce").astype("Int64")

    if "Horse Name" in df.columns:
        names = df["Horse Name"].astype("string").str.strip()
        bad = names.isna() | names.str.upper().isin(MISSING_NAMES)
        df = df.loc[~bad].copy()
        df["Horse Name"] = df["Horse Name"].astype("string").str.strip()
    else:
        df = df.iloc[0:0].copy()

    if "Foaling Year" in df.columns:
        df["Foaling Year"] = _stringify_year_col(df["Foaling Year"])
    else:
        df["Foaling Year"] = ""

    for col in df.columns:
        if col in ("Race Year", "Place"):
            continue
        if pd.api.types.is_object_dtype(df[col]) or str(df[col].dtype) in ("string", "string[python]"):
            df[col] = df[col].astype("string").fillna("").str.strip()
            df[col] = df[col].replace({"<NA>": "", "nan": "", "None": "", "NaN": ""})

    return df.reset_index(drop=True)


def load_graded_stakes_dataframe(path=None, winners_only=True):
    """Return the normalized IFHA stakes DataFrame.

    Derived columns: ``Race Year`` (nullable Int64) and ``Grade`` (alias of
    ``Group``). Default is Place==1 winners only.
    """
    csv_path = path or _default_csv_path()
    if not os.path.isfile(csv_path):
        print(f"⚠️ Warning: {STAKES_CSV_NAME} not found.")
        return pd.DataFrame()

    cache_key = os.path.abspath(csv_path)
    if cache_key not in _cached_frames:
        _cached_frames[cache_key] = _read_and_normalize(csv_path)

    df = _cached_frames[cache_key]
    if winners_only and "Place" in df.columns:
        place = pd.to_numeric(df["Place"], errors="coerce")
        df = df.loc[place == 1]
    return df.copy()


def _records_from_frame(df):
    if df.empty:
        return []
    ready = df.copy()
    if "Race Year" in ready.columns:
        years = pd.to_numeric(ready["Race Year"], errors="coerce")
        ready["Race Year"] = [
            int(y) if pd.notna(y) else "" for y in years
        ]
    if "Place" in ready.columns:
        places = pd.to_numeric(ready["Place"], errors="coerce")
        ready["Place"] = [
            int(p) if pd.notna(p) else "" for p in places
        ]
    records = ready.to_dict("records")
    for rec in records:
        for key, value in list(rec.items()):
            if value is None:
                rec[key] = ""
            else:
                try:
                    if pd.isna(value):
                        rec[key] = ""
                except (TypeError, ValueError):
                    pass
    return records


def load_stakes_records(path=None, winners_only=True):
    """List-of-dicts form used by hypomating, sale analyzer, and the API."""
    csv_path = os.path.abspath(path or _default_csv_path())
    cache_key = (csv_path, bool(winners_only))
    if cache_key not in _cached_records:
        df = load_graded_stakes_dataframe(path=csv_path, winners_only=winners_only)
        _cached_records[cache_key] = _records_from_frame(df)
    return _cached_records[cache_key]


def load_stakes_data(path=None, winners_only=True):
    """Backward-compatible name: Place==1 winners from the IFHA CSV."""
    return load_stakes_records(path=path, winners_only=winners_only)
