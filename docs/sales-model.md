# Sales model: expected sale price and Boom%

Fitted, validated replacement for the fee-band "Projected Price" on yearling and
weanling lots. Full generated tables (every coefficient, CI, p-value, year-by-year
held-out scores, calibration) are in [sales-model-results.md](sales-model-results.md).

- Runtime: `crossr_core/sales_model.py` (pure Python, ~12 µs per lot)
- Training: `scripts/train_sales_model.py` → `Analyzed Sales/sales_model.json.gz`
- Wiring: `crossr_core/projections.py::project_lot_market`
  (set `CROSSR_SALES_MODEL=0` to fall back to the fee bands)

## What was agreed

| Output | Definition | Status |
|---|---|---|
| Expected sale price | Hammer price if the lot sells | Built |
| Boom% | P(wins a graded / Group race anywhere in the world) | Built |
| Bust% | P(never starts) | Waiting on dam produce records |
| Value (fair price) | PV at 7%/yr of expected gross race earnings + mean breeding value | Waiting on dam produce records |

RNAs are treated as censored (the horse was worth less than the reserve it failed
to reach); outs are dropped. Private sales are not in the data.

## Data

`sales_lots` youngstock (catalog year − birth year = 0 or 1), 1999–2026: 184,499
lots (166,537 sold, 17,962 RNA with a price). Stud fees from `stud_fees` (2001+;
only ~47% of lots have a conception-year fee). Graded results from
`graded_stakes`, linked to sire/dam/foal year through `race_horses` (99.9% of
graded winners link), giving 1,606 graded winners among 145,752 youngstock horses
from the 1998–2021 crops.

## No look-ahead

Every feature is computed **as of the sale**: `History` replays the sales year by
year and a lot only sees earlier years' sales and graded results. The app uses
the same object (its final state is the artifact), and training asserts that
runtime features reproduce training features exactly (max difference 0).

## Features (candidates)

Sale level (last year's average log price at this sale), sex, weanling, sire stud
fee at conception (+ missing flag), fee change from conception to sale, sire /
damsire / dam earlier-foal prices relative to their sale (empirical-Bayes shrunk;
k estimated from pre-2010 data: sire 2.3, dam 1.8, damsire 7.9), sire × damsire
cross (nick) residual, counts of earlier foals and graded winners/placed, dam's
own graded record, and hip position (proxy for book/session).

Hip position is **per sale**: Keeneland sells best-first in books, so late hips
sell far lower, while Fasig-Tipton's single-session sales are alphabetical and
show no hip gradient once pedigree is accounted for. `hip_signal` is each sale's
own earlier-years price curve by hip (quadratic, refit as of every sale, shrunk
by n / (n + 200) lots; 0 for a sale with no history). A single pooled hip curve
was also a candidate and the rule dropped it.

**Selection rule (agreed):** a feature (or pair, e.g. fee + missing flag) is kept
only if p < 0.01 with sire-clustered standard errors **and** dropping it lowers
held-out log-likelihood (train ≤ 2017, test 2018–2025). Market trend, weanling,
number of sire foals, missing damsire and dam's graded-winner/placed foal counts
and the pooled hip curve failed for price.

## Models

**Price:** censored-normal (Tobit) regression of log price. Because the censored
fit prices every lot including buy-backs, lots that sell average 14% above it
(estimated from training residuals); the displayed figure is the expected hammer
**if it sells**, with the p25–p75 range (p10–p90 also returned). The censored
"fair value" is returned too.

**Boom%:** logistic regression on the same candidates. A crop is scored with a
model trained only on crops at least 4 years older (their outcomes were known).

Two variants of each: with hip position (catalog lots) and without (horse pages
that do not know the hip).

## Held-out accuracy

Rolling by sale year 2010–2025 (train on all earlier years, score the next):

| | With hip | No hip | Current fee bands |
|---|---|---|---|
| R² (log price) | **0.54** | 0.45 | — |
| R² on lots the fee bands can price (n=70,647) | **0.56** | 0.49 | 0.43 |
| Median absolute error | 58% | 63% | — |
| p25–p75 range contains price | 51.3% (target 50) | 50.8% | — |
| p10–p90 range contains price | 81.1% (target 80) | 81.1% | — |

Honest noise level: a single horse's 80% range is about ÷/× 3.8. The data has no
conformation, vet or consignor information for most lots, so most of the spread is
irreducible from what we hold. Remaining bias: prices run ~6% above prediction on
average (+0.07 log), which is the market's year-over-year growth the model can't foresee.

Boom%, crops 2008–2021: AUC 0.69 (with hip) / 0.65; the top predicted decile
produced graded winners at 3.5% vs 0.54% in the bottom decile (base 1.2%), and
predicted rates match observed rates decile by decile.

Per-sale hip curve vs the pooled hip curve it replaced, same held-out horses:
price R² improved in 15 of 16 sale years (mean +0.040; paired t p = 2×10⁻⁸, sign
test p = 0.0005). Boom% AUC 0.675 → 0.687 (DeLong p = 0.001; held-out log-loss gain
95% CI excludes 0 under a sire-cluster bootstrap; better in 11 of 14 crops, sign
test p = 0.06). Hip curve vs no hip feature at all: AUC 0.640 → 0.687 (p < 10⁻¹⁵).

## Key effects (price, with hip; all p < 0.0001)

- Filly: −16% vs colt
- Stud fee at conception: +10% fee → +1.8% price, on top of the sire's track record
  (the sire's earlier-foal prices carry most of the fee signal)
- Sire fee rising between conception and sale: +10% → +3.9%
- Dam herself graded winner: +10%; graded placed: +12%
- Hip position: same pedigree at Keeneland September, hip 5% vs 95% of the catalog:
  ~$690k vs ~$69k; at Fasig-Tipton October: ~$110k vs ~$117k (no effect)
- Each sire / damsire / dam / cross track-record term is strongly positive (see results)

## Retraining

```bash
pip install -r requirements-model.txt
python scripts/train_sales_model.py
```

Needs the local CSV copies in `data/` (sales_lots, stud_fees, race_horses,
graded_stakes). Takes about a minute. Retrain after new sales are loaded; a lot is
flagged `in_sample` (a backtest, not a forecast) when its own sale and year are in
the training data.

Renamed sales are merged through `SALE_ALIASES` in `crossr_core/sales_model.py`
(Fasig-Tipton Eastern Fall Yearlings = Midlantic Fall Yearlings since 2013).

## Next

1. Bust% and Value once the dam produce records (every foal, starts, earnings,
   stud/broodmare outcome) land.
2. Re-run selection with the requested data: complete stud fees, book/session,
   catalog pedigree pages (foaling date, black type), Keeneland consignors.
3. The catalog price filter (`expected_market_mid_for_filter`) still uses fee bands.
