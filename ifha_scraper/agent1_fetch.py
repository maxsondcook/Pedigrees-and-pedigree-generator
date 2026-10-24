#!/usr/bin/env python3
"""Fetcher for IFHA Group/Graded stakes race results (ifhaonline.org).

The site is classic ASP. Two request shapes are needed:

  1. Listing  POST default.asp?section=Racing&area=7  with the search-form body.
     Returns every matching race for one (year, group) slice in a single
     response -- there is no pagination. Omitting raceyear returns HTTP 500,
     so the job MUST be sliced by year.
  2. Detail   GET  default.asp?section=Racing&area=20&racepid=<pid>
     Returns the 1st/2nd/3rd finishers. The listing does NOT carry finishers,
     so one detail fetch per race is mandatory.

No session cookie is required: the POST responds identically with a cold jar.

Downstream parsers should use `iter_listings()` and `iter_race_details()`,
both of which yield (metadata_dict, raw_html) pairs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Iterable, Sequence

import httpx

BASE = "https://www.ifhaonline.org/default.asp"
LISTING_URL = f"{BASE}?section=Racing&area=7"
DETAIL_URL = f"{BASE}?section=Racing&area=20&racepid={{pid}}"
CONDITIONS_URL = f"{BASE}?section=Racing&area=8&racepid={{pid}}"

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Every field the area=0 search form submits. Values left empty mean "< ALL >".
FORM_DEFAULTS = {
    "cntry": "",
    "raceyear": "",
    "track": "",
    "FromDate": "",
    "ToDate": "",
    "FromPurse": "",
    "ToPurse": "",
    "FromDistance": "",
    "ToDistance": "",
    "distanceunit": "F",
    "group": "",
    "age": "",
    "sex": "",
    "Sort": "",
    "sCntry": "",
    "Submit": "Submit",
}

RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4

# The Content-Type header carries no charset, so httpx would guess utf-8 and
# mangle the currency symbols (£ ¥ as 0xA3/0xA5). The pages' own meta tag says
# iso-8859-1; cp1252 is its superset and decodes every byte without error.
SITE_ENCODING = "cp1252"


def listing_payload(year: int | str, group: str = "") -> dict[str, str]:
    """Build the POST body for one (year, group) slice.

    `group` is "G1" / "G2" / "G3", or "" for all three at once (the server
    returns exactly the union, so "" costs one request instead of three).
    """
    payload = dict(FORM_DEFAULTS)
    payload["raceyear"] = str(year)
    payload["group"] = group
    return payload


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #


def cache_key(method: str, url: str, data: dict | None = None) -> str:
    blob = json.dumps(
        {"m": method.upper(), "u": url, "d": data or {}}, sort_keys=True
    ).encode()
    return hashlib.sha256(blob).hexdigest()


class HtmlCache:
    """Flat on-disk cache keyed by a hash of (method, url, body).

    Sharded one level deep so the directory stays usable at ~31k entries.
    A cached page is never re-downloaded, which makes re-runs free and the
    whole job resumable after an interrupt.
    """

    def __init__(self, directory: Path = CACHE_DIR):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def path_for(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.html"

    def get(self, key: str) -> str | None:
        p = self.path_for(key)
        if p.is_file() and p.stat().st_size > 0:
            self.hits += 1
            return p.read_text(encoding="utf-8", errors="replace")
        self.misses += 1
        return None

    def put(self, key: str, html: str) -> None:
        p = self.path_for(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(html, encoding="utf-8", errors="replace")
        tmp.replace(p)


# --------------------------------------------------------------------------- #
# fetcher
# --------------------------------------------------------------------------- #


@dataclass
class Stats:
    requests: int = 0
    cache_hits: int = 0
    retries: int = 0
    failures: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def mean_latency(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0.0


class IfhaFetcher:
    def __init__(
        self,
        concurrency: int = 3,
        delay: float = 1.5,
        timeout: float = 45.0,
        cache_dir: Path = CACHE_DIR,
    ):
        self.delay = delay
        self.cache = HtmlCache(cache_dir)
        self.stats = Stats()
        self._sem = asyncio.Semaphore(concurrency)
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout

    async def __aenter__(self) -> "IfhaFetcher":
        self._client = httpx.AsyncClient(
            http2=False,
            timeout=self._timeout,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{BASE}?section=Racing&area=0",
            },
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def fetch(self, method: str, url: str, data: dict | None = None) -> str:
        key = cache_key(method, url, data)
        cached = self.cache.get(key)
        if cached is not None:
            self.stats.cache_hits += 1
            return cached

        assert self._client is not None, "use IfhaFetcher as an async context manager"
        async with self._sem:
            last_err: Exception | None = None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    t0 = time.perf_counter()
                    if method.upper() == "POST":
                        resp = await self._client.post(url, data=data)
                    else:
                        resp = await self._client.get(url)
                    elapsed = time.perf_counter() - t0
                    self.stats.requests += 1
                    self.stats.latencies.append(elapsed)

                    if resp.status_code in RETRY_STATUS:
                        raise httpx.HTTPStatusError(
                            f"status {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )
                    resp.raise_for_status()
                    resp.encoding = SITE_ENCODING
                    html = resp.text
                    self.cache.put(key, html)
                    await asyncio.sleep(self.delay)
                    return html

                except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
                    last_err = exc
                    if attempt == MAX_ATTEMPTS:
                        break
                    self.stats.retries += 1
                    backoff = (2 ** (attempt - 1)) * self.delay + random.uniform(0, 0.75)
                    print(
                        f"  retry {attempt}/{MAX_ATTEMPTS - 1} after {backoff:.1f}s "
                        f"({type(exc).__name__}) {url}",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(backoff)

            self.stats.failures += 1
            raise RuntimeError(f"giving up on {method} {url}: {last_err}")

    async def fetch_listing(self, year: int | str, group: str = "") -> str:
        return await self.fetch("POST", LISTING_URL, listing_payload(year, group))

    async def fetch_detail(self, pid: str) -> str:
        return await self.fetch("GET", DETAIL_URL.format(pid=pid))

    async def fetch_conditions(self, pid: str) -> str:
        return await self.fetch("GET", CONDITIONS_URL.format(pid=pid))


# --------------------------------------------------------------------------- #
# minimal listing scan -- just enough to enumerate racepids for the detail pass
# --------------------------------------------------------------------------- #

# <TD><b><a href='...area=8&racepid=59931'>NAME</a> </b></td> ... area=20&racepid=59931
ROW_RE = re.compile(
    r"area=8&racepid=(?P<pid>\d+)'>(?P<race>.*?)</a>.*?"
    r"<TD align='center' >(?P<country>[^<]*)</td>"
    r"<TD align='center'>(?P<track>[^<]*)</td>"
    r"<TD align='center'><small>(?P<date>[^<]*)</small></td>"
    r"<TD align='center'><small>(?P<distance>[^<]*)</small></td>"
    r"<TD align='center'>(?P<agesex>.*?)</td>"
    r"<TD align='center'>(?P<purse>[^<]*)</td>"
    r"<TD align='center'>(?P<group>[^<]*)</td>",
    re.S,
)


def scan_listing(html: str) -> list[dict[str, str]]:
    """Pull one dict per race out of an area=7 listing page."""
    rows = []
    for m in ROW_RE.finditer(html):
        d = {k: (v or "").strip() for k, v in m.groupdict().items()}
        d["race"] = re.sub(r"<[^>]+>", "", d["race"]).strip()
        d["agesex"] = re.sub(r"<br\s*/?>", "|", d["agesex"], flags=re.I)
        d["agesex"] = re.sub(r"<[^>]+>", "", d["agesex"]).strip("| ")
        rows.append(d)
    return rows


def racepids(html: str) -> list[str]:
    seen, out = set(), []
    for pid in re.findall(r"area=20&racepid=(\d+)", html):
        if pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


# --------------------------------------------------------------------------- #
# public async iterators for downstream parsers
# --------------------------------------------------------------------------- #


async def iter_listings(
    fetcher: IfhaFetcher, years: Iterable[int], groups: Sequence[str] = ("",)
) -> AsyncIterator[tuple[dict, str]]:
    """Yield ({'kind':'listing','year':..,'group':..}, raw_html) per slice."""
    for year in years:
        for group in groups:
            html = await fetcher.fetch_listing(year, group)
            yield {"kind": "listing", "year": year, "group": group}, html


async def iter_race_details(
    fetcher: IfhaFetcher,
    years: Iterable[int],
    groups: Sequence[str] = ("",),
    with_conditions: bool = False,
) -> AsyncIterator[tuple[dict, str]]:
    """Yield (metadata, raw_detail_html) for every race in the given slices.

    `metadata` carries the listing-level fields (country, track, date,
    distance, age/sex, purse, group, race name, racepid) so a parser can join
    them onto the finishers it extracts from the detail HTML.
    """
    async for slice_meta, listing_html in iter_listings(fetcher, years, groups):
        rows = scan_listing(listing_html)
        by_pid = {r["pid"]: r for r in rows}
        pids = racepids(listing_html)

        async def one(pid: str) -> tuple[dict, str]:
            html = await fetcher.fetch_detail(pid)
            meta = {
                "kind": "race_detail",
                "racepid": pid,
                "query_year": slice_meta["year"],
                "query_group": slice_meta["group"],
                **by_pid.get(pid, {}),
            }
            if with_conditions:
                meta["conditions_html"] = await fetcher.fetch_conditions(pid)
            return meta, html

        for coro in asyncio.as_completed([one(p) for p in pids]):
            yield await coro


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_years(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


async def amain() -> int:
    ap = argparse.ArgumentParser(description="Fetch IFHA graded stakes pages.")
    ap.add_argument("--years", default="2015", help="e.g. 2015 or 2003-2026 or 2015,2020")
    ap.add_argument(
        "--groups",
        default="",
        help="comma list of G1,G2,G3; empty string (default) fetches all three in one request",
    )
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--listing-only", action="store_true", help="skip per-race detail fetches")
    ap.add_argument("--limit", type=int, default=0, help="stop after N detail pages (0 = no limit)")
    args = ap.parse_args()

    years = parse_years(args.years)
    groups = [g.strip() for g in args.groups.split(",")] if args.groups else [""]

    t0 = time.perf_counter()
    async with IfhaFetcher(concurrency=args.concurrency, delay=args.delay) as f:
        if args.listing_only:
            async for meta, html in iter_listings(f, years, groups):
                rows = scan_listing(html)
                print(
                    f"{meta['year']} group={meta['group'] or 'ALL':3s} "
                    f"-> {len(racepids(html)):5d} races, {len(rows):5d} rows parsed"
                )
        else:
            n = 0
            per_year: dict[int, int] = {}
            async for meta, html in iter_race_details(f, years, groups):
                n += 1
                per_year[meta["query_year"]] = per_year.get(meta["query_year"], 0) + 1
                if n <= 3:
                    print(f"  sample: pid={meta['racepid']} {meta.get('race','?')} "
                          f"({meta.get('country','?')} {meta.get('date','?')}) "
                          f"html={len(html)}B")
                if n % 50 == 0:
                    print(f"  ... {n} detail pages", file=sys.stderr)
                if args.limit and n >= args.limit:
                    break
            for y, c in sorted(per_year.items()):
                print(f"{y}: {c} race detail pages fetched")

    el = time.perf_counter() - t0
    s = f.stats
    print(
        f"\ndone in {el:.1f}s | network requests={s.requests} cache_hits={s.cache_hits} "
        f"retries={s.retries} failures={s.failures} mean_latency={s.mean_latency:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
