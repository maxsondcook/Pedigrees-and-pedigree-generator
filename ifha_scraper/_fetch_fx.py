"""One-off helper that builds ``fx_rates.json`` from the Frankfurter API (ECB data).

Run directly:  python3 ifha_scraper/_fetch_fx.py

Produces annual *average* rates expressed as **units of local currency per 1 USD**,
computed from the daily ECB reference series. Currencies the ECB does not publish
(pegged Gulf currencies, most Latin American currencies, MOP, RUB after 2022) are
not fetched here -- ``normalize.py`` supplies approximations for those.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request

API = "https://api.frankfurter.dev/v1"
START_YEAR = 2003
END_YEAR = 2026
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fx_rates.json")


def _get(url: str) -> dict:
    """GET JSON, falling back to curl when Python has no usable CA bundle."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ifha-normalize/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        out = subprocess.run(
            ["curl", "-sL", "--max-time", "60", url],
            capture_output=True, text=True, check=True,
        ).stdout
        return json.loads(out)


def main() -> None:
    symbols = sorted(k for k in _get(f"{API}/currencies") if k != "USD")
    annual: dict[str, dict[str, float]] = {}

    for year in range(START_YEAR, END_YEAR + 1):
        url = (
            f"{API}/{year}-01-01..{year}-12-31"
            f"?base=USD&symbols={','.join(symbols)}"
        )
        try:
            payload = _get(url)
        except Exception as exc:  # pragma: no cover - network dependent
            print(f"  {year}: FAILED ({exc})")
            continue

        totals: dict[str, list[float]] = {}
        for day_rates in payload.get("rates", {}).values():
            for code, rate in day_rates.items():
                totals.setdefault(code, []).append(float(rate))

        if not totals:
            print(f"  {year}: no data")
            continue

        annual[str(year)] = {
            code: round(sum(vals) / len(vals), 6) for code, vals in sorted(totals.items())
        }
        n_days = len(payload.get("rates", {}))
        print(f"  {year}: {len(totals)} currencies from {n_days} daily observations")

    out = {
        "_meta": {
            "source": "Frankfurter API (api.frankfurter.dev) -- ECB reference rates",
            "units": "units of local currency per 1 USD",
            "method": "unweighted mean of all published daily rates in the calendar year",
        },
        "rates": annual,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(f"wrote {OUT} ({len(annual)} years)")


if __name__ == "__main__":
    main()
