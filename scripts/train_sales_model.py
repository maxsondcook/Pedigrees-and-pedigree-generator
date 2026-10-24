"""
Train the yearling / weanling sale-price (Tobit) and Boom% (logistic) models.

    pip install -r requirements-model.txt
    python scripts/train_sales_model.py [--data-dir data] [--quick]

Reads the local CSV copies in data/ (sales_lots, stud_fees, race_horses,
graded_stakes), replays history year by year through crossr_core.sales_model.History
so every lot only sees earlier years, then:

  1. price: censored-normal regression of log hammer price; RNAs are upper bounds
     (the horse failed to make its reserve), outs are dropped.
  2. boom: logistic regression of "won a graded / Group race anywhere".
  3. rolling held-out tests by sale year (price) and foal crop (boom),
     drop-one feature tests, sire-clustered standard errors.
  4. keeps a feature only if p < 0.01 AND dropping it hurts held-out fit.

Writes Analyzed Sales/sales_model.json.gz (runtime artifact) and
docs/sales-model-results.md (generated tables).
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, special, stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crossr_core import sales_model as sm  # noqa: E402

P_KEEP = 0.01
PRICE_FIRST_YEAR = 2003  # stud fees start 2001 -> first covered yearlings sell 2003
PRICE_TEST_YEARS = list(range(2010, 2026))
PRICE_ABLATION = (2017, list(range(2018, 2026)))  # train <= 2017, test 2018-2025
BOOM_LAST_CROP = 2021  # crops young enough to still be winning are excluded
BOOM_LAG = 4  # crop c is scored with outcomes known for crops <= c - 4
BOOM_TEST_CROPS = list(range(2008, BOOM_LAST_CROP + 1))
BOOM_ABLATION = (2013, list(range(2017, BOOM_LAST_CROP + 1)))


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# =============================================================== data assembly
def load_sales(data: Path) -> pd.DataFrame:
    cols = ["catalog_year", "catalog_title", "source_file", "hip", "name", "sex_letter",
            "sire", "dam", "damsire", "birth_year", "price_num", "is_rna", "is_out"]
    df = pd.read_csv(data / "sales_lots.csv", usecols=cols, low_memory=False)
    df["age"] = df.catalog_year - df.birth_year
    hipn = pd.to_numeric(df.hip.astype(str).str.extract(r"(\d+)")[0], errors="coerce")
    df["hip_pct"] = hipn.groupby(df.source_file).rank(pct=True)
    return df


def build_maps(df: pd.DataFrame, data: Path):
    """dam->sire map, graded events, per-horse own level, and Y/W boom outcomes."""
    rh = pd.read_csv(data / "race_horses.csv", usecols=["name_key", "foal_year", "sex", "sire", "dam"],
                     low_memory=False)
    rh["k"] = rh.name_key.map(sm.name_key)
    rh["sire_k"] = rh.sire.map(sm.name_key)
    rh["dam_k"] = rh.dam.map(sm.name_key)

    dam_sire = {}
    mares = df[(df.age >= 2) & df.sex_letter.isin(["F", "M"])]
    for k, s in zip(mares.name.map(sm.name_key), mares.sire.map(sm.name_key)):
        if k and s:
            dam_sire[k] = s
    for k, s in zip(rh.k[rh.sex.isin(["F", "M"])], rh.sire_k[rh.sex.isin(["F", "M"])]):
        if k and s:
            dam_sire[k] = s

    gs = pd.read_csv(data / "graded_stakes.csv", usecols=["Horse Name", "Place", "Race Year", "Foaling Year"],
                     low_memory=False)
    gs["k"] = gs["Horse Name"].map(sm.name_key)
    gs["fy"] = pd.to_numeric(gs["Foaling Year"], errors="coerce")
    gs["yr"] = pd.to_numeric(gs["Race Year"], errors="coerce")
    gs["place"] = pd.to_numeric(gs.Place, errors="coerce")
    gs = gs.dropna(subset=["fy", "yr"])
    won = gs[gs.place == 1].groupby(["k", "fy"]).yr.min().rename("won")
    placed = gs[gs.place.isin([2, 3])].groupby(["k", "fy"]).yr.min().rename("placed")
    horses = pd.concat([won, placed], axis=1).reset_index()
    horses["level"] = np.where(horses.won.notna(), 2, 1)
    horses["year"] = horses.won.fillna(horses.placed).astype(int)
    own = dict(zip(horses.k, horses.level))  # name-only, max level kept below
    for k, lv in zip(horses.k, horses.level):
        own[k] = max(own.get(k, 0), lv)

    ped = rh.dropna(subset=["foal_year"]).drop_duplicates(["k", "foal_year"])
    horses = horses.merge(ped[["k", "foal_year", "sire_k", "dam_k"]], left_on=["k", "fy"],
                          right_on=["k", "foal_year"], how="inner")
    events = horses[["year", "sire_k", "dam_k", "level"]].sort_values("year")
    outcome = horses[horses.level == 2].drop_duplicates(["sire_k", "dam_k", "fy"])
    gsw_keys = set(zip(outcome.sire_k, outcome.dam_k, outcome.fy.astype(int)))
    log(f"graded horses linked to pedigree: {len(horses):,} ({(horses.level == 2).sum():,} winners)")
    return dam_sire, events, own, gsw_keys


def load_fees(data: Path) -> dict:
    sf = pd.read_csv(data / "stud_fees.csv")
    sf["k"] = sf.Stallion.map(sm.name_key)
    sf["fee"] = pd.to_numeric(sf["Stud Fee"].astype(str).str.replace(r"[^\d.]", "", regex=True), errors="coerce")
    sf = sf[(sf.fee > 0) & (sf.fee < 1_000_000)]
    fees = defaultdict(dict)
    for (k, y), f in sf.groupby(["k", "Year"]).fee.max().items():
        fees[k][int(y)] = float(f)
    return fees


def youngstock(df: pd.DataFrame) -> pd.DataFrame:
    yw = df[df.age.isin([0, 1]) & (df.is_out == 0) & (df.price_num > 0)].copy()
    yw["filly"] = yw.sex_letter.map(sm._sex_flag)
    yw = yw[yw.filly.notna()]
    yw["kind"] = np.where(yw.age == 1, "Y", "W")
    yw["sire_k"] = yw.sire.map(sm.name_key)
    yw["dam_k"] = yw.dam.map(sm.name_key)
    yw["damsire_k"] = yw.damsire.map(sm.name_key)
    yw["sale_key"] = yw.catalog_title.map(sm.sale_key)
    yw["lp"] = np.log(yw.price_num)
    yw["sold"] = yw.is_rna == 0
    sale_mean = yw.lp.where(yw.sold).groupby([yw.source_file, yw.kind]).transform("mean")
    yw["rel"] = yw.lp - sale_mean
    return yw.reset_index(drop=True)


def eb_k(values: pd.Series, groups: pd.Series) -> float:
    """Empirical-Bayes shrinkage constant: within-group variance / between-group variance."""
    d = pd.DataFrame({"v": values.values, "g": groups.values})
    d = d[d.g != ""]
    agg = d.groupby("g").v.agg(["mean", "var", "count"])
    agg = agg[agg["count"] >= 2]
    within = float(np.average(agg["var"], weights=agg["count"] - 1))
    between = float(agg["mean"].var() - (within / agg["count"]).mean())
    return round(within / max(between, 1e-6), 2)


def replay(yw: pd.DataFrame, hist: sm.History, events: pd.DataFrame) -> np.ndarray:
    """Year-by-year as-of features; folds each year into hist only after scoring it."""
    feats = np.zeros((len(yw), len(sm.PRICE_FEATURES)))
    ds_used = [""] * len(yw)
    ev = list(events.itertuples(index=False))
    ei = 0
    for year, block in yw.groupby("catalog_year", sort=True):
        while ei < len(ev) and ev[ei].year < year:
            hist.add_graded([(ev[ei].sire_k, ev[ei].dam_k, ev[ei].level)])
            ei += 1
        sold_rows = []
        for i, r in zip(block.index, block.itertuples(index=False)):
            raw = hist.raw_stats({
                "year": year, "kind": r.kind, "sire_k": r.sire_k, "dam_k": r.dam_k,
                "damsire_k": r.damsire_k, "sale_key": r.sale_key, "birth_year": r.birth_year,
                "sex": r.sex_letter, "hip_pct": None if pd.isna(r.hip_pct) else r.hip_pct,
            })
            f = hist.features(raw)
            feats[i] = [f[n] for n in sm.PRICE_FEATURES]
            ds_used[i] = raw["damsire_k"]
            if r.sold:
                sold_rows.append({
                    "sire_k": r.sire_k, "dam_k": r.dam_k, "damsire_k": raw["damsire_k"],
                    "sale_key": r.sale_key, "kind": r.kind, "lp": r.lp, "rel": r.rel,
                    "sire_rel": f["sire_rel"], "damsire_rel": f["damsire_rel"],
                    "hip_pct": None if pd.isna(r.hip_pct) else float(r.hip_pct),
                })
        hist.add_sale(sold_rows, int(year))
    while ei < len(ev):
        hist.add_graded([(ev[ei].sire_k, ev[ei].dam_k, ev[ei].level)])
        ei += 1
    yw["damsire_used"] = ds_used
    return feats


# ===================================================================== fitting
def _std(X):
    mu = X.mean(0)
    sd = X.std(0)
    sd[sd == 0] = 1.0
    return mu, sd


def fit_tobit(X, y, upper):
    """Censored normal. upper=True rows: true log price < y (RNA). Returns (beta incl. intercept, sigma, info)."""
    mu_x, sd_x = _std(X)
    Z = np.column_stack([np.ones(len(X)), (X - mu_x) / sd_x])
    obs = ~upper
    p = Z.shape[1]

    def nll(theta):
        b, ls = theta[:p], theta[p]
        s = math.exp(ls)
        e = (y - Z @ b) / s
        ll_o = -0.5 * e[obs] ** 2 - ls - 0.5 * math.log(2 * math.pi)
        lc = special.log_ndtr(e[upper])
        g = np.zeros_like(e)
        g[obs] = e[obs] / s
        lam = np.exp(stats.norm.logpdf(e[upper]) - lc)
        g[upper] = -lam / s
        grad_b = -(Z.T @ g)
        grad_ls = -(np.sum(e[obs] ** 2 - 1) + np.sum(-lam * e[upper]))
        return -(ll_o.sum() + lc.sum()), np.append(grad_b, grad_ls)

    b0 = np.linalg.lstsq(Z[obs], y[obs], rcond=None)[0]
    theta0 = np.append(b0, math.log(np.std(y[obs] - Z[obs] @ b0)))
    res = optimize.minimize(nll, theta0, jac=True, method="L-BFGS-B", options={"maxiter": 2000})
    theta = res.x
    return theta, (mu_x, sd_x), nll


def tobit_scores(theta, Z, y, upper):
    p = Z.shape[1]
    b, ls = theta[:p], theta[p]
    s = math.exp(ls)
    e = (y - Z @ b) / s
    g = np.where(~upper, e / s, 0.0)
    lam = np.zeros_like(e)
    lc = special.log_ndtr(e[upper])
    lam[upper] = np.exp(stats.norm.logpdf(e[upper]) - lc)
    g[upper] = -lam[upper] / s
    sb = Z * g[:, None]
    sls = np.where(~upper, e ** 2 - 1, -lam * e)
    return np.column_stack([sb, sls])


def fit_logit(X, y, ridge=1e-4):
    mu_x, sd_x = _std(X)
    Z = np.column_stack([np.ones(len(X)), (X - mu_x) / sd_x])
    b = np.zeros(Z.shape[1])
    b[0] = math.log(y.mean() / (1 - y.mean()))
    for _ in range(50):
        pr = special.expit(Z @ b)
        W = pr * (1 - pr)
        H = (Z * W[:, None]).T @ Z + ridge * np.eye(len(b))
        step = np.linalg.solve(H, Z.T @ (y - pr) - ridge * b)
        b += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return b, (mu_x, sd_x)


def _unstandardize(b_std, scale, names):
    mu_x, sd_x = scale
    slopes = b_std[1:] / sd_x
    intercept = b_std[0] - float(np.sum(slopes * mu_x))
    coef = {"intercept": float(intercept)}
    coef.update({n: float(v) for n, v in zip(names, slopes)})
    return coef


def cluster_se(scores, hess_inv, clusters):
    """Sandwich SEs with observations grouped by cluster (sire)."""
    codes, _ = pd.factorize(clusters)
    G = codes.max() + 1
    S = np.zeros((G, scores.shape[1]))
    np.add.at(S, codes, scores)
    meat = S.T @ S
    V = hess_inv @ meat @ hess_inv * G / (G - 1)
    return np.sqrt(np.diag(V))


def numeric_hessian(fun, theta, eps=1e-5):
    p = len(theta)
    H = np.zeros((p, p))
    for j in range(p):
        d = np.zeros(p)
        d[j] = eps
        H[:, j] = (fun(theta + d)[1] - fun(theta - d)[1]) / (2 * eps)
    return (H + H.T) / 2


def significance_table(names, coef_std, se_std, scale):
    """Coefficients / SEs back on the original feature scale, with z, p, 95% CI."""
    _, sd_x = scale
    rows = []
    for j, n in enumerate(names):
        b = coef_std[j + 1] / sd_x[j]
        se = se_std[j + 1] / sd_x[j]
        z = b / se if se > 0 else float("nan")
        rows.append({"feature": n, "coef": b, "se": se, "z": z,
                     "p": float(2 * stats.norm.sf(abs(z))), "lo95": b - 1.96 * se, "hi95": b + 1.96 * se})
    return rows


# ================================================================== price model
def price_design(yw, F, names, mask):
    idx = [sm.PRICE_FEATURES.index(n) for n in names]
    return F[mask][:, idx], yw.lp.values[mask], ~yw.sold.values[mask]


def sold_adjustment(coef, names, X, y, up):
    """Mean / SD of training residuals among sold lots: shifts the censored fit to 'hammer if sold'."""
    r = y[~up] - (coef["intercept"] + X[~up] @ np.array([coef[n] for n in names]))
    return float(r.mean()), float(r.std())


def price_eval(yw, F, names, train, test):
    X, y, up = price_design(yw, F, names, train)
    theta, scale, _ = fit_tobit(X, y, up)
    coef = _unstandardize(theta[:-1], scale, names)
    sigma = math.exp(theta[-1])
    shift, sold_sigma = sold_adjustment(coef, names, X, y, up)
    Xt, yt, upt = price_design(yw, F, names, test)
    pred = coef["intercept"] + Xt @ np.array([coef[n] for n in names])
    # held-out censored log-likelihood per lot (sold + RNA), for model comparison
    zt = (yt - pred) / sigma
    ll = np.where(upt, special.log_ndtr(zt), stats.norm.logpdf(zt) - math.log(sigma))
    so = ~upt
    pred = pred + shift
    sigma = sold_sigma
    e = yt[so] - pred[so]
    return {
        "n": int(so.sum()),
        "r2": float(1 - np.sum(e ** 2) / np.sum((yt[so] - yt[so].mean()) ** 2)),
        "mae_log": float(np.mean(np.abs(e))),
        "median_abs_pct": float(np.median(np.abs(np.exp(pred[so]) - np.exp(yt[so])) / np.exp(yt[so]))),
        "coverage80": float(np.mean(np.abs(e) <= sm.Z80 * sigma)),
        "coverage50": float(np.mean(np.abs(e) <= sm.Z50 * sigma)),
        "bias_log": float(np.mean(e)),
        "ll": float(np.mean(ll)),
        "sigma": sigma,
        "_pred": pred[so],
        "_y": yt[so],
    }


def fee_band_baseline(yw, train, test, fees_hist):
    """The app's current method: median price of past sales in the sire's sale-year fee band."""
    import PriceProjection as pp

    fee_sale = np.array([fees_hist.fee(k, int(y)) or np.nan for k, y in zip(yw.sire_k, yw.catalog_year)])
    band = np.array([pp.fee_band_for(f)[0] if f == f else -1 for f in fee_sale])
    tr = train & yw.sold.values & (band >= 0)
    med = pd.Series(yw.lp.values[tr]).groupby(
        [band[tr], yw.kind.values[tr]]).median()
    te = test & yw.sold.values & (band >= 0)
    pred = np.array([med.get((b, k), np.nan) for b, k in zip(band[te], yw.kind.values[te])])
    return te, pred


def summarize(per_year):
    keys = ["r2", "mae_log", "median_abs_pct", "coverage80", "coverage50", "bias_log", "ll"]
    n = np.array([r["n"] for r in per_year])
    return {k: float(np.average([r[k] for r in per_year], weights=n)) for k in keys} | {"n": int(n.sum())}


# Features that only make sense together are tested and kept as a unit.
PAIRS = (("hip_pct", "hip_pct_sq"), ("log_fee", "fee_missing"))


def feature_groups(names):
    groups, seen = [], set()
    for n in names:
        if n in seen:
            continue
        grp = next((list(p) for p in PAIRS if n in p), [n])
        grp = [g for g in grp if g in names]
        seen.update(grp)
        groups.append(grp)
    return groups


def select(names, sig, ablation):
    """Keep a group if its best p < P_KEEP and dropping it lowers held-out log-likelihood."""
    p = {r["feature"]: r["p"] for r in sig}
    keep = []
    for grp in feature_groups(names):
        if min(p[g] for g in grp) < P_KEEP and ablation.get(grp[0], 0.0) > 0:
            keep.extend(grp)
    return keep


def run_price(yw, F, hist, variant):
    names = [n for n in sm.PRICE_FEATURES if variant == "with_hip" or n not in sm.HIP_FEATURES]
    years = yw.catalog_year.values
    base = years >= PRICE_FIRST_YEAR
    if variant == "with_hip":
        base &= ~np.isnan(yw.hip_pct.values)

    def full_fit(cols):
        mask = base
        X, y, up = price_design(yw, F, cols, mask)
        theta, scale, nll = fit_tobit(X, y, up)
        H = numeric_hessian(nll, theta)
        mu_x, sd_x = scale
        Z = np.column_stack([np.ones(len(X)), (X - mu_x) / sd_x])
        scores = tobit_scores(theta, Z, y, up)
        se = cluster_se(scores, np.linalg.inv(H), yw.sire_k.values[mask])
        return theta, scale, significance_table(cols, theta[:-1], se[:-1], scale)

    def ablate(cols):
        cut, test_years = PRICE_ABLATION
        train = base & (years <= cut)
        test = base & np.isin(years, test_years)
        ref = price_eval(yw, F, cols, train, test)
        out = {}
        for grp in feature_groups(cols):
            rest = [c for c in cols if c not in grp]
            r = price_eval(yw, F, rest, train, test)
            for g in grp:
                out[g] = ref["ll"] - r["ll"]  # >0: dropping it hurts held-out fit
            log(f"  price[{variant}] drop {'+'.join(grp)}: d_ll={ref['ll'] - r['ll']:+.4f} dR2={ref['r2'] - r['r2']:+.4f}")
        return out

    log(f"price[{variant}]: candidate fit + drop-one tests")
    _, _, sig0 = full_fit(names)
    abl0 = ablate(names)
    keep = select(names, sig0, abl0)
    dropped = [n for n in names if n not in keep]
    log(f"price[{variant}]: keep {keep}; drop {dropped}")

    theta, scale, sig = full_fit(keep)
    coef = _unstandardize(theta[:-1], scale, keep)
    sigma = math.exp(theta[-1])
    X, y, up = price_design(yw, F, keep, base)
    sold_shift, sold_sigma = sold_adjustment(coef, keep, X, y, up)

    log(f"price[{variant}]: rolling held-out by sale year")
    per_year, base_rows = [], []
    for Y in PRICE_TEST_YEARS:
        train = base & (years < Y)
        test = base & (years == Y)
        r = price_eval(yw, F, keep, train, test)
        te, bpred = fee_band_baseline(yw, train, test, hist)
        sold_test = test & yw.sold.values
        on = np.isin(np.flatnonzero(sold_test), np.flatnonzero(te))
        ok = ~np.isnan(bpred)
        yb = yw.lp.values[te][ok]
        m_pred = r["_pred"][on][ok]
        base_rows.append({
            "year": Y, "n": int(ok.sum()),
            "model_mae_log": float(np.mean(np.abs(yb - m_pred))),
            "band_mae_log": float(np.mean(np.abs(yb - bpred[ok]))),
            "model_r2": float(1 - np.sum((yb - m_pred) ** 2) / np.sum((yb - yb.mean()) ** 2)),
            "band_r2": float(1 - np.sum((yb - bpred[ok]) ** 2) / np.sum((yb - yb.mean()) ** 2)),
        })
        r = {k: v for k, v in r.items() if not k.startswith("_")} | {"year": Y}
        per_year.append(r)
        log(f"  {Y}: n={r['n']:,} R2={r['r2']:.3f} MAE={r['mae_log']:.3f} cov80={r['coverage80']:.3f}"
            f" | vs fee band (n={base_rows[-1]['n']:,}) R2 {base_rows[-1]['model_r2']:.3f} vs {base_rows[-1]['band_r2']:.3f}")
    nb = np.array([b["n"] for b in base_rows])
    baseline = {k: float(np.average([b[k] for b in base_rows], weights=nb))
                for k in ("model_mae_log", "band_mae_log", "model_r2", "band_r2")} | {"n": int(nb.sum())}
    return {
        "coef": coef, "sigma": sigma, "sold_shift": sold_shift, "sold_sigma": sold_sigma,
        "features": keep, "dropped": dropped,
        "n_train": int(base.sum()), "significance": sig, "candidate_significance": sig0,
        "ablation_ll": abl0, "holdout": summarize(per_year), "holdout_by_year": per_year,
        "vs_fee_band": baseline, "vs_fee_band_by_year": base_rows,
    }


# =================================================================== boom model
def auc(y, p):
    order = np.argsort(p)
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    pos = y == 1
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum()))


def boom_eval(X, y, names, train, test):
    b, scale = fit_logit(X[train], y[train])
    coef = _unstandardize(b, scale, names)
    p = special.expit(coef["intercept"] + X[test] @ np.array([coef[n] for n in names]))
    yt = y[test]
    base = y[train].mean()
    eps = 1e-12
    ll = float(np.mean(yt * np.log(p + eps) + (1 - yt) * np.log(1 - p + eps)))
    brier = float(np.mean((p - yt) ** 2))
    return {"n": int(test.sum()), "events": int(yt.sum()), "auc": auc(yt, p), "ll": ll, "brier": brier,
            "brier_base": float(np.mean((base - yt) ** 2)), "_p": p, "_y": yt}


def run_boom(yw, F, gsw_keys, variant):
    names = [n for n in sm.PRICE_FEATURES if variant == "with_hip" or n not in sm.HIP_FEATURES]
    idx = [sm.PRICE_FEATURES.index(n) for n in names]
    d = yw.assign(_row=np.arange(len(yw)))
    d = d[d.birth_year <= BOOM_LAST_CROP]
    if variant == "with_hip":
        d = d[d.hip_pct.notna()]
    # one row per horse: its last youngstock sale (pinhooked weanlings resold as yearlings)
    d = d.sort_values("catalog_year").drop_duplicates(["sire_k", "dam_k", "birth_year"], keep="last")
    y = np.array([(s, m, int(c)) in gsw_keys for s, m, c in zip(d.sire_k, d.dam_k, d.birth_year)], dtype=float)
    X = F[d._row.values][:, idx]
    crop = d.birth_year.values.astype(int)
    sires = d.sire_k.values
    log(f"boom[{variant}]: {len(d):,} horses, {int(y.sum()):,} graded winners ({y.mean():.2%})")

    def full_fit(cols):
        ci = [names.index(c) for c in cols]
        Xc = X[:, ci]
        b, scale = fit_logit(Xc, y)
        mu_x, sd_x = scale
        Z = np.column_stack([np.ones(len(Xc)), (Xc - mu_x) / sd_x])
        pr = special.expit(Z @ b)
        H = (Z * (pr * (1 - pr))[:, None]).T @ Z
        se = cluster_se(Z * (y - pr)[:, None], np.linalg.inv(H), sires)
        return b, scale, significance_table(cols, b, se, scale)

    def ablate(cols):
        cut, test_crops = BOOM_ABLATION
        train = crop <= cut
        test = np.isin(crop, test_crops)
        ci = [names.index(c) for c in cols]
        ref = boom_eval(X[:, ci], y, cols, train, test)
        out = {}
        for grp in feature_groups(cols):
            rest = [c for c in cols if c not in grp]
            ri = [names.index(c) for c in rest]
            r = boom_eval(X[:, ri], y, rest, train, test)
            for g in grp:
                out[g] = ref["ll"] - r["ll"]
            log(f"  boom[{variant}] drop {'+'.join(grp)}: d_ll={ref['ll'] - r['ll']:+.5f} dAUC={ref['auc'] - r['auc']:+.4f}")
        return out

    _, _, sig0 = full_fit(names)
    abl0 = ablate(names)
    keep = select(names, sig0, abl0)
    dropped = [n for n in names if n not in keep]
    log(f"boom[{variant}]: keep {keep}; drop {dropped}")
    b, scale, sig = full_fit(keep)
    coef = _unstandardize(b, scale, keep)

    ci = [names.index(c) for c in keep]
    per, ps, ys = [], [], []
    for c in BOOM_TEST_CROPS:
        r = boom_eval(X[:, ci], y, keep, crop <= c - BOOM_LAG, crop == c)
        ps.append(r.pop("_p"))
        ys.append(r.pop("_y"))
        per.append(r | {"crop": c})
        log(f"  crop {c}: n={r['n']:,} events={r['events']} AUC={r['auc']:.3f} brier={r['brier']:.5f} (base {r['brier_base']:.5f})")
    p_all, y_all = np.concatenate(ps), np.concatenate(ys)
    dec = pd.qcut(pd.Series(p_all).rank(method="first"), 10, labels=False)
    calib = pd.DataFrame({"p": p_all, "y": y_all, "dec": dec}).groupby("dec").agg(
        predicted=("p", "mean"), observed=("y", "mean"), n=("y", "size"), events=("y", "sum"))
    pooled = {
        "n": int(len(y_all)), "events": int(y_all.sum()), "auc": auc(y_all, p_all),
        "brier": float(np.mean((p_all - y_all) ** 2)),
        "brier_base": float(np.average([r["brier_base"] for r in per], weights=[r["n"] for r in per])),
        "top_decile_rate": float(calib.observed.iloc[-1]), "bottom_decile_rate": float(calib.observed.iloc[0]),
        "base_rate": float(y_all.mean()),
    }
    pooled["brier_skill"] = 1 - pooled["brier"] / pooled["brier_base"]
    return {
        "coef": coef, "features": keep, "dropped": dropped, "n_train": int(len(y)), "events": int(y.sum()),
        "significance": sig, "candidate_significance": sig0, "ablation_ll": abl0,
        "holdout": pooled, "holdout_by_crop": per,
        "calibration": calib.reset_index().to_dict("records"),
    }


# ===================================================================== reports
FEATURE_DOC = {
    "sale_level": "Average log price at this sale in the previous year",
    "sale_new": "Sale not seen in the previous 2 years",
    "market_trend": "Change in the market's average log price over the last 2 years",
    "weanling": "Weanling (vs yearling)",
    "filly": "Filly (vs colt)",
    "log_fee": "Log sire stud fee in the conception year",
    "fee_missing": "No stud fee on file for the conception year",
    "fee_momentum": "Log change in sire fee, conception year to sale year",
    "sire_rel": "Sire's earlier foals: price vs their sale average (shrunk)",
    "sire_log_n": "Log(1 + sire's earlier foals sold)",
    "sire_log_gsw": "Log(1 + sire's graded winners to date)",
    "damsire_rel": "Damsire's earlier grand-foals: price vs sale average (shrunk)",
    "damsire_missing": "Damsire unknown",
    "nick": "Sire x damsire cross: earlier foals' price beyond sire + damsire (shrunk)",
    "dam_rel": "Dam's earlier foals: price vs sale average (shrunk)",
    "dam_log_n": "Log(1 + dam's earlier foals sold)",
    "dam_log_gsw": "Log(1 + dam's graded-winning foals to date)",
    "dam_log_gsp": "Log(1 + dam's graded-placed foals to date)",
    "dam_own_gsw": "Dam herself a graded winner",
    "dam_own_gsp": "Dam herself graded placed",
    "hip_signal": "This sale's earlier-years price curve by hip position, at this hip (shrunk)",
    "hip_pct": "Hip position within the catalog (0 = first, 1 = last)",
    "hip_pct_sq": "Hip position squared",
}


def _sig_md(rows, effect):
    out = ["| Feature | Coef | 95% CI | p | Effect |", "|---|---|---|---|---|"]
    for r in rows:
        p = "<0.0001" if r["p"] < 1e-4 else f"{r['p']:.4f}"
        out.append(f"| {r['feature']} — {FEATURE_DOC.get(r['feature'], '')} | {r['coef']:+.4f} | "
                   f"[{r['lo95']:+.4f}, {r['hi95']:+.4f}] | {p} | {effect(r)} |")
    return "\n".join(out)


def _pct(x):
    return f"{100 * (math.exp(x) - 1):+.1f}%"


def write_report(path: Path, art: dict) -> None:
    lines = ["# Sales model — generated results", "",
             f"Generated by `scripts/train_sales_model.py` on {art['trained_at']} from data through "
             f"{art['history_through']}. See `docs/sales-model.md` for the method.", ""]
    for variant in ("with_hip", "no_hip"):
        pr = art["price"][variant]
        h = pr["holdout"]
        vb = pr["vs_fee_band"]
        lines += [f"## Price model ({variant.replace('_', ' ')})", "",
                  f"Training lots: {pr['n_train']:,} (sold + RNA). Censored-fit SD (log): {pr['sigma']:.3f}. "
                  f"Sold lots average {pr['sold_shift']:+.3f} log above the censored fit "
                  f"(×{math.exp(pr['sold_shift']):.2f}); sold-lot SD {pr['sold_sigma']:.3f} "
                  f"(80% range ≈ ÷/× {math.exp(sm.Z80 * pr['sold_sigma']):.2f}).", "",
                  f"Held-out by sale year {PRICE_TEST_YEARS[0]}–{PRICE_TEST_YEARS[-1]} (n={h['n']:,} sold lots): "
                  f"R² {h['r2']:.3f}, MAE {h['mae_log']:.3f} log, median abs error {100 * h['median_abs_pct']:.0f}%, "
                  f"p25–p75 coverage {100 * h['coverage50']:.1f}% (target 50%), "
                  f"p10–p90 coverage {100 * h['coverage80']:.1f}% (target 80%), bias {h['bias_log']:+.3f} log.", "",
                  f"Same lots as the current fee-band projection (n={vb['n']:,}): R² {vb['model_r2']:.3f} vs "
                  f"{vb['band_r2']:.3f}; MAE {vb['model_mae_log']:.3f} vs {vb['band_mae_log']:.3f} log.", "",
                  "Kept features (sire-clustered SEs):", "",
                  _sig_md(pr["significance"], lambda r: f"{_pct(r['coef'])} per unit"), "",
                  f"Dropped (p ≥ {P_KEEP} or no held-out gain): {', '.join(pr['dropped']) or 'none'}", "",
                  "| Year | n | R² | MAE (log) | 80% coverage |", "|---|---|---|---|---|"]
        lines += [f"| {r['year']} | {r['n']:,} | {r['r2']:.3f} | {r['mae_log']:.3f} | {100 * r['coverage80']:.1f}% |"
                  for r in pr["holdout_by_year"]]
        bm = art["boom"][variant]
        hb = bm["holdout"]
        lines += ["", f"## Boom% model ({variant.replace('_', ' ')})", "",
                  f"Horses: {bm['n_train']:,}, graded winners: {bm['events']:,}.", "",
                  f"Held-out crops {BOOM_TEST_CROPS[0]}–{BOOM_TEST_CROPS[-1]} (trained on crops ≥ {BOOM_LAG} years older): "
                  f"AUC {hb['auc']:.3f}, Brier skill {100 * hb['brier_skill']:.1f}% vs base rate, "
                  f"top decile {100 * hb['top_decile_rate']:.2f}% vs bottom {100 * hb['bottom_decile_rate']:.2f}% "
                  f"(base {100 * hb['base_rate']:.2f}%).", "",
                  "Kept features:", "",
                  _sig_md(bm["significance"], lambda r: f"odds ×{math.exp(r['coef']):.2f} per unit"), "",
                  f"Dropped: {', '.join(bm['dropped']) or 'none'}", "",
                  "| Predicted decile | Predicted | Observed | n |", "|---|---|---|---|"]
        lines += [f"| {c['dec'] + 1} | {100 * c['predicted']:.2f}% | {100 * c['observed']:.2f}% | {c['n']:,} |"
                  for c in bm["calibration"]]
        lines.append("")
    path.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(sm.ARTIFACT_PATH))
    ap.add_argument("--report", default=str(ROOT / "docs" / "sales-model-results.md"))
    args = ap.parse_args()
    data = Path(args.data_dir)

    log("loading sales")
    df = load_sales(data)
    dam_sire, events, own, gsw_keys = build_maps(df, data)
    fees = load_fees(data)
    yw = youngstock(df)
    del df
    log(f"youngstock lots: {len(yw):,} ({yw.sold.sum():,} sold, {(~yw.sold).sum():,} RNA)")

    early = yw[yw.sold & (yw.catalog_year < 2010)]
    ks = {
        "sire": eb_k(early.rel, early.sire_k),
        "dam": eb_k(early.rel, early.dam_k),
        "damsire": eb_k(early.rel, early.damsire_k.where(early.damsire_k != "", early.dam_k.map(dam_sire).fillna(""))),
    }
    ks["nick"] = ks["damsire"]
    log(f"empirical-Bayes shrinkage k: {ks}")

    def new_history():
        h = sm.History()
        h.k = dict(ks)
        h.fees = defaultdict(dict, {k: dict(v) for k, v in fees.items()})
        h.own = own
        h.dam_sire = dam_sire
        lf = [math.log(f) for v in fees.values() for f in v.values()]
        h.lfee_fill = float(np.median(lf))
        return h

    hist = new_history()
    log("replaying history year by year")
    F = replay(yw, hist, events)

    # as-of check: tables rebuilt through 2024 must reproduce 2025 training features
    chk_hist = new_history()
    pre = yw[yw.catalog_year <= 2024].reset_index(drop=True)
    replay(pre, chk_hist, events[events.year < 2025])
    sample = yw[yw.catalog_year == 2025].sample(500, random_state=1)
    worst = 0.0
    for i, r in zip(sample.index, sample.itertuples(index=False)):
        raw = chk_hist.raw_stats({"year": 2025, "kind": r.kind, "sire_k": r.sire_k, "dam_k": r.dam_k,
                                  "damsire_k": r.damsire_k, "sale_key": r.sale_key, "birth_year": r.birth_year,
                                  "sex": r.sex_letter, "hip_pct": None if pd.isna(r.hip_pct) else r.hip_pct})
        f = chk_hist.features(raw)
        worst = max(worst, float(np.max(np.abs(np.array([f[n] for n in sm.PRICE_FEATURES]) - F[i]))))
    log(f"as-of consistency check (runtime vs training features): max abs diff {worst:.2e}")
    assert worst < 1e-9, "runtime features diverge from training features"
    del chk_hist, pre

    art = {"version": 1, "trained_at": time.strftime("%Y-%m-%d"), "history_through": int(yw.catalog_year.max()),
           "shrinkage_k": ks, "price": {}, "boom": {}}
    for variant in ("with_hip", "no_hip"):
        art["price"][variant] = run_price(yw, F, hist, variant)
        art["boom"][variant] = run_boom(yw, F, gsw_keys, variant)

    blob = dict(art)
    blob["history"] = hist.to_json()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(blob, fh, separators=(",", ":"))
    log(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    write_report(Path(args.report), art)
    log(f"wrote {args.report}")


if __name__ == "__main__":
    main()
