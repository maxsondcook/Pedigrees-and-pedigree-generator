"""
ValueProjector — expected breeding-value (E[BV]) projections for colts and fillies/mares.

Formulas from project notes:

  COLT
    E[BV] = Σ_i (ISF_i · 400) / (F_SS_i / 2)
    where similar stallions S_i are sons/grandsons of the sire (or of the
    sire's sire when the direct sire has no sons at stud yet).
    Horses that never stand at stud contribute 0. Mode of the distribution
    is 0; this module estimates the mean (expected value).
    Industry stud-deal heuristic: lifetime stud value ≈ ISF × 400.

  FILLY / MARE
    E[BV] ≈ Σ progeny auction prices (empirical), isolating the mare's
    added value as sale_price / covering_sire_stud_fee (e.g. 2×, 6×).
    Career scale: ~6–10 foals/broodmare × ≈75% live-foal rate.
    When grandchildren / progeny sales are missing, fall back to familial
    bonds and stallions with similar race records / similar ISF.

  RACE EARNINGS (stallion projection)
    (Earnings / runner) · (runners / # foals with age ≥ 3)
    If the horse has no runners yet, predict via similar-ISF peers.
"""

from __future__ import annotations

import csv
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pedigrees_database
import stallion_profiles as sp_mod

# ---------------------------------------------------------------------------
# Constants (from notebook)
# ---------------------------------------------------------------------------
STUD_DEAL_MULTIPLIER = 400
LIVE_FOAL_RATE = 0.75
FOALS_PER_BROODMARE_LOW = 6
FOALS_PER_BROODMARE_HIGH = 10
FOALS_PER_BROODMARE_MEAN = 8
EXPECTED_LIVE_FOALS = FOALS_PER_BROODMARE_MEAN * LIVE_FOAL_RATE  # 6.0

# Opening / initial stud fees when known (current profile fee is used otherwise).
# Notebook example: Flightline ISF = $200,000.
INITIAL_STUD_FEE_OVERRIDES: Dict[str, int] = {
    "FLIGHTLINE": 200_000,
}

SALES_DIRS = [Path("sales_data"), Path(".")]

# Broodmare-sire development timeline (informational)
BM_SIRE_TIMELINE = [
    ("Horse retires", "Age 3–5"),
    ("First season at stud", "Age 4–6"),
    ("First foals", "Age 5–7"),
    ("First runners", "Age 7–9"),
    ("First horses retire", "Age 8–10"),
    ("First grandchildren", "Age 10–12"),
    ("First grandchildren at sales", "Age 11–13"),
]

# Lazy sales index: dam_sire_key -> list of sale dicts
_SALES_BY_DAM_SIRE: Optional[Dict[str, List[dict]]] = None
_SALES_BY_DAM: Optional[Dict[str, List[dict]]] = None


# ---------------------------------------------------------------------------
# Name / money helpers
# ---------------------------------------------------------------------------
def clean_horse_name(name: str) -> str:
    if not name or not isinstance(name, str):
        return ""
    cleaned = re.sub(r"\(.*?\)", "", name)
    cleaned = cleaned.replace(".", "").replace("'", "").replace(",", "")
    return " ".join(cleaned.split()).strip().upper()


def parse_money(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().upper().replace(",", "").replace("$", "")
    if not s or any(tok in s for tok in ("OUT", "NOT SOLD", "RNA", "N/A", "-2.00")):
        return 0.0
    cleaned = "".join(c for c in s if c.isdigit() or c == ".")
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def fmt_money(amount: float) -> str:
    if amount is None or (isinstance(amount, float) and math.isnan(amount)):
        return "n/a"
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.0f}"


def _profile_lookup(name: str) -> Tuple[Optional[str], Optional[dict]]:
    """Return (canonical profile key, profile dict) or (None, None)."""
    profiles = sp_mod.stallion_profiles
    target = clean_horse_name(name)
    for key, data in profiles.items():
        if clean_horse_name(key) == target:
            return key, data
    # Soft contains match
    hits = [k for k in profiles if target and target in clean_horse_name(k)]
    if len(hits) == 1:
        return hits[0], profiles[hits[0]]
    return None, None


def _pedigree_for(name: str) -> Optional[dict]:
    key = clean_horse_name(name)
    ped = pedigrees_database.pedigree_map.get(key)
    if ped:
        return ped
    # Soft match
    for k, v in pedigrees_database.pedigree_map.items():
        if clean_horse_name(k) == key:
            return v
    return None


def _node_horse(node: Any) -> str:
    if isinstance(node, dict):
        return clean_horse_name(node.get("Horse", ""))
    return clean_horse_name(str(node) if node else "")


def get_sire_name(name: str) -> Optional[str]:
    ped = _pedigree_for(name)
    if not ped:
        return None
    s = _node_horse(ped.get("Sire"))
    return s or None


def get_grandsire_name(name: str) -> Optional[str]:
    ped = _pedigree_for(name)
    if not ped:
        return None
    sire = ped.get("Sire")
    if isinstance(sire, dict):
        return _node_horse(sire.get("Sire")) or None
    return None


def get_dam_sire_name(name: str) -> Optional[str]:
    ped = _pedigree_for(name)
    if not ped:
        return None
    dam = ped.get("Dam")
    if isinstance(dam, dict):
        return _node_horse(dam.get("Sire")) or None
    return None


def career_race_earnings(profile: dict) -> float:
    total = 0.0
    for season in (profile.get("Race Record") or {}).values():
        if isinstance(season, dict):
            total += parse_money(season.get("Earnings", 0))
    return total


def initial_stud_fee(name: str, profile: Optional[dict] = None) -> float:
    """ISF: override table first, else current Stud Fee from the profile."""
    key = clean_horse_name(name)
    if key in INITIAL_STUD_FEE_OVERRIDES:
        return float(INITIAL_STUD_FEE_OVERRIDES[key])
    if profile is None:
        _, profile = _profile_lookup(name)
    if not profile:
        return 0.0
    return parse_money(profile.get("Stud Fee", 0))


def foals_of_racing_age(name: str, profile: Optional[dict] = None) -> int:
    if profile is None:
        _, profile = _profile_lookup(name)
    if profile:
        prog = profile.get("Progeny Racing Statistics") or {}
        for field in ("Foals of Racing Age", "Foals"):
            raw = prog.get(field)
            if raw is not None:
                try:
                    n = int(raw)
                    if n > 0:
                        return n
                except (TypeError, ValueError):
                    pass
    # Broodmare-sire cum_foals as last resort for prolific older sires
    try:
        import placeholder_store

        target = placeholder_store.broodmare_clean_horse_name(name)
        for entry in placeholder_store.load_broodmare_sire_rows():
            if placeholder_store.broodmare_clean_horse_name(entry["stallion"]) == target:
                n = int(entry.get("cum_foals") or 0)
                if n > 0:
                    return n
    except Exception:
        pass
    return 0


def stands_at_stud(profile: dict) -> bool:
    fee = parse_money(profile.get("Stud Fee", 0))
    status = str(profile.get("Status", "")).lower()
    if fee <= 0:
        return False
    if any(tok in status for tok in ("pension", "dead", "deceased", "retired from stud")):
        return False
    return True


# ---------------------------------------------------------------------------
# Similar stallions (sons / grandsons)
# ---------------------------------------------------------------------------
def find_similar_stallions(
    anchor_sire: str,
    include_grandsons: bool = True,
    exclude_names: Optional[set] = None,
) -> List[Tuple[str, dict]]:
    """
    Stallions in the roster whose sire (or grandsire) is anchor_sire.
    Only horses that currently stand at stud (fee > 0) are returned;
    non-stud horses contribute BV = 0 by omission from the sum.
    """
    exclude = {clean_horse_name(n) for n in (exclude_names or set())}
    anchor = clean_horse_name(anchor_sire)
    results: List[Tuple[str, dict]] = []

    for name, profile in sp_mod.stallion_profiles.items():
        if clean_horse_name(name) in exclude:
            continue
        if not stands_at_stud(profile):
            continue
        sire = get_sire_name(name)
        gs = get_grandsire_name(name) if include_grandsons else None
        if sire == anchor or (include_grandsons and gs == anchor):
            results.append((name, profile))

    results.sort(key=lambda x: initial_stud_fee(x[0], x[1]), reverse=True)
    return results


def resolve_sire_of_stallions(colt_sire: str) -> Tuple[str, str]:
    """
    Choose the Sire-of-Stallions (SS) used for F_SS and the similar set.

    Prefer the colt's own sire when he already has sons/grandsons at stud.
    Otherwise walk up one generation (notebook: Flightline → Tapit side).
    """
    direct = clean_horse_name(colt_sire)
    similars = find_similar_stallions(direct)
    if similars:
        return direct, "direct"

    parent = get_sire_name(colt_sire)
    if parent:
        return parent, "sire_side_fallback"

    return direct, "direct_empty"


# ---------------------------------------------------------------------------
# Colt E[BV]
# ---------------------------------------------------------------------------
def colt_contribution(isf: float, foals_racing_age_ss: int) -> float:
    """Single similar-stallion term: (ISF · 400) / (F_SS / 2)."""
    male_foals = foals_racing_age_ss / 2.0
    if male_foals <= 0 or isf <= 0:
        return 0.0
    return (isf * STUD_DEAL_MULTIPLIER) / male_foals


def project_colt_bv(colt_sire: str, verbose: bool = True) -> dict:
    """
    Expected breeding value of a yearling/colt by `colt_sire`.

    E[BV] = Σ (ISF_i · 400) / (F_SS / 2) over similar stallions of SS.
    """
    canon_sire, sire_profile = _profile_lookup(colt_sire)
    display_sire = canon_sire or colt_sire.strip()

    ss_name, resolution = resolve_sire_of_stallions(display_sire)
    ss_canon, ss_profile = _profile_lookup(ss_name)
    ss_display = ss_canon or ss_name

    f_ss = foals_of_racing_age(ss_display, ss_profile)
    # Notebook ballpark for Tapit was ~3000; if profile is thin, allow BMS cum_foals
    if f_ss <= 0:
        try:
            import placeholder_store

            for entry in placeholder_store.load_broodmare_sire_rows():
                if placeholder_store.broodmare_clean_horse_name(entry["stallion"]) == placeholder_store.broodmare_clean_horse_name(ss_display):
                    f_ss = int(entry.get("cum_foals") or 0)
                    break
        except Exception:
            pass

    similar = find_similar_stallions(ss_display)
    contributions = []
    total = 0.0

    for name, profile in similar:
        isf = initial_stud_fee(name, profile)
        if isf <= 0:
            continue  # BV = 0 if they don't stand
        term = colt_contribution(isf, f_ss)
        stud_deal = isf * STUD_DEAL_MULTIPLIER
        contributions.append(
            {
                "stallion": name,
                "isf": isf,
                "stud_deal": stud_deal,
                "contribution": term,
                "relation": (
                    "son"
                    if get_sire_name(name) == clean_horse_name(ss_display)
                    else "grandson"
                ),
            }
        )
        total += term

    result = {
        "kind": "colt",
        "colt_sire": display_sire,
        "sire_of_stallions": ss_display,
        "resolution": resolution,
        "foals_of_racing_age_ss": f_ss,
        "male_foals_est": f_ss / 2.0 if f_ss else 0.0,
        "n_similar": len(contributions),
        "contributions": contributions,
        "expected_bv": total,
        "note": (
            "Mode of realized BV is 0 (most colts never stand). "
            "This figure is the mean / expected value across similar stallions."
        ),
    }

    if verbose:
        _print_colt_report(result)
    return result


def _print_colt_report(r: dict) -> None:
    print("\n" + "=" * 72)
    print("  VALUE PROJECTOR — COLT BREEDING VALUE")
    print("=" * 72)
    print(f"  Colt sire              : {r['colt_sire']}")
    print(f"  Sire of stallions (SS) : {r['sire_of_stallions']}  [{r['resolution']}]")
    print(f"  F_SS (foals racing age): {r['foals_of_racing_age_ss']:,}")
    print(f"  Colts of racing age    : {r['male_foals_est']:,.0f}   (F_SS / 2)")
    print(f"  Similar stallions (n)  : {r['n_similar']}")
    print("-" * 72)
    print(f"  {'Stallion':<22} {'Rel':<9} {'ISF':>12} {'Stud deal':>14} {'Contrib':>12}")
    print("-" * 72)
    for c in r["contributions"]:
        print(
            f"  {c['stallion']:<22} {c['relation']:<9} "
            f"{fmt_money(c['isf']):>12} {fmt_money(c['stud_deal']):>14} "
            f"{fmt_money(c['contribution']):>12}"
        )
    print("-" * 72)
    print(f"  E[BV]  =  Σ (ISF·{STUD_DEAL_MULTIPLIER}) / (F_SS/2)")
    print(f"  Expected breeding value: {fmt_money(r['expected_bv'])}")
    print(f"  ({r['note']})")
    print("=" * 72 + "\n")


# ---------------------------------------------------------------------------
# Sales index (for filly / mare projections)
# ---------------------------------------------------------------------------
def _header_map(fieldnames: Optional[List[str]]) -> Dict[str, str]:
    if not fieldnames:
        return {}
    return {(h or "").lower().strip(): h for h in fieldnames if h}


def _dam_to_sire_cache() -> Dict[str, str]:
    """Map dam name → her sire (catalog 'sire of dam') from the pedigree DB."""
    cache: Dict[str, str] = {}
    for key, ped in pedigrees_database.pedigree_map.items():
        if not isinstance(ped, dict):
            continue
        dam_key = clean_horse_name(key)
        sire = _node_horse(ped.get("Sire"))
        if dam_key and sire:
            cache[dam_key] = sire
    return cache


def _build_sales_indexes() -> None:
    global _SALES_BY_DAM_SIRE, _SALES_BY_DAM
    by_ds: Dict[str, List[dict]] = defaultdict(list)
    by_dam: Dict[str, List[dict]] = defaultdict(list)
    dam_sire_of = _dam_to_sire_cache()

    for base in SALES_DIRS:
        if not base.exists():
            continue
        for fp in base.glob("*.csv"):
            try:
                with open(fp, mode="r", encoding="utf-8-sig", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    hm = _header_map(reader.fieldnames)
                    sod_h = hm.get("sire of dam") or hm.get("bms") or hm.get("damsire")
                    sire_h = hm.get("sire")
                    dam_h = hm.get("dam")
                    price_h = hm.get("price")
                    sex_h = hm.get("sex")
                    name_h = hm.get("name") or hm.get("horse name") or hm.get("horse")
                    if not price_h:
                        continue
                    for row in reader:
                        price = parse_money(row.get(price_h))
                        if price <= 0:
                            continue
                        sire = clean_horse_name(row.get(sire_h, "")) if sire_h else ""
                        dam = clean_horse_name(row.get(dam_h, "")) if dam_h else ""
                        sod = clean_horse_name(row.get(sod_h, "")) if sod_h else ""

                        # Infer broodmare sire = the dam's own sire when SOD is absent
                        if not sod and dam:
                            sod = dam_sire_of.get(dam, "")

                        rec = {
                            "price": price,
                            "sire": sire,
                            "dam": dam,
                            "dam_sire": sod,
                            "sex": (row.get(sex_h, "") if sex_h else ""),
                            "horse": clean_horse_name(row.get(name_h, "")) if name_h else "",
                            "file": fp.name,
                        }
                        if sod:
                            by_ds[sod].append(rec)
                        if dam:
                            by_dam[dam].append(rec)
            except Exception:
                continue

    _SALES_BY_DAM_SIRE = dict(by_ds)
    _SALES_BY_DAM = dict(by_dam)


def sales_by_dam_sire(dam_sire: str) -> List[dict]:
    global _SALES_BY_DAM_SIRE
    if _SALES_BY_DAM_SIRE is None:
        _build_sales_indexes()
    assert _SALES_BY_DAM_SIRE is not None
    return list(_SALES_BY_DAM_SIRE.get(clean_horse_name(dam_sire), []))


def sales_by_dam(dam: str) -> List[dict]:
    global _SALES_BY_DAM
    if _SALES_BY_DAM is None:
        _build_sales_indexes()
    assert _SALES_BY_DAM is not None
    return list(_SALES_BY_DAM.get(clean_horse_name(dam), []))


def covering_sire_fee(sire_name: str) -> float:
    _, profile = _profile_lookup(sire_name)
    if profile:
        return initial_stud_fee(sire_name, profile)
    return 0.0


def added_value_multiplier(sale_price: float, stud_fee: float) -> Optional[float]:
    if stud_fee <= 0 or sale_price <= 0:
        return None
    return sale_price / stud_fee


# ---------------------------------------------------------------------------
# Similar ISF / race-record peers (fallback when data is thin)
# ---------------------------------------------------------------------------
def similar_isf_peers(
    reference_name: str,
    top_n: int = 5,
    exclude_self: bool = True,
) -> List[Tuple[str, dict, float]]:
    """
    Stallions with similar initial stud fee and race earnings.
    Distance = normalized |ΔISF| + normalized |Δcareer earnings|.
    """
    ref_key, ref_profile = _profile_lookup(reference_name)
    if not ref_profile:
        # Synthesize from name only — use broodmare / fee-less peers by earnings≈0
        ref_isf = INITIAL_STUD_FEE_OVERRIDES.get(clean_horse_name(reference_name), 0.0)
        ref_earn = 0.0
    else:
        ref_isf = initial_stud_fee(ref_key or reference_name, ref_profile)
        ref_earn = career_race_earnings(ref_profile)

    scored: List[Tuple[str, dict, float]] = []
    for name, profile in sp_mod.stallion_profiles.items():
        if exclude_self and clean_horse_name(name) == clean_horse_name(reference_name):
            continue
        if not stands_at_stud(profile):
            continue
        isf = initial_stud_fee(name, profile)
        earn = career_race_earnings(profile)
        # Relative distances; guard zeros
        isf_den = max(ref_isf, isf, 1.0)
        earn_den = max(ref_earn, earn, 1.0)
        dist = abs(isf - ref_isf) / isf_den + abs(earn - ref_earn) / earn_den
        scored.append((name, profile, dist))

    scored.sort(key=lambda x: x[2])
    return scored[:top_n]


# ---------------------------------------------------------------------------
# Filly / mare E[BV]
# ---------------------------------------------------------------------------
def project_filly_bv(
    name: str,
    mode: str = "auto",
    verbose: bool = True,
) -> dict:
    """
    Project breeding value for a filly / female / mare.

    mode:
      - "mare"  : treat `name` as a specific dam; sum her progeny auction prices
      - "bms"   : treat `name` as a broodmare sire (e.g. Tapit); use daughters'
                  progeny sales and added-value multipliers
      - "auto"  : if `name` is a known stallion profile → bms, else mare
    """
    canon, profile = _profile_lookup(name)
    if mode == "auto":
        mode = "bms" if profile else "mare"

    if mode == "mare":
        return _project_specific_mare(name, verbose=verbose)
    return _project_broodmare_sire_filly(canon or name, verbose=verbose)


def _project_specific_mare(dam_name: str, verbose: bool = True) -> dict:
    sales = sales_by_dam(dam_name)
    multipliers = []
    by_sire: Dict[str, List[float]] = defaultdict(list)

    for rec in sales:
        fee = covering_sire_fee(rec["sire"])
        mult = added_value_multiplier(rec["price"], fee)
        by_sire[rec["sire"] or "?"].append(rec["price"])
        if mult is not None:
            multipliers.append(
                {
                    "sire": rec["sire"],
                    "price": rec["price"],
                    "stud_fee": fee,
                    "multiplier": mult,
                }
            )

    total_auction = sum(r["price"] for r in sales)
    mean_mult = statistics.mean(m["multiplier"] for m in multipliers) if multipliers else None
    median_price = statistics.median(r["price"] for r in sales) if sales else None

    # Career projection if we only have a few foals so far
    projected_career = None
    if median_price is not None:
        projected_career = EXPECTED_LIVE_FOALS * median_price
    elif not sales:
        # Fall back via dam sire / similar ISF
        ds = get_sire_name(dam_name)  # mare's sire = broodmare sire of her foals' dams... wait
        # For a mare, her sire is the broodmare sire of her progeny.
        mare_sire = get_sire_name(dam_name)
        if mare_sire:
            proxy = _project_broodmare_sire_filly(mare_sire, verbose=False)
            projected_career = proxy.get("projected_career_bv")
            mean_mult = proxy.get("mean_added_value_multiplier")
        else:
            peers = similar_isf_peers(dam_name)
            # Use first peer that is a known BM sire in sales
            for peer_name, _, _ in peers:
                proxy_sales = sales_by_dam_sire(peer_name)
                if proxy_sales:
                    median_price = statistics.median(r["price"] for r in proxy_sales)
                    projected_career = EXPECTED_LIVE_FOALS * median_price
                    break

    result = {
        "kind": "mare",
        "name": dam_name.strip(),
        "progeny_sales_count": len(sales),
        "sum_progeny_auction": total_auction,
        "mean_added_value_multiplier": mean_mult,
        "multiplier_examples": multipliers[:10],
        "median_progeny_price": median_price,
        "expected_live_foals": EXPECTED_LIVE_FOALS,
        "projected_career_bv": projected_career if projected_career is not None else total_auction,
        "empirical_bv": total_auction,
        "by_covering_sire": {k: {"n": len(v), "mean": statistics.mean(v)} for k, v in by_sire.items()},
    }
    if verbose:
        _print_filly_report(result)
    return result


def _project_broodmare_sire_filly(bms_name: str, verbose: bool = True) -> dict:
    """
    Expected breeding value of a filly whose sire is `bms_name` (she will
    become a broodmare by that sire), using auction results of foals out of
    mares by that sire — isolating added value vs covering-sire stud fees.
    """
    display = bms_name.strip()
    sales = sales_by_dam_sire(display)
    used_fallback = False
    fallback_from = None
    # Prefer the subject's own BMS sales; only borrow a similar-ISF peer when
    # that peer has a meaningful auction sample (same bar used for ranges).
    if len(sales) < 5:
        peers = similar_isf_peers(display, top_n=12)
        for peer_name, _, dist in peers:
            peer_sales = sales_by_dam_sire(peer_name)
            if len(peer_sales) >= FILLY_RANGE_MIN_N:
                sales = peer_sales
                fallback_from = peer_name
                used_fallback = True
                break

    multipliers = []
    prices = []
    for rec in sales:
        prices.append(rec["price"])
        fee = covering_sire_fee(rec["sire"])
        mult = added_value_multiplier(rec["price"], fee)
        if mult is not None:
            multipliers.append(
                {
                    "sire": rec["sire"],
                    "price": rec["price"],
                    "stud_fee": fee,
                    "multiplier": mult,
                }
            )

    mean_price = statistics.mean(prices) if prices else None
    median_price = statistics.median(prices) if prices else None
    mean_mult = statistics.mean(m["multiplier"] for m in multipliers) if multipliers else None
    median_mult = (
        statistics.median(m["multiplier"] for m in multipliers) if multipliers else None
    )

    # Per-dam aggregation: average total progeny auction value among dams
    by_dam: Dict[str, float] = defaultdict(float)
    for rec in sales:
        if rec["dam"]:
            by_dam[rec["dam"]] += rec["price"]
    mean_per_dam = statistics.mean(by_dam.values()) if by_dam else None

    projected = None
    if used_fallback and mean_per_dam is not None:
        # Peer fallback: use observed mean Σ/dam (no full-career scale-up)
        projected = mean_per_dam
    elif median_price is not None:
        projected = EXPECTED_LIVE_FOALS * median_price
    elif mean_per_dam is not None:
        projected = mean_per_dam

    # Highlight notebook-style examples (highest / notable multipliers)
    examples = sorted(multipliers, key=lambda m: m["multiplier"], reverse=True)[:8]

    result = {
        "kind": "filly_bms",
        "name": display,
        "broodmare_sire": display,
        "progeny_sales_count": len(sales),
        "unique_dams": len(by_dam),
        "mean_progeny_price": mean_price,
        "median_progeny_price": median_price,
        "mean_added_value_multiplier": mean_mult,
        "median_added_value_multiplier": median_mult,
        "mean_total_per_dam": mean_per_dam,
        "expected_live_foals": EXPECTED_LIVE_FOALS,
        "foals_per_broodmare_range": (FOALS_PER_BROODMARE_LOW, FOALS_PER_BROODMARE_HIGH),
        "live_foal_rate": LIVE_FOAL_RATE,
        "projected_career_bv": projected,
        "empirical_bv": mean_per_dam,
        "multiplier_examples": examples,
        "used_similar_isf_fallback": used_fallback and fallback_from is not None,
        "fallback_peer": fallback_from,
    }
    if verbose:
        _print_filly_report(result)
    return result


def _print_filly_report(r: dict) -> None:
    print("\n" + "=" * 72)
    if r["kind"] == "mare":
        print("  VALUE PROJECTOR — MARE BREEDING VALUE (progeny at auction)")
    else:
        print("  VALUE PROJECTOR — FILLY / BMS BREEDING VALUE")
    print("=" * 72)
    print(f"  Subject                : {r['name']}")
    if r["kind"] == "filly_bms":
        print(f"  Broodmare sire lens    : {r['broodmare_sire']}")
        if r.get("used_similar_isf_fallback"):
            print(f"  Similar-ISF fallback   : using sales of {r['fallback_peer']}")
    print(f"  Progeny sales used     : {r.get('progeny_sales_count', 0):,}")
    if r.get("unique_dams") is not None:
        print(f"  Unique dams            : {r['unique_dams']:,}")
    print(
        f"  Career scale           : {FOALS_PER_BROODMARE_LOW}–{FOALS_PER_BROODMARE_HIGH} "
        f"foals × ~{int(LIVE_FOAL_RATE*100)}% live  →  ≈{EXPECTED_LIVE_FOALS:.1f} live foals"
    )
    print("-" * 72)
    if r.get("mean_progeny_price") is not None:
        print(f"  Mean progeny price     : {fmt_money(r['mean_progeny_price'])}")
    if r.get("median_progeny_price") is not None:
        print(f"  Median progeny price   : {fmt_money(r['median_progeny_price'])}")
    if r.get("mean_total_per_dam") is not None:
        print(f"  Mean Σ auction / dam   : {fmt_money(r['mean_total_per_dam'])}")
    if r.get("sum_progeny_auction") is not None:
        print(f"  Σ progeny at auction   : {fmt_money(r['sum_progeny_auction'])}")
    if r.get("mean_added_value_multiplier") is not None:
        print(
            f"  Mean added-value mult  : {r['mean_added_value_multiplier']:.2f}× stud fee"
        )
    if r.get("median_added_value_multiplier") is not None:
        print(
            f"  Median added-value mult: {r['median_added_value_multiplier']:.2f}× stud fee"
        )
    examples = r.get("multiplier_examples") or []
    if examples:
        print("-" * 72)
        print(f"  {'Covering sire':<22} {'Sale':>12} {'Fee':>12} {'Added':>10}")
        for m in examples[:8]:
            print(
                f"  {(m.get('sire') or '?'):<22} {fmt_money(m['price']):>12} "
                f"{fmt_money(m['stud_fee']):>12} {m['multiplier']:>9.2f}×"
            )
    print("-" * 72)
    emp = r.get("empirical_bv")
    proj = r.get("projected_career_bv")
    if emp is not None:
        print(f"  Empirical E[BV] (Σ auction)     : {fmt_money(emp)}")
    if proj is not None:
        print(f"  Projected career E[BV]          : {fmt_money(proj)}")
        print(f"    (= ≈{EXPECTED_LIVE_FOALS:.1f} live foals × median progeny price)")
    print("=" * 72 + "\n")


# ---------------------------------------------------------------------------
# Projected race earnings
# ---------------------------------------------------------------------------
def project_race_earnings(stallion_name: str, verbose: bool = True) -> dict:
    """
    (Earnings / runner) · (runners / # foals with age ≥ 3)

    Equivalent to total_progeny_earnings / foals_of_racing_age when
    earnings/runner is taken from the stallion profile.
    """
    canon, profile = _profile_lookup(stallion_name)
    display = canon or stallion_name.strip()
    used_fallback = False
    fallback_peer = None

    def _from_profile(name: str, prof: dict) -> Optional[dict]:
        prog = prof.get("Progeny Racing Statistics") or {}
        earn = prof.get("Progeny Earnings Statistics") or {}
        runners = prog.get("Starters") or prog.get("Runners")
        foals_ra = prog.get("Foals of Racing Age") or prog.get("Foals")
        avg = parse_money(earn.get("Avg Earnings/starter", 0))
        total = parse_money(earn.get("Earnings", 0))
        try:
            runners_n = int(runners) if runners is not None else 0
        except (TypeError, ValueError):
            runners_n = 0
        try:
            foals_n = int(foals_ra) if foals_ra is not None else 0
        except (TypeError, ValueError):
            foals_n = 0
        if avg <= 0 and total > 0 and runners_n > 0:
            avg = total / runners_n
        if foals_n <= 0 or avg <= 0:
            return None
        runner_rate = runners_n / foals_n if foals_n else 0.0
        projected = avg * runner_rate  # earnings per foal of racing age
        return {
            "earnings_per_runner": avg,
            "runners": runners_n,
            "foals_age_ge_3": foals_n,
            "runners_per_foal": runner_rate,
            "projected_earnings_per_foal": projected,
            "total_progeny_earnings": total if total else avg * runners_n,
        }

    stats = _from_profile(display, profile) if profile else None

    if stats is None:
        used_fallback = True
        for peer_name, peer_prof, _ in similar_isf_peers(display, top_n=10):
            stats = _from_profile(peer_name, peer_prof)
            if stats:
                fallback_peer = peer_name
                break

    result = {
        "kind": "race_earnings",
        "stallion": display,
        "used_similar_isf_fallback": used_fallback and fallback_peer is not None,
        "fallback_peer": fallback_peer,
        **(stats or {}),
        "projected_earnings_per_foal": (stats or {}).get("projected_earnings_per_foal"),
    }

    if verbose:
        print("\n" + "=" * 72)
        print("  VALUE PROJECTOR — PROJECTED RACE EARNINGS")
        print("=" * 72)
        print(f"  Stallion               : {display}")
        if result.get("used_similar_isf_fallback"):
            print(f"  Similar-ISF fallback   : {fallback_peer}")
        if stats:
            print(f"  Earnings / runner      : {fmt_money(stats['earnings_per_runner'])}")
            print(f"  Runners                : {stats['runners']:,}")
            print(f"  Foals age ≥ 3          : {stats['foals_age_ge_3']:,}")
            print(f"  Runners / foal         : {stats['runners_per_foal']:.1%}")
            print("-" * 72)
            print(
                f"  Projected = (E/runner)·(runners/foals≥3) "
                f"= {fmt_money(stats['projected_earnings_per_foal'])} per foal"
            )
        else:
            print("  Insufficient progeny and peer data to project race earnings.")
        print("=" * 72 + "\n")

    return result


def print_bm_sire_timeline() -> None:
    print("\n" + "=" * 72)
    print("  BROODMARE-SIRE DEVELOPMENT TIMELINE")
    print("=" * 72)
    for label, ages in BM_SIRE_TIMELINE:
        print(f"  {label:<32} {ages}")
    print(
        "\n  Grandchildren take ~11–13 years to reach the sales ring — hence the\n"
        "  similar-ISF / familial-bond fallback when that data does not exist yet."
    )
    print("=" * 72 + "\n")


# ---------------------------------------------------------------------------
# Catalog enrichment — point estimate or statistically supported range
# ---------------------------------------------------------------------------
# Show an IQR / percentile range only when the sample is large enough that a
# single point would understate dispersion. Otherwise emit a point estimate.
FILLY_RANGE_MIN_N = 20          # progeny sales for BMS / filly lens
MARE_RANGE_MIN_N = 5            # progeny sales for a specific mare
COLT_RANGE_MIN_SIMILAR = 5      # similar stallions at stud
RANGE_MIN_RELATIVE_SPAN = 0.12  # collapse to point if (high-low)/mid < 12%

_HIP_CACHE: Dict[str, dict] = {}


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def _fmt_vp_display(low: Optional[float], high: Optional[float], point: Optional[float]) -> str:
    if point is None and low is None and high is None:
        return ""
    if low is not None and high is not None and high > low:
        mid = (low + high) / 2.0
        if mid > 0 and (high - low) / mid >= RANGE_MIN_RELATIVE_SPAN:
            return f"{fmt_money(low)}–{fmt_money(high)}"
        return fmt_money(mid if point is None else point)
    if point is not None:
        return fmt_money(point)
    if low is not None:
        return fmt_money(low)
    return fmt_money(high) if high is not None else ""


def _pack_vp_result(
    *,
    kind: str,
    point: Optional[float],
    low: Optional[float] = None,
    high: Optional[float] = None,
    n: int = 0,
    detail: str = "",
) -> dict:
    is_range = (
        low is not None
        and high is not None
        and high > low
        and point is not None
        and point > 0
        and (high - low) / max(point, 1.0) >= RANGE_MIN_RELATIVE_SPAN
    )
    if not is_range:
        low = point
        high = point
    display = _fmt_vp_display(low if is_range else None, high if is_range else None, point)
    return {
        "kind": kind,
        "point": point,
        "low": low,
        "high": high,
        "is_range": is_range,
        "n": n,
        "display": display,
        "detail": detail,
        "VALUE PROJECTOR": display,
        "VP LOW": "" if low is None else round(low),
        "VP HIGH": "" if high is None else round(high),
        "VP POINT": "" if point is None else round(point),
    }


def _empty_vp(kind: str = "") -> dict:
    return _pack_vp_result(kind=kind, point=None, n=0, detail="insufficient data")


def _colt_vp_summary(colt_sire: str) -> dict:
    raw = project_colt_bv(colt_sire, verbose=False)
    point = float(raw.get("expected_bv") or 0.0)
    contribs = raw.get("contributions") or []
    n = len(contribs)
    if point <= 0 or n == 0:
        return _empty_vp("colt")

    low = high = None
    detail = f"n_similar={n}; SS={raw.get('sire_of_stallions')}"

    if n >= COLT_RANGE_MIN_SIMILAR:
        sons = [c["contribution"] for c in contribs if c.get("relation") == "son"]
        all_sum = point
        sons_sum = sum(sons) if sons else None
        # Jackknife band: leave-one-out totals (always ≤ full sum)
        jack = []
        for i in range(n):
            jack.append(all_sum - contribs[i]["contribution"])
        jack_sorted = sorted(jack)
        # Spread from conservative (leave out top contributor ≈ jack min)
        # up through full mean; also widen with sons-only when available.
        candidates_low = [jack_sorted[0], jack_sorted[len(jack_sorted) // 4]]
        candidates_high = [all_sum]
        if sons_sum is not None and len(sons) >= 2:
            candidates_low.append(sons_sum)
            candidates_high.append(all_sum)
        low = min(candidates_low)
        high = max(candidates_high)
        # Ensure point sits inside the band
        low = min(low, point)
        high = max(high, point)
        detail += "; range=jackknife/sons sensitivity"

    return _pack_vp_result(
        kind="colt",
        point=point,
        low=low,
        high=high,
        n=n,
        detail=detail,
    )


def _filly_bms_vp_summary(bms_name: str) -> dict:
    raw = project_filly_bv(bms_name, mode="bms", verbose=False)
    point = raw.get("projected_career_bv")
    if point is None:
        point = raw.get("empirical_bv")
    if point is None:
        return _empty_vp("filly_bms")
    point = float(point)

    # Rebuild price list from the same sales source the projector used
    sales = sales_by_dam_sire(raw.get("fallback_peer") or bms_name)
    if raw.get("used_similar_isf_fallback") and raw.get("fallback_peer"):
        sales = sales_by_dam_sire(raw["fallback_peer"])
    else:
        sales = sales_by_dam_sire(bms_name)
        if len(sales) < 5 and raw.get("fallback_peer"):
            sales = sales_by_dam_sire(raw["fallback_peer"])

    prices = sorted(r["price"] for r in sales if r.get("price"))
    n = len(prices)
    used_fallback = bool(raw.get("used_similar_isf_fallback"))
    detail = f"n_sales={n}"
    if used_fallback:
        detail += f"; peer={raw.get('fallback_peer')}"

    low = high = None
    # Ranges only from direct BMS evidence — peer fallbacks stay a point estimate
    # so another sire's auction IQR is not pasted onto a thinly documented line.
    if not used_fallback and n >= FILLY_RANGE_MIN_N:
        p25 = _percentile(prices, 0.25)
        p75 = _percentile(prices, 0.75)
        low = EXPECTED_LIVE_FOALS * p25
        high = EXPECTED_LIVE_FOALS * p75
        low = min(low, point)
        high = max(high, point)
        detail += "; range=P25–P75 career"
    elif not used_fallback and n >= 10:
        p20 = _percentile(prices, 0.20)
        p80 = _percentile(prices, 0.80)
        low = EXPECTED_LIVE_FOALS * p20
        high = EXPECTED_LIVE_FOALS * p80
        low = min(low, point)
        high = max(high, point)
        detail += "; range=P20–P80 career"

    return _pack_vp_result(
        kind="filly_bms",
        point=point,
        low=low,
        high=high,
        n=n,
        detail=detail,
    )


def _mare_vp_summary(mare_name: str, mare_sire: str = "") -> dict:
    raw = project_filly_bv(mare_name, mode="mare", verbose=False)
    sales = sales_by_dam(mare_name)
    n = len(sales)
    point = raw.get("projected_career_bv")
    if point is None:
        point = raw.get("empirical_bv")
    if (point is None or point == 0) and mare_sire:
        return _filly_bms_vp_summary(mare_sire)

    if point is None:
        return _empty_vp("mare")
    point = float(point)

    low = high = None
    detail = f"n_progeny_sales={n}"
    if n >= MARE_RANGE_MIN_N:
        prices = sorted(r["price"] for r in sales)
        # Empirical total so far as low; scale unfinished careers with percentiles
        total = sum(prices)
        p25 = _percentile(prices, 0.25)
        p75 = _percentile(prices, 0.75)
        # Remaining expected foals beyond those already sold
        remaining = max(EXPECTED_LIVE_FOALS - n, 0.0)
        low = total + remaining * p25
        high = total + remaining * p75
        if remaining <= 0:
            low = total
            high = total
        low = min(low, point) if point else low
        high = max(high, point) if point else high
        detail += "; range=realized+remaining P25–P75"
    elif mare_sire:
        return _filly_bms_vp_summary(mare_sire)

    return _pack_vp_result(
        kind="mare",
        point=point,
        low=low,
        high=high,
        n=n,
        detail=detail,
    )


def classify_catalog_role(
    sex: str = "",
    sold_as: str = "",
    covering_sire: str = "",
) -> str:
    """
    Return catalog projection role:
      - "youngstock" : weanling / yearling → breeding value + projected race earnings
      - "broodmare"  : broodmare (incl. broodmare/racing prospect) → breeding value only
      - "other"      : 2yos, racing prospects, etc. → no projections
    """
    sold_u = (sold_as or "").strip().upper()
    sex_u = (sex or "").strip().upper()
    cov = (covering_sire or "").strip()
    cov_ok = cov and cov.lower() not in ("nan", "none", "")

    if "BROODMARE" in sold_u or cov_ok or sex_u in ("M", "MARE"):
        return "broodmare"
    if "YEARLING" in sold_u or "WEANLING" in sold_u:
        return "youngstock"
    return "other"


def _race_earnings_vp_summary(sire_name: str) -> dict:
    """Projected race earnings (per foal) for youngstock, keyed by sire."""
    if not sire_name or not str(sire_name).strip():
        return {
            "display": "",
            "point": None,
            "PROJECTED RACE EARNINGS": "",
            "detail": "no sire",
        }
    cache_key = f"race::{clean_horse_name(sire_name)}"
    if cache_key in _HIP_CACHE:
        return _HIP_CACHE[cache_key]

    raw = project_race_earnings(sire_name, verbose=False)
    point = raw.get("projected_earnings_per_foal")
    detail = f"sire={raw.get('stallion')}"
    if raw.get("used_similar_isf_fallback"):
        detail += f"; peer={raw.get('fallback_peer')}"
    display = fmt_money(point) if point else ""
    result = {
        "display": display,
        "point": point,
        "PROJECTED RACE EARNINGS": display,
        "detail": detail,
        "n": raw.get("foals_age_ge_3") or raw.get("runners") or 0,
    }
    _HIP_CACHE[cache_key] = result
    return result


def _breeding_value_for_youngstock(sex: str, sire: str) -> dict:
    sex_u = (sex or "").strip().upper()
    if sex_u in ("G", "GELDING") or sex_u.startswith("G"):
        return _empty_vp("gelding")
    is_colt = sex_u in ("C", "H", "R", "COLT", "HORSE", "RIDGLING") or sex_u.startswith("C")
    is_filly = sex_u in ("F", "FILLY") or sex_u.startswith("F")
    if is_colt:
        cache_key = f"colt::{clean_horse_name(sire)}"
        if cache_key not in _HIP_CACHE:
            _HIP_CACHE[cache_key] = _colt_vp_summary(sire) if sire else _empty_vp("colt")
        return _HIP_CACHE[cache_key]
    if is_filly:
        cache_key = f"filly::{clean_horse_name(sire)}"
        if cache_key not in _HIP_CACHE:
            _HIP_CACHE[cache_key] = (
                _filly_bms_vp_summary(sire) if sire else _empty_vp("filly_bms")
            )
        return _HIP_CACHE[cache_key]
    if sire:
        cache_key = f"colt::{clean_horse_name(sire)}"
        if cache_key not in _HIP_CACHE:
            _HIP_CACHE[cache_key] = _colt_vp_summary(sire)
        return _HIP_CACHE[cache_key]
    return _empty_vp()


def project_hip_value(
    sex: str,
    sire: str = "",
    dam: str = "",
    horse_name: str = "",
    sold_as: str = "",
    covering_sire: str = "",
    sire_of_dam: str = "",
) -> dict:
    """
    Catalog-row Value Projector entry.

    Weanlings / yearlings → breeding value + projected race earnings
    Broodmares            → breeding value only
    Everything else       → blank (no projections)
    """
    sex_u = (sex or "").strip().upper()
    sire = (sire or "").strip()
    dam = (dam or "").strip()
    horse_name = (horse_name or "").strip()
    sire_of_dam = (sire_of_dam or "").strip()
    covering_sire = (covering_sire or "").strip()
    role = classify_catalog_role(sex=sex_u, sold_as=sold_as, covering_sire=covering_sire)

    blank_race = {
        "display": "",
        "point": None,
        "PROJECTED RACE EARNINGS": "",
        "detail": "",
    }

    if role == "other":
        out = _empty_vp("other")
        out["role"] = role
        out["PROJECTED RACE EARNINGS"] = ""
        return out

    if role == "broodmare":
        cache_key = f"mare::{clean_horse_name(horse_name) or clean_horse_name(dam)}"
        if cache_key not in _HIP_CACHE:
            mare_id = horse_name or dam
            mare_sire = sire or sire_of_dam
            _HIP_CACHE[cache_key] = _mare_vp_summary(mare_id, mare_sire=mare_sire)
        out = dict(_HIP_CACHE[cache_key])
        out["role"] = role
        out["PROJECTED RACE EARNINGS"] = ""  # broodmares: breeding value only
        return out

    # youngstock: weanling / yearling
    bv = _breeding_value_for_youngstock(sex_u, sire)
    race = _race_earnings_vp_summary(sire) if sire else blank_race
    out = dict(bv)
    out["role"] = role
    out["PROJECTED RACE EARNINGS"] = race.get("PROJECTED RACE EARNINGS", "")
    out["race_detail"] = race.get("detail", "")
    return out


VP_CATALOG_COLUMNS = (
    "VALUE PROJECTOR",
    "VP LOW",
    "VP HIGH",
    "VP POINT",
    "PROJECTED RACE EARNINGS",
)


def enrich_sales_dataframe(df, progress_every: int = 500):
    """
    Add breeding-value + (for youngstock) race-earnings columns to a catalog DataFrame.
    Mutates and returns df.
    """
    if df is None or len(df) == 0:
        return df

    for col in VP_CATALOG_COLUMNS:
        if col not in df.columns:
            df[col] = ""
        else:
            df[col] = df[col].astype(str).replace({"nan": "", "None": "", "NaN": ""})

    total = len(df)
    for i, (idx, row) in enumerate(df.iterrows()):
        vp = project_hip_value(
            sex=str(row.get("SEX", "") or ""),
            sire=str(row.get("SIRE", "") or ""),
            dam=str(row.get("DAM", "") or ""),
            horse_name=str(row.get("HORSE NAME", "") or ""),
            sold_as=str(row.get("SOLD AS", "") or ""),
            covering_sire=str(row.get("COVERING SIRE", "") or ""),
            sire_of_dam=str(row.get("SIRE OF DAM", "") or ""),
        )

        def _as_cell(v):
            if v is None or v == "":
                return ""
            return str(v)

        df.at[idx, "VALUE PROJECTOR"] = _as_cell(vp.get("VALUE PROJECTOR", ""))
        df.at[idx, "VP LOW"] = _as_cell(vp.get("VP LOW", ""))
        df.at[idx, "VP HIGH"] = _as_cell(vp.get("VP HIGH", ""))
        df.at[idx, "VP POINT"] = _as_cell(vp.get("VP POINT", ""))
        df.at[idx, "PROJECTED RACE EARNINGS"] = _as_cell(
            vp.get("PROJECTED RACE EARNINGS", "")
        )
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  ValueProjector: {i + 1:,}/{total:,} hips…")

    return df


def enrich_catalog_csv(csv_path: str, inplace: bool = True) -> str:
    """Load a catalog CSV, attach Value Projector columns, save, return path."""
    import pandas as pd

    path = Path(csv_path)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for col in VP_CATALOG_COLUMNS:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str)
    print(f"ValueProjector enriching {path.name} ({len(df):,} rows)…")
    enrich_sales_dataframe(df)
    out = path if inplace else path.with_name(path.stem + "_vp" + path.suffix)
    df.to_csv(out, index=False)
    print(f"  → wrote {out}")
    return str(out)


def enrich_all_analyzed_sales(analyzed_dir: str = "Analyzed Sales") -> List[str]:
    """Enrich every analyzed_*.csv catalog with Value Projector columns."""
    root = Path(analyzed_dir)
    written = []
    if not root.exists():
        return written
    for fp in sorted(root.glob("analyzed_*.csv")):
        written.append(enrich_catalog_csv(str(fp), inplace=True))
    return written


# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------
def run_value_projector_menu() -> None:
    while True:
        print("\n=========================================")
        print("           VALUE PROJECTOR               ")
        print("=========================================")
        print(" [1] Project COLT breeding value (by sire)")
        print(" [2] Project FILLY / MARE breeding value")
        print(" [3] Project race earnings (stallion)")
        print(" [4] Broodmare-sire timeline")
        print(" [5] Enrich all Analyzed Sales catalogs")
        print(" [B] Back / Exit")
        print("=========================================")
        choice = input("Select an option: ").strip().lower()

        if choice in ("b", "e", "q", ""):
            break

        if choice == "1":
            sire = input("Enter the colt's sire (e.g. Tapit, Flightline): ").strip()
            if sire:
                project_colt_bv(sire, verbose=True)

        elif choice == "2":
            print("  [1] Filly by broodmare-sire lens (e.g. Tapit)")
            print("  [2] Specific mare (sum her progeny auction prices)")
            sub = input("Choose 1 or 2: ").strip()
            name = input("Enter horse name: ").strip()
            if not name:
                continue
            if sub == "2":
                project_filly_bv(name, mode="mare", verbose=True)
            else:
                project_filly_bv(name, mode="bms", verbose=True)

        elif choice == "3":
            name = input("Enter stallion name: ").strip()
            if name:
                project_race_earnings(name, verbose=True)

        elif choice == "4":
            print_bm_sire_timeline()

        elif choice == "5":
            paths = enrich_all_analyzed_sales()
            print(f"Enriched {len(paths)} catalog(s).")

        else:
            print("Invalid selection.")


if __name__ == "__main__":
    run_value_projector_menu()
