"""Wire PriceProjection + ValueProjector into sales Expected Market / Market Prediction."""

from __future__ import annotations

import math
import re
import threading
from typing import Any, Dict, Optional

_LOCK = threading.Lock()
_PRICE_ROWS = None
_PRICE_MODEL = None
_BAND_MODEL = None
_PRICE_ERROR = None
_WARMED = False


def _money(amount: Optional[float]) -> str:
    if amount is None or (isinstance(amount, float) and (math.isnan(amount) or amount <= 0)):
        return ""
    return f"${int(round(amount)):,}"


def _fee_amount(raw: Any) -> int:
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


_NON_YW_TOKENS = (
    "BROODMARE",
    "RACING AGE",
    "RACING PROSPECT",
    "TWO-YEAR",
    "2-YEAR",
    "2YO",
    "THREE-YEAR",
    "HORSE OF RACING",
)


def foaling_age_years(birth_year: Any = None, sale_year: Any = None) -> Optional[int]:
    """Whole years of age at sale: sale_year − foal_year, or None if unknown."""
    by = _parse_sale_year(birth_year)
    sy = _parse_sale_year(sale_year)
    if by is None or sy is None:
        return None
    return int(sy) - int(by)


def kind_from_foaling_age(birth_year: Any = None, sale_year: Any = None) -> Optional[str]:
    """sale_year − foal_year: 0 → Weanling, 1 → Yearling; else None (2yo+ / unknown)."""
    age = foaling_age_years(birth_year, sale_year)
    if age is None:
        return None
    if age == 0:
        return "Weanling"
    if age == 1:
        return "Yearling"
    return None


def modal_catalog_kind(
    lots: Optional[list] = None,
    *,
    sale_year: Any = None,
) -> Optional[str]:
    """Most common Y/W kind among hips with a readable foaling age in this catalog."""
    from collections import Counter

    counts: Counter = Counter()
    for lot in lots or []:
        kind = kind_from_foaling_age(
            lot.get("birth_year") or lot.get("birth_date"),
            sale_year
            or lot.get("sale_year")
            or lot.get("catalog_year")
            or lot.get("year"),
        )
        if kind:
            counts[kind] += 1
    if not counts:
        return None
    # Prefer Yearling on ties (commercial select sales skew yearling).
    return sorted(counts.items(), key=lambda kv: (-kv[1], 0 if kv[0] == "Yearling" else 1))[0][0]


def _sold_as_kind(
    sold_as: str = "",
    catalog_title: str = "",
    sex: str = "",
    *,
    birth_year: Any = None,
    sale_year: Any = None,
    catalog_default_kind: Optional[str] = None,
) -> Optional[str]:
    """Return Yearling/Weanling for EMV / ValueProjector; else None.

    Order (Maxson): explicit non-Y/W role → foaling age vs sale year → explicit
    Y/W sold_as → catalog modal age (only if age unknown) → title keywords last.
    Known age ≥ 2 never inherits the catalog modal Yearling/Weanling default.
    """
    sold_u = (sold_as or "").strip().upper()
    if sold_u and any(tok in sold_u for tok in _NON_YW_TOKENS):
        return None

    age = foaling_age_years(birth_year, sale_year)
    if age is not None:
        if age == 0:
            return "Weanling"
        if age == 1:
            return "Yearling"
        # Known 2yo+ / older breeding stock — do not apply Y/W modal or title.
        return None

    if "WEANLING" in sold_u:
        return "Weanling"
    if "YEARLING" in sold_u:
        return "Yearling"

    if catalog_default_kind in ("Yearling", "Weanling"):
        return catalog_default_kind

    blob = f"{catalog_title} {sex}".upper()
    if any(tok in blob for tok in _NON_YW_TOKENS):
        return None
    if "WEANLING" in blob:
        return "Weanling"
    if "YEARLING" in blob:
        return "Yearling"
    return None


def annotate_lot_kinds(
    lots: Optional[list] = None,
    *,
    sale_year: Any = None,
    catalog_title: str = "",
) -> Optional[str]:
    """Stamp ``sold_as_kind`` / fill blank ``sold_as`` from age; return modal catalog kind."""
    lots = lots or []
    year = sale_year
    modal = modal_catalog_kind(lots, sale_year=year)
    for lot in lots:
        sy = (
            year
            or lot.get("sale_year")
            or lot.get("catalog_year")
            or lot.get("year")
        )
        kind = _sold_as_kind(
            lot.get("sold_as") or "",
            catalog_title or lot.get("catalog_title") or lot.get("sale_title") or "",
            lot.get("sex_letter") or lot.get("sex") or "",
            birth_year=lot.get("birth_year") or lot.get("birth_date"),
            sale_year=sy,
            catalog_default_kind=modal,
        )
        lot["sold_as_kind"] = kind
        lot["sale_year_resolved"] = _parse_sale_year(sy)
        lot["foaling_age"] = foaling_age_years(
            lot.get("birth_year") or lot.get("birth_date"), sy
        )
        if kind and not (lot.get("sold_as") or "").strip():
            lot["sold_as"] = kind
    return modal


def warm_price_model(force: bool = False) -> Dict[str, Any]:
    """Load empirical fee-band model from cache (rebuild only if missing/forced)."""
    global _PRICE_ROWS, _PRICE_MODEL, _BAND_MODEL, _PRICE_ERROR, _WARMED
    with _LOCK:
        if _WARMED and not force:
            return {
                "ready": _BAND_MODEL is not None,
                "n_matched": (_BAND_MODEL or {}).get("n_matched", 0),
                "error": _PRICE_ERROR,
                "source": "fee_band",
            }
        try:
            import PriceProjection as pp

            band = None if force else pp.load_fee_band_model()
            if band is None or not (band.get("by_kind") or {}):
                _rows, _stats, band = pp.build_fee_band_dataset(
                    scrape_missing=False, max_scrapes=0
                )
                pp.save_fee_band_model(band)
                _PRICE_ROWS = _rows
            _BAND_MODEL = band
            _PRICE_ERROR = None
        except Exception as exc:  # pragma: no cover
            _PRICE_ROWS = None
            _PRICE_MODEL = None
            _BAND_MODEL = None
            _PRICE_ERROR = str(exc)
        _WARMED = True
        return {
            "ready": _BAND_MODEL is not None,
            "n_matched": (_BAND_MODEL or {}).get("n_matched", 0),
            "error": _PRICE_ERROR,
            "source": "fee_band",
        }


def _model() -> Optional[Dict[str, Any]]:
    """Return multiple model only if already built (never blocks the request path)."""
    if not _WARMED:
        warm_price_model()
    return _PRICE_MODEL

def _band_model() -> Optional[Dict[str, Any]]:
    if not _WARMED:
        warm_price_model()
    return _BAND_MODEL


def _rows():
    if not _WARMED:
        warm_price_model()
    return _PRICE_ROWS or []


def resolve_stud_fee(
    sire_name: str,
    sire_profile: Optional[dict] = None,
    *,
    sale_year: Optional[int] = None,
) -> Optional[int]:
    """Resolve sire stud fee — at sale year when provided, else current fee."""
    fee = None
    try:
        import fee_and_standing_location as fee_db

        if sale_year:
            fee = fee_db.resolve_fee_at_sale(sire_name or "", int(sale_year))
        else:
            fee = fee_db.get_current_fee(sire_name or "")
    except Exception:
        fee = None
    if fee and fee > 0:
        return int(fee)
    profile_fee = _fee_amount((sire_profile or {}).get("Stud Fee"))
    return profile_fee or None


def _value_projector_payload(lot: dict) -> Dict[str, Any]:
    try:
        import ValueProjector as vp

        raw = vp.project_hip_value(
            sex=lot.get("sex_letter") or lot.get("sex") or "",
            sire=lot.get("sire") or "",
            dam=lot.get("dam") or "",
            horse_name=lot.get("name") or lot.get("raw_name") or "",
            sold_as=lot.get("sold_as") or "",
            covering_sire=lot.get("covering_sire") or "",
            sire_of_dam=lot.get("damsire") or lot.get("sire_of_dam") or "",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "display": "", "point": None}

    point = raw.get("point")
    low = raw.get("low")
    high = raw.get("high")
    display = raw.get("display") or raw.get("VALUE PROJECTOR") or ""
    race = (raw.get("PROJECTED RACE EARNINGS") or "").strip()
    kind = raw.get("kind") or ""
    role = raw.get("role") or ""
    sex_u = (lot.get("sex_letter") or lot.get("sex") or "").strip().upper()

    # Colts / horses / ridglings / geldings as youngstock: never surface a
    # breeding-value number in the sales UI (stallion-prospect or BMS-style).
    male_youngstock = role == "youngstock" and (
        kind in ("colt", "gelding")
        or sex_u[:1] in ("C", "H", "R", "G")
        or sex_u.startswith(("COLT", "HORSE", "RIDGLING", "GELDING"))
    )
    if male_youngstock:
        point = None
        low = None
        high = None
        display = ""

    breeding_ok = bool(point) or bool(display)
    race_ok = bool(race)
    return {
        # Ready if either breeding value or race earnings is available.
        "ok": breeding_ok or race_ok,
        "breeding_ok": breeding_ok,
        "race_ok": race_ok,
        "kind": kind,
        "role": role,
        "point": point,
        "low": low,
        "high": high,
        "display": display,
        "detail": raw.get("detail") or "",
        "projected_race_earnings": race,
        "race_detail": raw.get("race_detail") or "",
    }


def _price_projection_payload(
    *,
    sire: str,
    fee: Optional[int],
    sold_as: str,
) -> Dict[str, Any]:
    """Legacy median/mean multiple projection (kept for Market Prediction cues)."""
    model = _model()
    if not model or not fee:
        return {
            "ok": False,
            "error": _PRICE_ERROR or ("no stud fee" if not fee else "model unavailable"),
            "sold_as": sold_as,
            "current_fee": fee,
        }
    try:
        import PriceProjection as pp

        proj = pp.project_price(float(fee), model, sold_as=sold_as)
        hist = pp.summarize_sire_history(_rows(), sire) if sire else {"n": 0}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "sold_as": sold_as, "current_fee": fee}

    if proj.get("error"):
        return {"ok": False, "error": proj["error"], "sold_as": sold_as, "current_fee": fee}

    low = proj.get("proj_median_multiple")
    high = proj.get("proj_mean_multiple") or proj.get("proj_loglog")
    point = proj.get("proj_loglog") or proj.get("proj_median_multiple")
    if low and high and high < low:
        low, high = high, low
    if low and high:
        label = f"{_money(low)} – {_money(high)}"
    elif point:
        label = _money(point)
        low = high = point
    else:
        label = ""

    market_block = (model.get("by_kind") or {}).get(sold_as) or (model.get("by_kind") or {}).get("All") or {}
    return {
        "ok": bool(label),
        "sold_as": sold_as,
        "current_fee": fee,
        "n": proj.get("n"),
        "n_matched": model.get("n_matched"),
        "median_multiple": proj.get("median_multiple"),
        "mean_multiple": proj.get("mean_multiple"),
        "proj_median_multiple": proj.get("proj_median_multiple"),
        "proj_mean_multiple": proj.get("proj_mean_multiple"),
        "proj_loglog": proj.get("proj_loglog"),
        "low": low,
        "high": high,
        "mid": ((low or 0) + (high or 0)) / 2.0 if low and high else point,
        "point": point,
        "label": label,
        "market_median_multiple": market_block.get("median_multiple"),
        "market_mean_multiple": market_block.get("mean_multiple"),
        "sire_history": {
            "n": hist.get("n") or 0,
            "median_price": hist.get("median_price"),
            "median_multiple": hist.get("median_multiple"),
            "mean_multiple": hist.get("mean_multiple"),
            "years": hist.get("years") or [],
        },
    }


def _empirical_market_payload(
    *,
    fee: Optional[int],
    sold_as: str,
) -> Dict[str, Any]:
    band_model = _band_model()
    if not band_model or not fee:
        return {
            "ok": False,
            "error": _PRICE_ERROR or ("no stud fee" if not fee else "band model unavailable"),
            "sold_as": sold_as,
            "current_fee": fee,
        }
    try:
        import PriceProjection as pp

        return pp.project_from_fee_band(float(fee), band_model, sold_as=sold_as)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "sold_as": sold_as, "current_fee": fee}


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _market_prediction(price: Dict[str, Any], value: Dict[str, Any], fee: Optional[int]) -> Dict[str, Any]:
    """
    Boom/bust signal for the Market Prediction panel.

    Prefer sire historical multiples vs market; else breeding-value vs auction projection.
    """
    score = 0.0
    basis = "market baseline"
    market_med = price.get("market_median_multiple")
    hist = price.get("sire_history") or {}
    hist_n = int(hist.get("n") or 0)
    hist_med = hist.get("median_multiple")

    if hist_n >= 5 and market_med and hist_med:
        ratio = float(hist_med) / float(market_med)
        score = _clamp((ratio - 1.0) / 0.5)
        basis = f"sire progeny {hist_med:.2f}× vs market {market_med:.2f}× (n={hist_n})"
    elif value.get("ok") and price.get("mid") and value.get("point"):
        ratio = float(price["mid"]) / max(float(value["point"]), 1.0)
        score = _clamp((ratio - 1.0) / 0.75)
        basis = f"auction mid {_money(price['mid'])} vs breeding value {_money(value['point'])}"
    elif price.get("ok") and fee and market_med:
        proj_mult = (price.get("point") or price.get("mid") or 0) / float(fee)
        ratio = proj_mult / float(market_med) if market_med else 1.0
        score = _clamp((ratio - 1.0) / 0.35)
        basis = f"model multiple {proj_mult:.2f}× vs market {market_med:.2f}×"

    if score >= 0.55:
        signal, label = "boom", "Boom"
    elif score >= 0.2:
        signal, label = "firm", "Firm"
    elif score <= -0.55:
        signal, label = "bust", "Bust"
    elif score <= -0.2:
        signal, label = "soft", "Soft"
    else:
        signal, label = "fair", "Fair"

    marker = 0.5 - (score * 0.42)
    marker = max(0.08, min(0.92, marker))

    note_bits = [f"{label} — {basis}."]
    if price.get("ok") and price.get("label"):
        note_bits.append(
            f"Projected {price.get('sold_as', 'sale').lower()} "
            f"{price['label']} on {_money(fee)} stud fee "
            f"({price.get('median_multiple') or 0:.2f}× median / "
            f"{price.get('mean_multiple') or 0:.2f}× mean)."
        )
    if value.get("ok") and value.get("display"):
        race = value.get("projected_race_earnings") or ""
        extra = f" Value projector {value['display']}"
        if race:
            extra += f"; race earnings {race}"
        note_bits.append(extra + ".")

    return {
        "signal": signal,
        "label": label,
        "score": round(score, 3),
        "marker": round(marker, 3),
        "basis": basis,
        "note": " ".join(note_bits),
        "ready": bool(price.get("ok") or value.get("ok")),
    }


def _parse_sale_year(raw: Any) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        text = str(raw).strip()
        # Prefer a 4-digit year token (handles "03/05/2025").
        m = re.search(r"(19|20)\d{2}", text)
        if m:
            return int(m.group(0))
        return int(text[:4])
    except (TypeError, ValueError):
        return None


def project_lot_market(
    lot: Optional[dict] = None,
    *,
    sire: str = "",
    sex: str = "",
    sold_as: str = "",
    catalog_title: str = "",
    sire_profile: Optional[dict] = None,
    dam: str = "",
    name: str = "",
    damsire: str = "",
    covering_sire: str = "",
    sale_year: Optional[int] = None,
    birth_year: Any = None,
    catalog_default_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Combined Expected Market Value + Market Prediction for one hip."""
    lot = dict(lot or {})
    if sire:
        lot.setdefault("sire", sire)
    if sex:
        lot.setdefault("sex_letter", sex)
        lot.setdefault("sex", sex)
    if sold_as:
        lot.setdefault("sold_as", sold_as)
    if dam:
        lot.setdefault("dam", dam)
    if name:
        lot.setdefault("name", name)
    if damsire:
        lot.setdefault("damsire", damsire)
    if covering_sire:
        lot.setdefault("covering_sire", covering_sire)
    if birth_year:
        lot.setdefault("birth_year", birth_year)

    year = (
        _parse_sale_year(sale_year)
        or _parse_sale_year(lot.get("sale_year"))
        or _parse_sale_year(lot.get("catalog_year"))
        or _parse_sale_year(lot.get("year"))
    )
    foaled = (
        _parse_sale_year(birth_year)
        or _parse_sale_year(lot.get("birth_year"))
        or _parse_sale_year(lot.get("birth_date"))
        or _parse_sale_year(lot.get("foaled"))
    )
    kind = _sold_as_kind(
        lot.get("sold_as") or "",
        catalog_title,
        lot.get("sex_letter") or lot.get("sex") or "",
        birth_year=foaled,
        sale_year=year,
        catalog_default_kind=catalog_default_kind or lot.get("catalog_default_kind"),
    )
    # ValueProjector sale-type gates on sold_as; fill from age/kind when missing.
    if kind and "YEARLING" not in (lot.get("sold_as") or "").upper() and "WEANLING" not in (
        lot.get("sold_as") or ""
    ).upper():
        lot["sold_as"] = kind
    lot["sold_as_kind"] = kind

    fee = resolve_stud_fee(lot.get("sire") or "", sire_profile, sale_year=year)
    value = _value_projector_payload(lot)
    empirical = (
        _empirical_market_payload(fee=fee, sold_as=kind)
        if kind
        else {"ok": False, "error": "not yearling/weanling", "sold_as": sold_as or None}
    )
    price = (
        _price_projection_payload(sire=lot.get("sire") or "", fee=fee, sold_as=kind)
        if kind
        else {"ok": False, "error": "not yearling/weanling", "sold_as": sold_as or None}
    )

    # Expected Market Value: empirical fee-band hammer ranges for Y/W.
    if empirical.get("ok"):
        expected = {
            "sire_stud_fee": fee,
            "sale_year": year,
            "low": empirical.get("low"),
            "high": empirical.get("high"),
            "mid": empirical.get("mid"),
            "label": empirical.get("label"),
            "rule": empirical.get("rule"),
            "source": "empirical_fee_band",
            "sold_as": kind,
            "band_label": empirical.get("band_label"),
            "band_key": empirical.get("band_key"),
            "n": empirical.get("n"),
            "n_matched": empirical.get("n_matched"),
            "match_rate": empirical.get("match_rate"),
            "p10": empirical.get("p10"),
            "p25": empirical.get("p25"),
            "p50": empirical.get("p50"),
            "p75": empirical.get("p75"),
            "p90": empirical.get("p90"),
            "median_multiple": empirical.get("median_multiple"),
            "mean_multiple": empirical.get("mean_multiple"),
            "fee_basis": "sire_stud_fee_at_sale_year",
        }
    elif value.get("ok") and (value.get("low") or value.get("point")):
        low = value.get("low") if value.get("low") is not None else value.get("point")
        high = value.get("high") if value.get("high") is not None else value.get("point")
        expected = {
            "sire_stud_fee": fee,
            "sale_year": year,
            "low": low,
            "high": high,
            "mid": ((low or 0) + (high or 0)) / 2.0 if low and high else value.get("point"),
            "label": value.get("display") or (_money(low) if low == high else f"{_money(low)} – {_money(high)}"),
            "rule": f"ValueProjector {value.get('kind') or 'breeding value'}",
            "source": "value_projector",
            "sold_as": kind,
        }
    elif fee:
        low, high = fee * 2, fee * 6
        expected = {
            "sire_stud_fee": fee,
            "sale_year": year,
            "low": low,
            "high": high,
            "mid": (low + high) / 2.0,
            "label": f"{_money(low)} – {_money(high)}",
            "rule": "fallback 2×–6× sire stud fee",
            "source": "fee_fallback",
            "sold_as": kind,
        }
    else:
        expected = {
            "sire_stud_fee": None,
            "sale_year": year,
            "low": None,
            "high": None,
            "mid": None,
            "label": "Projection unavailable (stud fee unknown)",
            "rule": "unavailable",
            "source": "unavailable",
            "sold_as": kind,
        }

    expected["value_projector"] = value
    expected["price_projection"] = {
        k: price.get(k)
        for k in (
            "ok",
            "error",
            "sold_as",
            "current_fee",
            "n",
            "n_matched",
            "median_multiple",
            "mean_multiple",
            "proj_median_multiple",
            "proj_mean_multiple",
            "proj_loglog",
            "market_median_multiple",
            "sire_history",
        )
        if k in price
    }
    expected["empirical_band"] = {
        k: empirical.get(k)
        for k in (
            "ok",
            "error",
            "band_label",
            "band_key",
            "n",
            "n_matched",
            "match_rate",
            "p25",
            "p50",
            "p75",
            "rule",
            "fee_basis",
            "kind_used",
        )
        if k in empirical
    }

    # Market prediction still uses multiple model when available; else empirical mid.
    pred_price = price if price.get("ok") else {
        "ok": empirical.get("ok"),
        "mid": empirical.get("mid"),
        "point": empirical.get("mid"),
        "label": empirical.get("label"),
        "sold_as": kind,
        "median_multiple": empirical.get("median_multiple"),
        "mean_multiple": empirical.get("mean_multiple"),
        "market_median_multiple": empirical.get("median_multiple"),
        "sire_history": (price.get("sire_history") if isinstance(price, dict) else None) or {"n": 0},
    }
    prediction = _market_prediction(pred_price, value, fee)
    return {
        "expected_market": expected,
        "market_prediction": prediction,
    }


def expected_market_mid_for_filter(
    sire_name: str,
    *,
    sold_as: str = "",
    catalog_title: str = "",
    sex: str = "",
    sire_profile: Optional[dict] = None,
    sale_year: Optional[int] = None,
    birth_year: Any = None,
    catalog_default_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Cheap band for catalog price filters (empirical fee-band mid when possible)."""
    kind = (
        _sold_as_kind(
            sold_as,
            catalog_title,
            sex,
            birth_year=birth_year,
            sale_year=sale_year,
            catalog_default_kind=catalog_default_kind,
        )
        or "Yearling"
    )
    fee = resolve_stud_fee(sire_name, sire_profile, sale_year=sale_year)
    empirical = _empirical_market_payload(fee=fee, sold_as=kind)
    if empirical.get("ok") and empirical.get("mid"):
        return {
            "low": empirical.get("low"),
            "high": empirical.get("high"),
            "mid": empirical.get("mid"),
            "source": "empirical_fee_band",
            "label": empirical.get("label"),
            "sire_stud_fee": fee,
            "rule": empirical.get("rule"),
        }
    if fee:
        low, high = fee * 2, fee * 6
        return {
            "low": low,
            "high": high,
            "mid": (low + high) / 2.0,
            "source": "fee_fallback",
            "label": f"{_money(low)} – {_money(high)}",
            "sire_stud_fee": fee,
        }
    return {
        "low": None,
        "high": None,
        "mid": None,
        "source": "unavailable",
        "label": "",
        "sire_stud_fee": None,
    }
