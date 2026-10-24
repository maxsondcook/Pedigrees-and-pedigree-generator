"""
PriceProjection.py

Data-science module: relate yearling / weanling sale prices to the sire's
stud fee at covering (the nomination year that produced the foal), then
project expected sale price from a stallion's current stud fee.

Only YEARLING and WEANLING lots are included.
Missing stud fees are scraped from Racing Post and written into
stud_fee_database.json via fee_and_standing_location.
"""

from __future__ import annotations

import csv
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import fee_and_standing_location as fee_db

SEARCH_DIRS = [Path("sales_data"), Path(".")]
ROOT = Path(__file__).resolve().parent
FEE_BAND_CACHE_PATH = ROOT / "Analyzed Sales" / "expected_market_fee_bands.json"

# Stud-fee bands for empirical Expected Market Value (USD, half-open [lo, hi)).
FEE_BANDS: List[Tuple[int, Optional[int], str]] = [
    (0, 5_000, "under $5k"),
    (5_000, 10_000, "$5k–10k"),
    (10_000, 15_000, "$10k–15k"),
    (15_000, 25_000, "$15k–25k"),
    (25_000, 40_000, "$25k–40k"),
    (40_000, 60_000, "$40k–60k"),
    (60_000, 100_000, "$60k–100k"),
    (100_000, 150_000, "$100k–150k"),
    (150_000, 250_000, "$150k–250k"),
    (250_000, 500_000, "$250k–500k"),
    (500_000, None, "$500k+"),
]
MIN_BAND_N = 25


def safe_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def parse_price(val: Any) -> float:
    val_str = safe_str(val).upper()
    if not val_str or "OUT" in val_str or val_str == "-2.00":
        return 0.0
    cleaned = "".join(c for c in val_str if c.isdigit() or c == ".")
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def clean_title(filename: str) -> str:
    name = filename.replace(".csv", "").replace("_", " ")
    name = re.sub(r"\d{4}", "", name)
    name = name.replace("()", "").replace("[]", "").replace("-", " ")
    return " ".join(name.split()).title()


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def covering_year_for_lot(sold_as: str, sale_year: int) -> int:
    """
    Nomination / covering year that produced this foal.

    Yearling sold in Y  -> covered in Y-2 (foaled Y-1)
    Weanling sold in Y  -> covered in Y-1 (foaled Y)
    """
    kind = (sold_as or "").strip().lower()
    if kind == "weanling":
        return int(sale_year) - 1
    return int(sale_year) - 2


def classify_lot(
    file_name: str,
    sex: str = "",
    sold_as: str = "",
    birth_year: Optional[int] = None,
    sale_year: Optional[int] = None,
) -> Optional[str]:
    """Return 'Yearling', 'Weanling', or None if the lot is out of scope."""
    fn = file_name.lower()
    sold = (sold_as or "").strip().upper()
    sex_u = (sex or "").strip().upper()

    if sold == "WEANLING" or "WEANLING" in sex_u:
        return "Weanling"
    if "weanling" in fn and "yearling" not in fn:
        return "Weanling"

    # Explicit yearling catalogs (including mixed titles that contain yearling)
    if "yearling" in fn:
        # Mixed November-style catalogs are handled via SoldAs above.
        # For pure / named yearling sales, every offered lot is a yearling.
        if any(tok in fn for tok in ("breeding stock", "horses of all ages", "mixed")):
            if birth_year and sale_year and int(sale_year) - int(birth_year) == 1:
                return "Yearling"
            if sold and "YEARLING" in sold:
                return "Yearling"
            return None
        return "Yearling"

    if birth_year and sale_year:
        age = int(sale_year) - int(birth_year)
        if age == 0:
            return "Weanling"
        if age == 1:
            return "Yearling"

    if sold and "YEARLING" in sold:
        return "Yearling"
    return None


def _header_map(fieldnames: Optional[Iterable[str]]) -> Dict[str, str]:
    return {k.lower().strip(): k for k in (fieldnames or [])}


def _pick(headers: Dict[str, str], *aliases: str) -> Optional[str]:
    for a in aliases:
        if a in headers:
            return headers[a]
    return None


# ---------------------------------------------------------------------------
# Sales ingest (yearlings + weanlings only)
# ---------------------------------------------------------------------------

def iter_yearling_weanling_sales(
    sales_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Walk sales CSVs and return sold yearling/weanling lots with sire + price."""
    roots = [sales_root] if sales_root else SEARCH_DIRS
    records: List[Dict[str, Any]] = []

    seen_files = set()
    for root in roots:
        if root is None or not root.exists():
            continue
        for path in sorted(root.glob("*.csv")):
            if path.name in seen_files:
                continue
            seen_files.add(path.name)
            records.extend(_load_yw_from_csv(path))
    return records


def _load_yw_from_csv(file_path: Path) -> List[Dict[str, Any]]:
    year_m = re.search(r"\d{4}", file_path.name)
    sale_year = int(year_m.group(0)) if year_m else None
    if not sale_year:
        return []

    sale_title = clean_title(file_path.name)
    out: List[Dict[str, Any]] = []

    try:
        with open(file_path, mode="r", encoding="utf-8-sig", errors="ignore") as f:
            sample = f.read(2048)
            f.seek(0)
            dialect = csv.excel_tab if "\t" in sample else csv.excel
            reader = csv.DictReader(f, dialect=dialect)
            headers = _header_map(reader.fieldnames)

            hip_key = _pick(headers, "hip number", "hip", "hip_no")
            name_key = _pick(headers, "horse", "horse name", "name", "description")
            sex_key = _pick(headers, "sex", "gender")
            price_key = _pick(headers, "sale price", "price", "final bid", "price_raw")
            purchaser_key = _pick(headers, "purchaser", "buyer", "buyer name")
            sire_key = _pick(headers, "sire")
            dam_key = _pick(headers, "dam")
            dob_key = _pick(
                headers, "year of birth", "birth year", "dob", "date of birth", "foaled"
            )
            sold_as_key = _pick(headers, "soldas", "sold as", "sold_as")

            for row in reader:
                if not any(row.values()):
                    continue

                raw_sire = safe_str(row.get(sire_key, "")) if sire_key else ""
                raw_dam = safe_str(row.get(dam_key, "")) if dam_key else ""
                raw_sex = safe_str(row.get(sex_key, "")).upper() if sex_key else ""
                raw_sold_as = safe_str(row.get(sold_as_key, "")) if sold_as_key else ""
                raw_dob = safe_str(row.get(dob_key, "")) if dob_key else ""
                birth_year = None
                if raw_dob:
                    ym = re.search(r"\d{4}", raw_dob)
                    if ym:
                        birth_year = int(ym.group(0))

                kind = classify_lot(
                    file_path.name,
                    sex=raw_sex,
                    sold_as=raw_sold_as,
                    birth_year=birth_year,
                    sale_year=sale_year,
                )
                if kind is None:
                    continue

                raw_price = safe_str(row.get(price_key, "0")) if price_key else "0"
                raw_purchaser = (
                    safe_str(row.get(purchaser_key, "")).upper() if purchaser_key else ""
                )
                price_upper = raw_price.upper()
                is_out = "OUT" in raw_purchaser or "OUT" in price_upper
                is_rna = (
                    "NOT SOLD" in raw_purchaser
                    or "RNA" in raw_purchaser
                    or "R.N.A." in raw_purchaser
                    or "RNA" in price_upper
                    or "R.N.A." in price_upper
                    or raw_price.strip() == "-2.00"
                )
                price_num = parse_price(raw_price)
                if is_out or is_rna or price_num <= 0:
                    continue

                if not raw_sire:
                    continue

                hip_val = safe_str(row.get(hip_key, "N/A")) if hip_key else "N/A"
                if hip_val.isdigit():
                    hip_val = hip_val.zfill(4)

                cover_year = covering_year_for_lot(kind, sale_year)
                out.append(
                    {
                        "sale_title": sale_title,
                        "sale_year": sale_year,
                        "hip": hip_val,
                        "name": safe_str(row.get(name_key, "")) if name_key else "",
                        "sex": raw_sex,
                        "sire": raw_sire,
                        "dam": raw_dam,
                        "birth_year": birth_year,
                        "sold_as": kind,
                        "covering_year": cover_year,
                        "price": float(price_num),
                        "source_file": file_path.name,
                    }
                )
    except FileNotFoundError:
        return []
    return out


# ---------------------------------------------------------------------------
# Fee attachment
# ---------------------------------------------------------------------------

def attach_stud_fees(
    lots: List[Dict[str, Any]],
    *,
    scrape_missing: bool = True,
    max_scrapes: Optional[int] = None,
    progress_every: int = 25,
    fee_year_field: str = "covering_year",
    allow_nearest_prior: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Attach stud fee to each lot for ``fee_year_field`` (covering_year or sale_year).

    BloodHorse CSV + JSON are consulted first (no network). Scrapes Racing Post
    only when ``scrape_missing`` is True and the year is still unknown.
    """
    db = fee_db.load_fee_database()
    fee_db.load_csv_fee_history()
    enriched: List[Dict[str, Any]] = []
    stats = {
        "lots": len(lots),
        "matched": 0,
        "missing_fee": 0,
        "scrapes_ok": 0,
        "scrapes_fail": 0,
        "cache_hits": 0,
        "fee_year_field": fee_year_field,
    }

    # Deduplicate scrape attempts by normalized sire
    scrape_budget = max_scrapes if max_scrapes is not None else 10**9
    failed_sires = set()

    needed = {}
    for lot in lots:
        year_val = lot.get(fee_year_field) or lot.get("covering_year")
        if year_val is None:
            continue
        key = (fee_db._norm_name(lot["sire"]), int(year_val))
        needed.setdefault(key, lot["sire"])

    fee_cache: Dict[Tuple[str, int], Optional[int]] = {}
    for (norm, year), display_name in sorted(needed.items(), key=lambda x: (x[0][0], x[0][1])):
        cached = fee_db.get_fee_for_year(
            display_name, year, db, allow_nearest_prior=allow_nearest_prior
        )
        if cached is not None:
            fee_cache[(norm, year)] = cached
            stats["cache_hits"] += 1
            continue

        if not scrape_missing or norm in failed_sires or scrape_budget <= 0:
            fee_cache[(norm, year)] = None
            continue

        fee, db, note = fee_db.ensure_fee_for_year(
            display_name, year, db=db, scrape_if_missing=True, persist=True
        )
        scrape_budget -= 1
        if note == "scraped" or (note == "scraped_no_year" and fee is not None):
            stats["scrapes_ok"] += 1
        elif note not in ("cache", "missing"):
            stats["scrapes_fail"] += 1
            failed_sires.add(norm)
        # Re-resolve so CSV / plausibility filters still apply after scrape.
        fee_cache[(norm, year)] = fee_db.get_fee_for_year(
            display_name, year, db, allow_nearest_prior=allow_nearest_prior
        ) or fee

        if progress_every and (stats["scrapes_ok"] + stats["scrapes_fail"]) % progress_every == 0:
            print(
                f"  … scraped {stats['scrapes_ok']} ok / {stats['scrapes_fail']} fail "
                f"(budget left ~{scrape_budget})"
            )

    for lot in lots:
        norm = fee_db._norm_name(lot["sire"])
        year_val = lot.get(fee_year_field) or lot.get("covering_year")
        fee = fee_cache.get((norm, int(year_val))) if year_val is not None else None
        row = dict(lot)
        row["stud_fee"] = fee
        row["fee_year"] = int(year_val) if year_val is not None else None
        row["price_to_fee"] = (row["price"] / fee) if fee and fee > 0 else None
        enriched.append(row)
        if fee:
            stats["matched"] += 1
        else:
            stats["missing_fee"] += 1

    return enriched, stats


def attach_sale_year_stud_fees(
    lots: List[Dict[str, Any]],
    *,
    scrape_missing: bool = False,
    max_scrapes: Optional[int] = 0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Attach sire stud fee as of the sale year (exact or nearest prior)."""
    return attach_stud_fees(
        lots,
        scrape_missing=scrape_missing,
        max_scrapes=max_scrapes,
        fee_year_field="sale_year",
        allow_nearest_prior=True,
    )


# ---------------------------------------------------------------------------
# Model / projection
# ---------------------------------------------------------------------------

def _safe_median(values: List[float]) -> Optional[float]:
    return statistics.median(values) if values else None


def _safe_mean(values: List[float]) -> Optional[float]:
    return statistics.mean(values) if values else None


def fit_price_fee_model(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Fit simple projections from matched yearling/weanling sales:

    1) Median / mean price-to-fee multiple
    2) Log-log OLS: log(price) = a + b * log(fee)
    """
    usable = [
        r
        for r in rows
        if r.get("stud_fee") and r["stud_fee"] > 0 and r.get("price") and r["price"] > 0
    ]
    by_kind: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in usable:
        by_kind[r["sold_as"]].append(r)
        by_kind["All"].append(r)

    models: Dict[str, Any] = {}
    for kind, subset in by_kind.items():
        multiples = [r["price"] / r["stud_fee"] for r in subset]
        log_x = [math.log(r["stud_fee"]) for r in subset]
        log_y = [math.log(r["price"]) for r in subset]
        slope, intercept = _ols(log_x, log_y)
        models[kind] = {
            "n": len(subset),
            "median_multiple": _safe_median(multiples),
            "mean_multiple": _safe_mean(multiples),
            "log_slope": slope,
            "log_intercept": intercept,
            "median_price": _safe_median([r["price"] for r in subset]),
            "median_fee": _safe_median([r["stud_fee"] for r in subset]),
        }
    return {"n_matched": len(usable), "by_kind": models}


def _ols(xs: List[float], ys: List[float]) -> Tuple[Optional[float], Optional[float]]:
    n = len(xs)
    if n < 2:
        return None, None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x <= 0:
        return None, None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = cov / var_x
    intercept = mean_y - slope * mean_x
    return slope, intercept


def project_price(
    current_fee: float,
    model: Dict[str, Any],
    sold_as: str = "Yearling",
) -> Dict[str, Any]:
    """Project sale price from a stallion's current stud fee."""
    kind_models = model.get("by_kind", {})
    block = kind_models.get(sold_as) or kind_models.get("All")
    if not block:
        return {"error": "No fitted model available. Attach fees to sales first."}

    fee = float(current_fee)
    out = {
        "sold_as": sold_as,
        "current_fee": fee,
        "n": block["n"],
        "median_multiple": block["median_multiple"],
        "mean_multiple": block["mean_multiple"],
    }
    if block["median_multiple"] is not None:
        out["proj_median_multiple"] = fee * block["median_multiple"]
    if block["mean_multiple"] is not None:
        out["proj_mean_multiple"] = fee * block["mean_multiple"]
    if block["log_slope"] is not None and block["log_intercept"] is not None and fee > 0:
        out["proj_loglog"] = math.exp(block["log_intercept"] + block["log_slope"] * math.log(fee))
    return out


# ---------------------------------------------------------------------------
# Empirical Expected Market Value (fee-at-sale bands → hammer percentiles)
# ---------------------------------------------------------------------------

def fee_band_for(fee: float) -> Tuple[int, Optional[int], str]:
    fee_i = int(fee)
    for lo, hi, label in FEE_BANDS:
        if hi is None:
            if fee_i >= lo:
                return lo, hi, label
        elif lo <= fee_i < hi:
            return lo, hi, label
    return FEE_BANDS[-1]


def _percentile(sorted_vals: List[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    idx = (len(sorted_vals) - 1) * p
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return float(sorted_vals[lo])
    w = idx - lo
    return float(sorted_vals[lo] * (1 - w) + sorted_vals[hi] * w)


def _band_key(lo: int, hi: Optional[int]) -> str:
    return f"{lo}-{hi if hi is not None else 'up'}"


def fit_fee_band_model(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Empirical sale-price ranges by sire stud-fee band (fee at sale year).

    Exclusions: RNA / OUT / non-positive hammer (already dropped in ingest),
    missing / implausible stud fee. Range = p25–p75; mid = p50.
    """
    usable = [
        r
        for r in rows
        if r.get("stud_fee") and r["stud_fee"] > 0 and r.get("price") and r["price"] > 0
    ]
    prices: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    multiples: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for r in usable:
        lo, hi, _label = fee_band_for(r["stud_fee"])
        key = _band_key(lo, hi)
        price = float(r["price"])
        mult = price / float(r["stud_fee"])
        prices[r["sold_as"]][key].append(price)
        prices["All"][key].append(price)
        multiples[r["sold_as"]][key].append(mult)
        multiples["All"][key].append(mult)

    by_kind: Dict[str, Dict[str, Any]] = {}
    for kind, band_map in prices.items():
        bands_out: Dict[str, Any] = {}
        for lo, hi, label in FEE_BANDS:
            key = _band_key(lo, hi)
            vals = sorted(band_map.get(key) or [])
            if not vals:
                continue
            mults = multiples[kind].get(key) or []
            bands_out[key] = {
                "lo": lo,
                "hi": hi,
                "label": label,
                "n": len(vals),
                "p10": _percentile(vals, 0.10),
                "p25": _percentile(vals, 0.25),
                "p50": _percentile(vals, 0.50),
                "p75": _percentile(vals, 0.75),
                "p90": _percentile(vals, 0.90),
                "median_multiple": _safe_median(mults),
                "mean_multiple": _safe_mean(mults),
            }
        by_kind[kind] = bands_out

    sale_years = sorted({int(r["sale_year"]) for r in usable if r.get("sale_year")})
    return {
        "method": "empirical_fee_band_percentiles",
        "fee_basis": "sire_stud_fee_at_sale_year",
        "range": "p25-p75",
        "mid": "p50",
        "exclusions": "RNA, OUT, non-positive hammer, missing/implausible stud fee (>$1M)",
        "n_sales_total": len(rows),
        "n_matched": len(usable),
        "match_rate": (len(usable) / len(rows)) if rows else 0.0,
        "sale_years": sale_years,
        "min_band_n": MIN_BAND_N,
        "bands_def": [
            {"lo": lo, "hi": hi, "label": label, "key": _band_key(lo, hi)}
            for lo, hi, label in FEE_BANDS
        ],
        "by_kind": by_kind,
    }


def _pick_band_block(
    band_model: Dict[str, Any],
    fee: float,
    sold_as: str,
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """Return (block, kind_used, band_key), widening to All / neighbors if sparse."""
    lo, hi, _label = fee_band_for(fee)
    key = _band_key(lo, hi)
    by_kind = band_model.get("by_kind") or {}
    min_n = int(band_model.get("min_band_n") or MIN_BAND_N)
    keys = [_band_key(a, b) for a, b, _ in FEE_BANDS]
    try:
        idx = keys.index(key)
    except ValueError:
        idx = 0

    for kind in (sold_as, "All"):
        kind_bands = by_kind.get(kind) or {}
        block = kind_bands.get(key)
        if block and block.get("n", 0) >= min_n:
            return block, kind, key
        for j in (idx - 1, idx + 1, idx - 2, idx + 2):
            if j < 0 or j >= len(keys):
                continue
            neighbor = kind_bands.get(keys[j])
            if neighbor and neighbor.get("n", 0) >= min_n:
                return neighbor, kind, keys[j]

    for kind in (sold_as, "All"):
        block = (by_kind.get(kind) or {}).get(key)
        if block and block.get("n", 0) > 0:
            return block, kind, key
    return None, sold_as, key


def project_from_fee_band(
    fee: float,
    band_model: Dict[str, Any],
    sold_as: str = "Yearling",
) -> Dict[str, Any]:
    """Expected Market Value from empirical fee-band sale-price percentiles."""
    if not band_model or not fee or fee <= 0:
        return {"ok": False, "error": "fee or band model unavailable"}

    block, kind_used, key = _pick_band_block(band_model, fee, sold_as)
    if not block:
        return {"ok": False, "error": "no band coverage", "current_fee": fee, "sold_as": sold_as}

    low = block.get("p25")
    mid = block.get("p50")
    high = block.get("p75")
    if low and high and high < low:
        low, high = high, low
    label = ""
    if low and high:
        label = f"${int(round(low)):,} – ${int(round(high)):,}"
    elif mid:
        label = f"${int(round(mid)):,}"
        low = high = mid

    band_label = block.get("label") or key
    return {
        "ok": bool(label),
        "sold_as": sold_as,
        "kind_used": kind_used,
        "current_fee": float(fee),
        "band_key": key,
        "band_label": band_label,
        "band_lo": block.get("lo"),
        "band_hi": block.get("hi"),
        "n": block.get("n"),
        "n_matched": band_model.get("n_matched"),
        "match_rate": band_model.get("match_rate"),
        "p10": block.get("p10"),
        "p25": low,
        "p50": mid,
        "p75": high,
        "p90": block.get("p90"),
        "low": low,
        "mid": mid,
        "high": high,
        "point": mid,
        "label": label,
        "median_multiple": block.get("median_multiple"),
        "mean_multiple": block.get("mean_multiple"),
        "method": band_model.get("method"),
        "fee_basis": band_model.get("fee_basis"),
        "rule": (
            f"Historical sales × fee-at-sale · {band_label} band · "
            f"n={block.get('n'):,} · p25–p75"
        ),
    }


def build_fee_band_dataset(
    *,
    scrape_missing: bool = False,
    max_scrapes: Optional[int] = 0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    """Load Y/W sales, attach sale-year fees, fit empirical fee-band ranges."""
    print("\nLoading yearling & weanling sales for fee-band model…")
    lots = iter_yearling_weanling_sales()
    print(f"  Found {len(lots):,} sold yearling/weanling lots.")
    print("Matching sale-year stud fees (CSV + JSON, nearest prior)…")
    enriched, stats = attach_sale_year_stud_fees(
        lots, scrape_missing=scrape_missing, max_scrapes=max_scrapes
    )
    print(
        f"  Matched fees: {stats['matched']:,} | Missing: {stats['missing_fee']:,} | "
        f"Cache hits: {stats['cache_hits']:,}"
    )
    model = fit_fee_band_model(enriched)
    return enriched, stats, model


def save_fee_band_model(model: Dict[str, Any], path: Optional[Path] = None) -> Path:
    import json

    path = path or FEE_BAND_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    return path


def load_fee_band_model(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    import json

    path = path or FEE_BAND_CACHE_PATH
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def summarize_sire_history(
    rows: List[Dict[str, Any]],
    stallion: str,
) -> Dict[str, Any]:
    norm = fee_db._norm_name(stallion)
    subset = [r for r in rows if fee_db._norm_name(r["sire"]) == norm and r.get("stud_fee")]
    if not subset:
        return {"stallion": stallion, "n": 0}

    prices = [r["price"] for r in subset]
    multiples = [r["price"] / r["stud_fee"] for r in subset if r["stud_fee"]]
    return {
        "stallion": stallion,
        "n": len(subset),
        "median_price": _safe_median(prices),
        "mean_price": _safe_mean(prices),
        "median_multiple": _safe_median(multiples),
        "mean_multiple": _safe_mean(multiples),
        "years": sorted({r["sale_year"] for r in subset}),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _money(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"${int(round(v)):,}"


def _fmt_multiple(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"{v:.2f}x"


def build_dataset(
    *,
    scrape_missing: bool = False,
    max_scrapes: Optional[int] = 50,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    print("\nLoading yearling & weanling sales…")
    lots = iter_yearling_weanling_sales()
    print(f"  Found {len(lots):,} sold yearling/weanling lots.")
    print("Matching covering-year stud fees…")
    enriched, stats = attach_stud_fees(
        lots,
        scrape_missing=scrape_missing,
        max_scrapes=max_scrapes,
    )
    print(
        f"  Matched fees: {stats['matched']:,} | Missing: {stats['missing_fee']:,} | "
        f"Cache hits: {stats['cache_hits']:,} | "
        f"Scraped ok/fail: {stats['scrapes_ok']}/{stats['scrapes_fail']}"
    )
    model = fit_price_fee_model(enriched)
    return enriched, stats, model


def print_model_summary(model: Dict[str, Any]) -> None:
    print("\n=======================================================")
    print("         PRICE ↔ STUD FEE MODEL (YRLG / WNLG)         ")
    print("=======================================================")
    print(f"Matched sales used: {model.get('n_matched', 0):,}")
    print(f"{'Segment':<12} {'N':>8} {'Med Multiple':>14} {'Mean Multiple':>14} {'Log Slope':>10}")
    print("-" * 62)
    for kind, block in model.get("by_kind", {}).items():
        slope = block["log_slope"]
        slope_s = f"{slope:.3f}" if slope is not None else "n/a"
        print(
            f"{kind:<12} {block['n']:>8,} {_fmt_multiple(block['median_multiple']):>14} "
            f"{_fmt_multiple(block['mean_multiple']):>14} {slope_s:>10}"
        )
    print("=======================================================")
    print("Covering year = sale_year-2 (yearlings) / sale_year-1 (weanlings).")
    print("Projection uses these multiples against a stallion's CURRENT fee.")


def run_projection_prompt(model: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    name = input("\nStallion name for projection: ").strip()
    if not name:
        return

    db = fee_db.load_fee_database()
    current = fee_db.get_current_fee(name, db)
    if current is None:
        print("Current stud fee not in database — trying Racing Post…")
        scraped = fee_db.scrape_racing_post_fee_history(name)
        if scraped["ok"]:
            fee_db.upsert_fee_history(
                name,
                scraped["fees_by_year"],
                farm=scraped.get("farm"),
                racing_post_id=scraped.get("horse_id"),
                racing_post_slug=scraped.get("slug"),
                usd_years=scraped.get("usd_years"),
            )
            current = fee_db.get_current_fee(name)
        else:
            print(f"  Could not scrape fee: {scraped.get('error')}")

    if current is None:
        manual = input("Enter current stud fee manually (digits only, or blank to cancel): ").strip()
        current = fee_db.parse_fee_value(manual)
        if current is None:
            return
        fee_db.upsert_fee_history(name, {2026: current})

    kind = input("Project as [1] Yearling (default) or [2] Weanling: ").strip()
    sold_as = "Weanling" if kind == "2" else "Yearling"
    proj = project_price(current, model, sold_as=sold_as)
    hist = summarize_sire_history(rows, name)

    print("\n---------------- Projection ----------------")
    print(f"Stallion          : {name}")
    print(f"Current stud fee  : {_money(current)}")
    print(f"Segment           : {sold_as}")
    print(f"Model sample size : {proj.get('n', 0):,}")
    print(f"Median multiple   : {_fmt_multiple(proj.get('median_multiple'))}")
    print(f"Proj @ median x   : {_money(proj.get('proj_median_multiple'))}")
    print(f"Proj @ mean x     : {_money(proj.get('proj_mean_multiple'))}")
    print(f"Proj log-log OLS  : {_money(proj.get('proj_loglog'))}")
    if hist.get("n"):
        print(
            f"This sire history : n={hist['n']:,} | "
            f"med price {_money(hist['median_price'])} | "
            f"med multiple {_fmt_multiple(hist['median_multiple'])}"
        )
    print("--------------------------------------------")


def scrape_missing_for_dataset(rows: List[Dict[str, Any]], max_scrapes: int = 100) -> None:
    missing_sires = sorted(
        {
            r["sire"]
            for r in rows
            if not r.get("stud_fee")
        },
        key=lambda s: fee_db._norm_name(s),
    )
    print(f"\nUnique sires still missing a covering fee on ≥1 lot: {len(missing_sires)}")
    if not missing_sires:
        return
    limit = input(f"Scrape up to how many sires? [{max_scrapes}]: ").strip()
    try:
        max_scrapes = int(limit) if limit else max_scrapes
    except ValueError:
        pass

    db = fee_db.load_fee_database()
    ok = fail = 0
    for i, sire in enumerate(missing_sires[:max_scrapes], 1):
        print(f"[{i}/{min(max_scrapes, len(missing_sires))}] {sire}…", end=" ", flush=True)
        scraped = fee_db.scrape_racing_post_fee_history(sire)
        if scraped["ok"]:
            fee_db.upsert_fee_history(
                sire,
                scraped["fees_by_year"],
                farm=scraped.get("farm"),
                racing_post_id=scraped.get("horse_id"),
                racing_post_slug=scraped.get("slug"),
                usd_years=scraped.get("usd_years"),
                db=db,
                persist=True,
            )
            ok += 1
            print(f"ok ({len(scraped['fees_by_year'])} years)")
        else:
            fail += 1
            print(f"fail ({scraped.get('error')})")
    print(f"Done. Scraped ok={ok} fail={fail}. Re-run build to refresh matches.")


def export_matched_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    matched = [r for r in rows if r.get("stud_fee")]
    fields = [
        "sale_year",
        "sale_title",
        "hip",
        "name",
        "sold_as",
        "sire",
        "dam",
        "covering_year",
        "stud_fee",
        "price",
        "price_to_fee",
        "source_file",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in matched:
            writer.writerow(r)
    print(f"Wrote {len(matched):,} matched rows → {path}")


def run_price_projection_menu() -> None:
    enriched: List[Dict[str, Any]] = []
    model: Dict[str, Any] = {"n_matched": 0, "by_kind": {}}

    while True:
        print("\n==================================")
        print("       Price Projection           ")
        print("==================================")
        print("[1] Build yearling/weanling dataset (use cached fees)")
        print("[2] Build dataset + scrape missing fees from Racing Post")
        print("[3] Show price ↔ stud-fee model summary")
        print("[4] Project sale price from a stallion's current fee")
        print("[5] Scrape missing stallion fees into stud fee database")
        print("[6] Export matched sales CSV")
        print("----------------------------------")
        print("[X] Return")

        choice = input("\nSelect Option: ").strip().lower()
        if choice in ("x", ""):
            break
        elif choice == "1":
            enriched, _, model = build_dataset(scrape_missing=False)
            print_model_summary(model)
        elif choice == "2":
            cap = input("Max Racing Post scrapes this run [40]: ").strip()
            try:
                max_scrapes = int(cap) if cap else 40
            except ValueError:
                max_scrapes = 40
            enriched, _, model = build_dataset(scrape_missing=True, max_scrapes=max_scrapes)
            print_model_summary(model)
        elif choice == "3":
            if not model.get("n_matched"):
                print("Build the dataset first (option 1 or 2).")
                continue
            print_model_summary(model)
        elif choice == "4":
            if not model.get("n_matched"):
                print("Build the dataset first (option 1 or 2).")
                continue
            run_projection_prompt(model, enriched)
        elif choice == "5":
            if not enriched:
                print("Build the dataset first so we know which fees are missing.")
                continue
            scrape_missing_for_dataset(enriched)
        elif choice == "6":
            if not enriched:
                print("Build the dataset first (option 1 or 2).")
                continue
            out = Path("Analyzed Sales") / "price_projection_matched.csv"
            out.parent.mkdir(parents=True, exist_ok=True)
            export_matched_csv(enriched, out)
        else:
            print("Invalid selection.")


if __name__ == "__main__":
    run_price_projection_menu()
