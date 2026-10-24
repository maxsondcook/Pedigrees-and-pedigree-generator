"""
Statistical sale-price and Boom% model for yearling / weanling lots.

Fitted by scripts/train_sales_model.py (see docs/sales-model.md). This module is the
runtime half and the single source of truth for features, so training and the app
can never disagree about how a lot is described:

  History   running, as-of tables (sire / dam / damsire / cross / sale levels /
            graded-stakes counts). Training replays sales year by year, so every
            lot only sees earlier years; the final state ships as the artifact.
  features  raw as-of stats -> numeric feature vector (same function everywhere).
  predict   censored-normal (Tobit) log-price model + logistic Boom% model.

Pure Python at runtime: no numpy / scipy needed to score a lot.
"""

from __future__ import annotations

import gzip
import json
import math
import re
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_PATH = ROOT / "Analyzed Sales" / "sales_model.json.gz"

# A lot's stats only count history this many years back for sale levels.
SALE_LEVEL_MAX_LAG = 2
# Nearest prior stud fee allowed when the exact year is missing.
FEE_MAX_LAG = 2
# Per-sale hip curves are shrunk toward "no effect" by n / (n + HIP_K) lots.
HIP_K = 200.0

Z80 = 1.2815515655446004  # standard-normal 90th percentile -> 80% interval
Z50 = 0.6744897501960817  # 75th percentile -> 50% (p25-p75) interval

PRICE_FEATURES = [
    "sale_level",
    "sale_new",
    "market_trend",
    "weanling",
    "filly",
    "log_fee",
    "fee_missing",
    "fee_momentum",
    "sire_rel",
    "sire_log_n",
    "sire_log_gsw",
    "damsire_rel",
    "damsire_missing",
    "nick",
    "dam_rel",
    "dam_log_n",
    "dam_log_gsw",
    "dam_log_gsp",
    "dam_own_gsw",
    "dam_own_gsp",
    "hip_signal",
    "hip_pct",
    "hip_pct_sq",
]
HIP_FEATURES = ("hip_signal", "hip_pct", "hip_pct_sq")


def name_key(name: Any) -> str:
    """Uppercase, punctuation-free horse key; drops country suffixes like (IRE)."""
    if not isinstance(name, str):
        return ""
    s = re.sub(r"\(.*?\)", "", name)
    for ch in ".',’`":
        s = s.replace(ch, "")
    return " ".join(s.split()).upper()


_SALE_NOISE = re.compile(r"\b(analyzed|19\d{2}|20\d{2})\b")
# Renamed sales: old name -> current name (Fasig-Tipton's Timonium yearling sale).
SALE_ALIASES = {"eastern fall yearlings": "midlantic fall yearlings"}


def sale_key(title: Any) -> str:
    """Normalise a catalog title / file stem: 'analyzed_the_saratoga_sale_(2026)' -> 'the saratoga sale'."""
    s = str(title or "").lower().replace("_", " ")
    s = re.sub(r"\.csv$", "", s)
    s = _SALE_NOISE.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = " ".join(s.split())
    for old, new in SALE_ALIASES.items():
        s = s.replace(old, new)
    return s


def _sex_flag(sex: Any) -> Optional[int]:
    """1 = filly, 0 = colt/gelding/ridgling, None = unknown."""
    s = str(sex or "").strip().upper()[:1]
    if s == "F":
        return 1
    if s in ("C", "H", "R", "G"):
        return 0
    return None


class History:
    """As-of tables built from past sales and graded-stakes results."""

    def __init__(self) -> None:
        self.k: Dict[str, float] = {"sire": 20.0, "damsire": 20.0, "nick": 20.0, "dam": 2.0}
        self.fees: Dict[str, Dict[int, float]] = defaultdict(dict)
        self.sire: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0])  # rel sum, n
        self.damsire: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0])
        self.nick: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0])  # residual sum, n
        self.dam: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0])
        self.sire_gsw: Dict[str, int] = defaultdict(int)  # progeny graded winners
        self.dam_gsw: Dict[str, int] = defaultdict(int)
        self.dam_gsp: Dict[str, int] = defaultdict(int)  # progeny graded placed (not won)
        self.own: Dict[str, int] = {}  # horse -> 2 graded winner, 1 graded placed
        self.dam_sire: Dict[str, str] = {}  # dam -> her sire (fills missing damsire)
        # sale levels: "sale_key|kind" -> {year: mean log price}; market: kind -> {year: mean}
        self.sale_level: Dict[str, Dict[int, float]] = defaultdict(dict)
        self.market_level: Dict[str, Dict[int, float]] = defaultdict(dict)
        # per "sale_key|kind": moments for regressing rel on (h, h^2), h = hip_pct - 0.5.
        # Some sales run best-first (Keeneland books); others are alphabetical.
        self.hip_moments: Dict[str, List[float]] = defaultdict(lambda: [0.0] * 9)
        self.lfee_fill: float = 9.5
        self.through_year: Optional[int] = None

    # ----------------------------------------------------------------- lookups
    def fee(self, sire_k: str, year: Optional[int]) -> Optional[float]:
        hist = self.fees.get(sire_k)
        if not hist or year is None:
            return None
        for y in range(year, year - FEE_MAX_LAG - 1, -1):
            if y in hist:
                return hist[y]
        return None

    def _level(self, table: Dict[int, float], year: int) -> Optional[float]:
        for y in range(year - 1, year - SALE_LEVEL_MAX_LAG - 1, -1):
            if y in table:
                return table[y]
        return None

    def _match_sale(self, skey: str, kind: str) -> Optional[str]:
        """Exact sale key, else the training sale whose name ends with / best overlaps it."""
        exact = f"{skey}|{kind}"
        if exact in self.sale_level:
            return exact
        want = set(skey.split())
        if not want:
            return None
        best, best_score = None, 0.0
        for key in self.sale_level:
            name, k = key.rsplit("|", 1)
            if k != kind:
                continue
            if name.endswith(skey):
                return key
            have = set(name.split())
            score = len(want & have) / len(want | have)
            if score > best_score:
                best, best_score = key, score
        return best if best_score >= 0.6 else None

    def hip_curve(self, skey: Optional[str], hip_pct: Optional[float]) -> float:
        """Earlier years' price-vs-hip curve at this sale, evaluated at this hip (0 when unknown)."""
        if not skey or hip_pct is None or skey not in self.hip_moments:
            return 0.0
        n, s1, s2, s11, s12, s22, sr, s1r, s2r = self.hip_moments[skey]
        if n < 30:
            return 0.0
        a = [[n, s1, s2], [s1, s11, s12], [s2, s12, s22]]
        rhs = [sr, s1r, s2r]
        coef = _solve3(a, rhs)
        if coef is None:
            return 0.0
        h = float(hip_pct) - 0.5
        # centre so the curve averages 0 over the sale's own hips
        fitted = coef[1] * (h - s1 / n) + coef[2] * (h * h - s2 / n)
        return fitted * n / (n + HIP_K)

    def raw_stats(self, lot: Dict[str, Any]) -> Dict[str, Any]:
        """As-of stats for one lot. Keys: sire_k, dam_k, damsire_k, sale_key, kind, year, sex, hip_pct."""
        year = int(lot["year"])
        kind = lot["kind"]
        sire_k, dam_k = lot.get("sire_k") or "", lot.get("dam_k") or ""
        ds_k = lot.get("damsire_k") or self.dam_sire.get(dam_k, "")
        skey = self._match_sale(lot.get("sale_key") or "", kind)
        cover_year = lot.get("birth_year")
        cover_year = int(cover_year) - 1 if cover_year else (year - 2 if kind == "Y" else year - 1)
        return {
            "kind": kind,
            "filly": _sex_flag(lot.get("sex")),
            "sale_level": self._level(self.sale_level.get(skey, {}), year) if skey else None,
            "market_level": self._level(self.market_level.get(kind, {}), year),
            "market_prev": self._level(self.market_level.get(kind, {}), year - 1),
            "fee_cover": self.fee(sire_k, cover_year),
            "fee_sale": self.fee(sire_k, year),
            "sire": tuple(self.sire.get(sire_k, (0.0, 0))),
            "sire_gsw": self.sire_gsw.get(sire_k, 0),
            "damsire_known": bool(ds_k),
            "damsire": tuple(self.damsire.get(ds_k, (0.0, 0))) if ds_k else (0.0, 0),
            "nick": tuple(self.nick.get(f"{sire_k}|{ds_k}", (0.0, 0))) if ds_k else (0.0, 0),
            "dam": tuple(self.dam.get(dam_k, (0.0, 0))),
            "dam_gsw": self.dam_gsw.get(dam_k, 0),
            "dam_gsp": self.dam_gsp.get(dam_k, 0),
            "dam_own": self.own.get(dam_k, 0),
            "hip_pct": lot.get("hip_pct"),
            "hip_signal": self.hip_curve(skey, lot.get("hip_pct")),
            "damsire_k": ds_k,
            "sale_matched_key": skey,
        }

    def features(self, raw: Dict[str, Any]) -> Dict[str, float]:
        """Raw as-of stats -> model features (identical in training and the app)."""
        market = raw["market_level"]
        level = raw["sale_level"]
        sale_new = level is None
        if level is None:
            level = market if market is not None else 10.0
        fee_c, fee_s = raw["fee_cover"], raw["fee_sale"]
        sire_sum, sire_n = raw["sire"]
        ds_sum, ds_n = raw["damsire"]
        nk_sum, nk_n = raw["nick"]
        dam_sum, dam_n = raw["dam"]
        hip = raw.get("hip_pct")
        hip = 0.5 if hip is None else float(hip)
        return {
            "sale_level": float(level),
            "sale_new": float(sale_new),
            "market_trend": (
                market - raw["market_prev"]
                if market is not None and raw.get("market_prev") is not None
                else 0.0
            ),
            "weanling": float(raw["kind"] == "W"),
            "filly": float(raw["filly"] or 0),
            "log_fee": math.log(fee_c) if fee_c else self.lfee_fill,
            "fee_missing": float(not fee_c),
            "fee_momentum": math.log(fee_s / fee_c) if fee_c and fee_s else 0.0,
            "sire_rel": sire_sum / (sire_n + self.k["sire"]),
            "sire_log_n": math.log1p(sire_n),
            "sire_log_gsw": math.log1p(raw["sire_gsw"]),
            "damsire_rel": ds_sum / (ds_n + self.k["damsire"]),
            "damsire_missing": float(not raw["damsire_known"]),
            "nick": nk_sum / (nk_n + self.k["nick"]),
            "dam_rel": dam_sum / (dam_n + self.k["dam"]),
            "dam_log_n": math.log1p(dam_n),
            "dam_log_gsw": math.log1p(raw["dam_gsw"]),
            "dam_log_gsp": math.log1p(raw["dam_gsp"]),
            "dam_own_gsw": float(raw["dam_own"] == 2),
            "dam_own_gsp": float(raw["dam_own"] == 1),
            "hip_signal": raw.get("hip_signal", 0.0),
            "hip_pct": hip,
            "hip_pct_sq": hip * hip,
        }

    # ----------------------------------------------------------------- updates
    def add_graded(self, events: Iterable[Tuple[str, str, int]]) -> None:
        """events: (sire_k, dam_k, level) with level 2 = graded winner, 1 = graded placed only."""
        for sire_k, dam_k, level in events:
            if level == 2:
                self.sire_gsw[sire_k] += 1
                self.dam_gsw[dam_k] += 1
            else:
                self.dam_gsp[dam_k] += 1

    def add_sale(self, rows: List[Dict[str, Any]], year: int) -> None:
        """Fold one sale year's sold lots into the tables (after their own features were taken).

        Each row needs: sire_k, dam_k, damsire_k, sale_key, kind, lp (log price),
        rel (lp minus its sale's mean), sire_rel and damsire_rel (as-of features).
        """
        levels: Dict[str, List[float]] = defaultdict(list)
        market: Dict[str, List[float]] = defaultdict(list)
        for r in rows:
            skey = f"{r['sale_key']}|{r['kind']}"
            levels[skey].append(r["lp"])
            hip = r.get("hip_pct")
            if hip is not None:
                h = hip - 0.5
                m = self.hip_moments[skey]
                for j, v in enumerate((1.0, h, h * h, h * h, h ** 3, h ** 4, r["rel"], h * r["rel"], h * h * r["rel"])):
                    m[j] += v
            market[r["kind"]].append(r["lp"])
            rel = r["rel"]
            for table, key in ((self.sire, r["sire_k"]), (self.dam, r["dam_k"])):
                if key:
                    table[key][0] += rel
                    table[key][1] += 1
            ds = r.get("damsire_k")
            if ds:
                self.damsire[ds][0] += rel
                self.damsire[ds][1] += 1
                nk = self.nick[f"{r['sire_k']}|{ds}"]
                nk[0] += rel - r["sire_rel"] - r["damsire_rel"]
                nk[1] += 1
        for key, vals in levels.items():
            self.sale_level[key][year] = sum(vals) / len(vals)
        for kind, vals in market.items():
            self.market_level[kind][year] = sum(vals) / len(vals)
        self.through_year = year

    # ----------------------------------------------------------------- storage
    def to_json(self, keep_dams: Optional[set] = None) -> Dict[str, Any]:
        def num(d):
            return {k: [round(v[0], 5), v[1]] for k, v in d.items() if v[1]}

        own = self.own if keep_dams is None else {k: v for k, v in self.own.items() if k in keep_dams}
        dam_sire = self.dam_sire if keep_dams is None else {
            k: v for k, v in self.dam_sire.items() if k in keep_dams
        }
        return {
            "k": self.k,
            "lfee_fill": self.lfee_fill,
            "through_year": self.through_year,
            "fees": {s: {str(y): f for y, f in h.items()} for s, h in self.fees.items()},
            "sire": num(self.sire),
            "damsire": num(self.damsire),
            "nick": {k: v for k, v in num(self.nick).items() if v[1] >= 2},
            "dam": num(self.dam),
            "sire_gsw": dict(self.sire_gsw),
            "dam_gsw": dict(self.dam_gsw),
            "dam_gsp": dict(self.dam_gsp),
            "own": own,
            "dam_sire": dam_sire,
            "sale_level": {k: {str(y): round(v, 5) for y, v in t.items()} for k, t in self.sale_level.items()},
            "market_level": {k: {str(y): round(v, 5) for y, v in t.items()} for k, t in self.market_level.items()},
            "hip_moments": dict(self.hip_moments),
        }

    @classmethod
    def from_json(cls, blob: Dict[str, Any]) -> "History":
        h = cls()
        h.k = blob["k"]
        h.lfee_fill = blob["lfee_fill"]
        h.through_year = blob.get("through_year")
        h.fees = defaultdict(dict, {s: {int(y): f for y, f in t.items()} for s, t in blob["fees"].items()})
        for name in ("sire", "damsire", "nick", "dam"):
            getattr(h, name).update({k: list(v) for k, v in blob[name].items()})
        h.sire_gsw.update(blob["sire_gsw"])
        h.dam_gsw.update(blob["dam_gsw"])
        h.dam_gsp.update(blob["dam_gsp"])
        h.own = dict(blob["own"])
        h.hip_moments.update({k: list(v) for k, v in blob.get("hip_moments", {}).items()})
        h.dam_sire = dict(blob["dam_sire"])
        for name in ("sale_level", "market_level"):
            getattr(h, name).update(
                {k: {int(y): v for y, v in t.items()} for k, t in blob[name].items()}
            )
        return h


def _solve3(a: List[List[float]], b: List[float]) -> Optional[List[float]]:
    """Solve a 3x3 linear system (Gaussian elimination with partial pivoting)."""
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None
        m[col], m[piv] = m[piv], m[col]
        for r in range(3):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][3] / m[i][i] for i in range(3)]


# --------------------------------------------------------------------- scoring
def linear(coef: Dict[str, float], feats: Dict[str, float]) -> float:
    return coef.get("intercept", 0.0) + sum(coef[f] * feats[f] for f in coef if f != "intercept")


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


_LOCK = threading.Lock()
_MODEL: Optional[Dict[str, Any]] = None
_LOADED = False


def load(path: Path = ARTIFACT_PATH, force: bool = False) -> Optional[Dict[str, Any]]:
    """Load the trained artifact once; None when it has not been trained yet."""
    global _MODEL, _LOADED
    with _LOCK:
        if _LOADED and not force:
            return _MODEL
        _LOADED = True
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                blob = json.load(fh)
            blob["history"] = History.from_json(blob["history"])
            _MODEL = blob
        except (OSError, ValueError, KeyError):
            _MODEL = None
        return _MODEL


def predict_lot(
    *,
    sire: str,
    dam: str,
    damsire: str = "",
    sex: str = "",
    kind: str,
    sale_year: int,
    birth_year: Optional[int] = None,
    catalog_title: str = "",
    hip_pct: Optional[float] = None,
    model: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Expected hammer if sold (median, p25-p75, p10-p90), fair value and Boom% for one Y/W lot."""
    model = model or load()
    if not model or kind not in ("Yearling", "Weanling", "Y", "W"):
        return None
    hist: History = model["history"]
    raw = hist.raw_stats(
        {
            "year": int(sale_year),
            "kind": kind[:1].upper(),
            "sire_k": name_key(sire),
            "dam_k": name_key(dam),
            "damsire_k": name_key(damsire),
            "sale_key": sale_key(catalog_title),
            "birth_year": birth_year,
            "sex": sex,
            "hip_pct": hip_pct,
        }
    )
    feats = hist.features(raw)
    variant = "with_hip" if hip_pct is not None else "no_hip"
    price = model["price"][variant]
    mu = linear(price["coef"], feats)
    sigma = price["sigma"]
    # Censored fit prices every lot incl. buy-backs; lots that sell run above that by
    # sold_shift (mean training residual of sold lots) -> the expected hammer if sold.
    fair = math.exp(mu)
    mu += price.get("sold_shift", 0.0)
    sigma = price.get("sold_sigma", sigma)
    boom_p = _sigmoid(linear(model["boom"][variant]["coef"], feats))
    return {
        "median": math.exp(mu),
        "fair_value": fair,
        "mean": math.exp(mu + sigma * sigma / 2.0),
        "low": math.exp(mu - Z50 * sigma),
        "high": math.exp(mu + Z50 * sigma),
        "p10": math.exp(mu - Z80 * sigma),
        "p90": math.exp(mu + Z80 * sigma),
        "log_mu": mu,
        "sigma": sigma,
        "boom_pct": 100.0 * boom_p,
        "variant": variant,
        "features": feats,
        "fee_at_cover": raw["fee_cover"],
        "sale_matched": not bool(feats["sale_new"]),
        "damsire_used": raw["damsire_k"],
        "trained_through": hist.through_year,
        # Only lots whose own sale (this sale, this year) is in the training data are backtests.
        "in_sample": bool(raw["sale_matched_key"])
        and int(sale_year) in hist.sale_level.get(raw["sale_matched_key"], {}),
        "holdout": {
            "price": price.get("holdout"),
            "boom": model["boom"][variant].get("holdout"),
        },
    }
