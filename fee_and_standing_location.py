"""
Horse Fee Database

Stores current and historical stud fees by stallion / nomination year.
Scraped Racing Post fee-history rows are persisted to stud_fee_database.json.
"""

from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote_plus

DB_PATH = Path(__file__).resolve().parent / "stud_fee_database.json"
ROOT = Path(__file__).resolve().parent
CSV_FEE_PATHS = [
    ROOT / "stud_fee_database.csv",
    ROOT / "stallion_rankings_data" / "stud_fee_database.csv",
]
# Fees above this are almost always bad scrapes / FX artifacts (e.g. ¥ mislabeled as $).
MAX_PLAUSIBLE_USD_FEE = 1_000_000

_CSV_FEE_HISTORY: Optional[Dict[str, Dict[int, int]]] = None

# Seed map of common US sires so fee scrapes work even when web search is flaky.
KNOWN_RACING_POST_IDS = {
    "into mischief": ("693584", "into-mischief"),
    "munnings": ("715172", "munnings"),
    "american pharoah": ("868021", "american-pharoah"),
    "gun runner": ("901222", "gun-runner"),
    "not this time": ("1144336", "not-this-time"),
    "twirling candy": ("763225", "twirling-candy"),
    "candy ride": ("584425", "candy-ride"),
    "candy ride arg": ("584425", "candy-ride"),
    "cairo prince": ("848525", "cairo-prince"),
    "violence": ("823948", "violence"),
    "union rags": ("791717", "union-rags"),
    "good magic": ("1655024", "good-magic"),
    "bolt doro": ("1610707", "bolt-doro"),
    "bolt d oro": ("1610707", "bolt-doro"),
    "mendelssohn": ("1478674", "mendelssohn"),
    "uncle mo": ("768597", "uncle-mo"),
    "curlin": ("675528", "curlin"),
    "quality road": ("727653", "quality-road"),
    "constitution": ("857515", "constitution"),
    "practical joke": ("1086206", "practical-joke"),
    "nyquist": ("896792", "nyquist"),
    "hard spun": ("671451", "hard-spun"),
    "street sense": ("664565", "street-sense"),
    "liams map": ("875552", "liams-map"),
    "liam s map": ("875552", "liams-map"),
    "macleans music": ("1030825", "macleans-music"),
    "maclean s music": ("1030825", "macleans-music"),
}

# Prefer curl_cffi (TLS fingerprint) so Racing Post does not 406 us.
try:
    from curl_cffi import requests as http
    _IMPERSONATE = "chrome120"
except ImportError:  # pragma: no cover - fallback for bare installs
    import requests as http
    _IMPERSONATE = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


def _norm_name(name: str) -> str:
    if not name:
        return ""
    cleaned = re.sub(r"\(.*?\)", "", str(name))
    cleaned = cleaned.replace(".", "").replace("'", "").replace(",", "")
    return " ".join(cleaned.lower().split()).strip()


def _slugify(name: str) -> str:
    s = re.sub(r"\(.*?\)", "", str(name)).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _request(url: str, **kwargs):
    kwargs.setdefault("timeout", 45)
    if _IMPERSONATE:
        kwargs.setdefault("impersonate", _IMPERSONATE)
    return http.get(url, **kwargs)


def load_fee_database(path: Path = DB_PATH) -> Dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    # Normalize keys on load
    return {_norm_name(k): v for k, v in raw.items()}


def save_fee_database(db: Dict[str, dict], path: Path = DB_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = dict(sorted(db.items(), key=lambda kv: kv[0]))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=2, sort_keys=True)


def _ensure_entry(db: Dict[str, dict], stallion: str) -> dict:
    key = _norm_name(stallion)
    if key not in db:
        db[key] = {
            "farm": None,
            "status": "active",
            "fees_by_year": {},
            "current_fee": None,
            "racing_post_id": None,
            "racing_post_slug": None,
        }
    entry = db[key]
    entry.setdefault("fees_by_year", {})
    entry.setdefault("current_fee", None)
    entry.setdefault("racing_post_id", None)
    entry.setdefault("racing_post_slug", None)
    return entry


def parse_fee_value(raw: Any) -> Optional[int]:
    """Parse stud fee scalars; Private / YTBA / blank -> None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw) if raw else None
    text = str(raw).strip()
    if not text:
        return None
    low = text.lower()
    if any(tok in low for tok in ("private", "n/a", "tba", "yet to", "undisclosed")):
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _plausible_fee(fee: Optional[int]) -> Optional[int]:
    if fee is None or fee <= 0:
        return None
    if fee > MAX_PLAUSIBLE_USD_FEE:
        return None
    return int(fee)


def load_csv_fee_history(force: bool = False) -> Dict[str, Dict[int, int]]:
    """BloodHorse / rankings CSV: stallion -> {year: fee}. Cached in-process."""
    global _CSV_FEE_HISTORY
    if _CSV_FEE_HISTORY is not None and not force:
        return _CSV_FEE_HISTORY

    out: Dict[str, Dict[int, int]] = {}
    path = next((p for p in CSV_FEE_PATHS if p.exists()), None)
    if path is None:
        _CSV_FEE_HISTORY = {}
        return _CSV_FEE_HISTORY

    with open(path, encoding="utf-8-sig", errors="ignore") as f:
        for row in csv.DictReader(f):
            name = _norm_name(row.get("Stallion") or "")
            try:
                year = int(str(row.get("Year") or "").strip())
            except (TypeError, ValueError):
                continue
            fee = _plausible_fee(parse_fee_value(row.get("Stud Fee")))
            if not name or not year or not fee:
                continue
            out.setdefault(name, {})[year] = fee

    _CSV_FEE_HISTORY = out
    return out


def _fee_from_json_entry(entry: dict, year: int) -> Optional[int]:
    fees = entry.get("fees_by_year") or {}
    raw = fees.get(str(year), fees.get(year))
    return _plausible_fee(parse_fee_value(raw))


def _nearest_prior_fee(year_map: Dict[int, int], year: int) -> Optional[int]:
    priors = [y for y in year_map if y <= year]
    if not priors:
        return None
    return _plausible_fee(year_map[max(priors)])


def get_fee_for_year(
    stallion: str,
    year: int,
    db: Optional[Dict[str, dict]] = None,
    *,
    allow_nearest_prior: bool = False,
) -> Optional[int]:
    """Return stud fee for a stallion in a given year.

    Preference: BloodHorse CSV exact → JSON exact → (optional) nearest prior
    from CSV then JSON. Implausible USD amounts (> $1M) are ignored.
    """
    year = int(year)
    key = _norm_name(stallion)
    csv_hist = load_csv_fee_history().get(key) or {}
    if year in csv_hist:
        return csv_hist[year]

    db = db if db is not None else load_fee_database()
    entry = db.get(key)
    if entry:
        exact = _fee_from_json_entry(entry, year)
        if exact:
            return exact

    if not allow_nearest_prior:
        return None

    prior_csv = _nearest_prior_fee(csv_hist, year)
    if prior_csv:
        return prior_csv

    if entry:
        fees = entry.get("fees_by_year") or {}
        year_map: Dict[int, int] = {}
        for y, raw in fees.items():
            try:
                yi = int(y)
            except (TypeError, ValueError):
                continue
            fee = _plausible_fee(parse_fee_value(raw))
            if fee:
                year_map[yi] = fee
        return _nearest_prior_fee(year_map, year)
    return None


def resolve_fee_at_sale(
    stallion: str,
    sale_year: Optional[int],
    db: Optional[Dict[str, dict]] = None,
) -> Optional[int]:
    """Sire stud fee as of the sale year (exact, else nearest prior ≤ sale year)."""
    if not stallion or not sale_year:
        return get_current_fee(stallion, db)
    return get_fee_for_year(
        stallion, int(sale_year), db, allow_nearest_prior=True
    ) or get_current_fee(stallion, db)


def get_current_fee(stallion: str, db: Optional[Dict[str, dict]] = None) -> Optional[int]:
    db = db if db is not None else load_fee_database()
    entry = db.get(_norm_name(stallion))
    key = _norm_name(stallion)

    # Prefer explicitly stored current USD fee when present
    if entry:
        current = _plausible_fee(parse_fee_value(entry.get("current_fee")))
        usd_years = entry.get("usd_fee_years") or []
        fees = entry.get("fees_by_year") or {}
        if usd_years:
            newest_usd = max(int(y) for y in usd_years)
            usd_fee = _plausible_fee(parse_fee_value(fees.get(str(newest_usd))))
            if usd_fee:
                return usd_fee
        if current:
            return current
        years = []
        for y in fees:
            try:
                years.append(int(y))
            except (TypeError, ValueError):
                continue
        if years:
            fee = _plausible_fee(parse_fee_value(fees[str(max(years))]))
            if fee:
                return fee

    csv_hist = load_csv_fee_history().get(key) or {}
    if csv_hist:
        return csv_hist[max(csv_hist)]
    return None


def upsert_fee_history(
    stallion: str,
    fees_by_year: Dict[int, Optional[int]],
    *,
    farm: Optional[str] = None,
    status: Optional[str] = None,
    racing_post_id: Optional[str] = None,
    racing_post_slug: Optional[str] = None,
    usd_years: Optional[list] = None,
    db: Optional[Dict[str, dict]] = None,
    persist: bool = True,
) -> Dict[str, dict]:
    """Merge year->fee rows into the stud fee database and optionally save."""
    db = db if db is not None else load_fee_database()
    entry = _ensure_entry(db, stallion)
    for year, fee in fees_by_year.items():
        if fee is None:
            continue
        entry["fees_by_year"][str(int(year))] = int(fee)
    if farm:
        entry["farm"] = farm
    if status:
        entry["status"] = status
    if racing_post_id:
        entry["racing_post_id"] = str(racing_post_id)
    if racing_post_slug:
        entry["racing_post_slug"] = racing_post_slug
    if usd_years:
        existing = {int(y) for y in (entry.get("usd_fee_years") or [])}
        existing.update(int(y) for y in usd_years)
        entry["usd_fee_years"] = sorted(existing)

    # Refresh current_fee from newest USD year when known, else newest year
    usd = [int(y) for y in (entry.get("usd_fee_years") or [])]
    years = [int(y) for y in entry["fees_by_year"] if str(y).isdigit()]
    if usd:
        newest = max(usd)
        entry["current_fee"] = entry["fees_by_year"].get(str(newest))
    elif years:
        newest = max(years)
        entry["current_fee"] = entry["fees_by_year"][str(newest)]
    if years:
        entry["status"] = entry.get("status") or "active"

    if persist:
        save_fee_database(db)
    return db


def resolve_racing_post_horse(stallion: str) -> Optional[Tuple[str, str]]:
    """
    Resolve Racing Post horse id + slug via seed map, then DuckDuckGo HTML search.
    Tries several query shapes because strict site: queries are often empty.
    Returns (horse_id, slug) or None.
    """
    name = stallion.strip()
    # Drop country suffixes for matching: "Candy Ride (ARG)" -> "Candy Ride"
    bare = re.sub(r"\s*\([^)]*\)\s*", " ", name).strip()
    seed = KNOWN_RACING_POST_IDS.get(_norm_name(name)) or KNOWN_RACING_POST_IDS.get(_norm_name(bare))
    if seed:
        return seed
    slug_guess = _slugify(bare)
    queries = [
        f'"{bare}" fee-history racingpost',
        f"{bare} fee-history site:racingpost.com",
        f'site:racingpost.com/profile/horse "{bare}" fee-history',
        f'site:racingpost.com/profile/horse "{bare}"',
        f"{bare} site:racingpost.com/profile/horse",
    ]
    if bare.lower() != name.lower():
        queries.append(f'"{name}" fee-history racingpost')

    pattern = re.compile(
        r"racingpost\.com/profile/horse/(\d+)/([a-z0-9-]+)",
        re.IGNORECASE,
    )
    tokens = [t for t in slug_guess.split("-") if t and t not in {"usa", "ire", "gb", "fr", "arg"}]

    for q in queries:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(q)}"
        try:
            resp = _request(url)
            candidates = pattern.findall(resp.text or "")
        except Exception:
            candidates = []
        if not candidates:
            time.sleep(0.25)
            continue

        for horse_id, slug in candidates:
            if slug == slug_guess:
                return horse_id, slug
        for horse_id, slug in candidates:
            if tokens and all(t in slug for t in tokens[: min(2, len(tokens))]):
                return horse_id, slug
        # Avoid obvious wrong progeny hits when possible
        horse_id, slug = candidates[0]
        if tokens and tokens[0] in slug:
            return horse_id, slug
        time.sleep(0.25)

    return None


def scrape_racing_post_fee_history(
    stallion: str,
    *,
    horse_id: Optional[str] = None,
    slug: Optional[str] = None,
    sleep_s: float = 0.75,
) -> Dict[str, Any]:
    """
    Scrape Racing Post fee-history for a stallion.

    Returns dict with keys: ok, stallion, horse_id, slug, fees_by_year, farm, error
    """
    result = {
        "ok": False,
        "stallion": stallion,
        "horse_id": horse_id,
        "slug": slug,
        "fees_by_year": {},
        "farm": None,
        "error": None,
    }

    if not horse_id or not slug:
        resolved = resolve_racing_post_horse(stallion)
        if not resolved:
            result["error"] = "Could not resolve Racing Post horse id"
            return result
        horse_id, slug = resolved
        result["horse_id"] = horse_id
        result["slug"] = slug

    url = f"https://www.racingpost.com/profile/horse/{horse_id}/{slug}/fee-history/"
    try:
        if sleep_s:
            time.sleep(sleep_s)
        resp = _request(url)
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code} for {url}"
            return result
        html = resp.text
    except Exception as exc:
        result["error"] = str(exc)
        return result

    fees: Dict[int, Optional[int]] = {}
    usd_years: list = []
    farm = None

    # Prefer embedded Next.js payload (stable)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            payload = json.loads(m.group(1))
            fh = (
                payload.get("props", {})
                .get("pageProps", {})
                .get("initialState", {})
                .get("horseProfile", {})
                .get("feeHistory", {})
                .get("data")
            )
            if isinstance(fh, list):
                for row in fh:
                    year = row.get("nominationYear")
                    if not year:
                        continue
                    year = int(year)
                    if row.get("isPrivate"):
                        continue
                    fee = parse_fee_value(row.get("studFee"))
                    if fee is None:
                        continue
                    country = str(row.get("countryDesc") or "").upper()
                    currency = str(row.get("currencyCode") or "").upper()
                    is_usa = ("U.S" in country) or ("USA" in country) or currency == "USD"
                    # Prefer USA/USD when a year already has a foreign row
                    if year in fees and not is_usa:
                        continue
                    fees[year] = fee
                    if is_usa and year not in usd_years:
                        usd_years.append(year)
                    if is_usa and row.get("studName"):
                        farm = row.get("studName")
                    elif not farm and row.get("studName"):
                        farm = row.get("studName")
        except Exception:
            pass

    # HTML table fallback
    if not fees and BeautifulSoup is not None:
        soup = BeautifulSoup(html, "lxml")
        for table in soup.find_all("table"):
            headers = [c.get_text(" ", strip=True).lower() for c in table.find_all("th")]
            if not headers or "year" not in " ".join(headers):
                continue
            for tr in table.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
                if len(cells) < 2:
                    continue
                year_m = re.search(r"(20\d{2})", cells[0])
                if not year_m:
                    continue
                year = int(year_m.group(1))
                fee_cell = cells[1]
                # Skip clearly non-USD rows in the fallback path
                if re.search(r"\b(JPY|EUR|GBP|AUD|NZD|ZAR)\b", fee_cell, re.I):
                    continue
                fee = parse_fee_value(fee_cell)
                if fee is not None:
                    fees[year] = fee
                    if year not in usd_years:
                        usd_years.append(year)
                if len(cells) >= 4 and cells[3] and not farm:
                    farm = cells[3]

    if not fees:
        result["error"] = "No fee history rows found on Racing Post page"
        return result

    result["ok"] = True
    result["fees_by_year"] = fees
    result["usd_years"] = usd_years
    result["farm"] = farm
    return result


def ensure_fee_for_year(
    stallion: str,
    year: int,
    *,
    db: Optional[Dict[str, dict]] = None,
    scrape_if_missing: bool = True,
    persist: bool = True,
) -> Tuple[Optional[int], Dict[str, dict], Optional[str]]:
    """
    Look up stud fee for stallion/year. If missing and scrape_if_missing,
    pull Racing Post history into the database.

    Returns (fee_or_None, db, note)
    """
    db = db if db is not None else load_fee_database()
    fee = get_fee_for_year(stallion, year, db)
    if fee is not None:
        return fee, db, "cache"

    if not scrape_if_missing:
        return None, db, "missing"

    entry = db.get(_norm_name(stallion)) or {}
    scraped = scrape_racing_post_fee_history(
        stallion,
        horse_id=entry.get("racing_post_id"),
        slug=entry.get("racing_post_slug"),
    )
    if not scraped["ok"]:
        return None, db, scraped.get("error") or "scrape_failed"

    db = upsert_fee_history(
        stallion,
        scraped["fees_by_year"],
        farm=scraped.get("farm"),
        racing_post_id=scraped.get("horse_id"),
        racing_post_slug=scraped.get("slug"),
        usd_years=scraped.get("usd_years"),
        db=db,
        persist=persist,
    )
    fee = get_fee_for_year(stallion, year, db)
    return fee, db, "scraped" if fee is not None else "scraped_no_year"


def get_stallion_info(user_wants: str) -> str:
    """Legacy interactive helper: describe current fee / farm / status."""
    stallions = load_fee_database()
    lookup_key = _norm_name(user_wants)
    data = stallions.get(lookup_key)
    if not data:
        return f"Error: '{user_wants}' not found in the stallion roster."

    fee = get_current_fee(lookup_key, stallions)
    if fee is None:
        formatted_fee = "a private fee"
    else:
        formatted_fee = f"a fee of ${fee:,}"

    farm = data.get("farm") or "an undisclosed farm"
    status = data.get("status") or "active"
    return f"{lookup_key.title()} is standing at {farm} for {formatted_fee} ({status})."


if __name__ == "__main__":
    q = input("Stallion name: ").strip()
    if q:
        print(get_stallion_info(q))
