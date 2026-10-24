#!/usr/bin/env python3
"""Fetch BloodHorse archive pages with real headed Chrome (Playwright).

Headless Chrome + spoofed UA is blocked by Imperva ("Pardon Our Interruption").
A persistent headed Chrome profile with the real browser UA passes.

Imports parse/write helpers from scrape_sirelists.py only. Does not touch
the Pedigrees repo.
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from multiprocessing import Process
from pathlib import Path

from playwright.sync_api import sync_playwright

from scrape_sirelists import (
    AEI_PDF_YEARS,
    PAGES,
    CACHE_DIR,
    MISSES_PATH,
    PageSpec,
    cache_path,
    csv_has_data,
    csv_path,
    download_aei_pdf,
    fallback_headers,
    is_blocked,
    is_login_wall,
    page_url,
    parse_aei_pdf_file,
    parse_page,
    write_csv,
    verify_2004_general,
)

SCRAPER_DIR = Path("/Users/maxsoncook/Desktop/stallion_rankings_data/bloodhorse_sirelists")
PROFILE_BASE = SCRAPER_DIR / "chrome_profile"
HOME_URL = "https://www.bloodhorse.com/"


def page_complete(year: int, spec: PageSpec) -> bool:
    return all(csv_has_data(csv_path(year, title)) for title in spec.outputs.values())


def cache_usable(path: Path) -> str | None:
    if not path.exists():
        return None
    html = path.read_text(encoding="utf-8", errors="replace")
    if not html or is_blocked(html):
        return None
    if "<table" not in html.lower():
        return None
    return html


class MissLog:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        MISSES_PATH.parent.mkdir(parents=True, exist_ok=True)

    def write(self, year: int, title: str, reason: str, url: str) -> None:
        with self.lock:
            with MISSES_PATH.open("a", encoding="utf-8") as fh:
                fh.write(f"{year}\t{title}\t{reason}\t{url}\n")


def write_outputs(year: int, spec: PageSpec, html: str, url: str, misses: MissLog, status: str) -> int:
    if status == "login":
        for title in spec.outputs.values():
            if csv_has_data(csv_path(year, title)):
                continue
            write_csv(csv_path(year, title), fallback_headers(title, year))
            misses.write(year, title, "login-wall", url)
        return 0
    parsed = parse_page(html, spec, year) if html else {}
    written = 0
    for key, title in spec.outputs.items():
        dest = csv_path(year, title)
        if csv_has_data(dest):
            continue
        rows = parsed.get(key)
        if not rows or len(rows) <= 2:
            write_csv(dest, fallback_headers(title, year))
            reason = "unpublished-or-empty" if status != "no-table" else "no-table"
            if year == 2026:
                reason += "-2026-partial"
            misses.write(year, title, reason, url)
            continue
        write_csv(dest, rows)
        written += 1
    return written


def fetch_with_page(page, url: str, dest: Path) -> tuple[str, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = "empty"
    for attempt in range(1, 6):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            html = ""
            for tick in range(15):
                page.wait_for_timeout(1000)
                html = page.content()
                if is_blocked(html):
                    last = "blocked"
                    continue
                try:
                    page.wait_for_selector("table.sire-list", timeout=2500)
                except Exception:
                    pass
                html = page.content()
                if is_blocked(html):
                    last = "blocked"
                    continue
                break
        except Exception as exc:
            last = f"error:{exc}"
            time.sleep(2 * attempt)
            continue
        if is_blocked(html):
            last = "blocked"
            page.wait_for_timeout(3000 + attempt * 2000)
            continue
        dest.write_text(html, encoding="utf-8")
        if is_login_wall(html):
            return html, "login"
        if "table" not in html.lower():
            return html, "no-table"
        return html, "ok"
    return "", last


def warmup(page) -> None:
    try:
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        html = page.content()
        if is_blocked(html):
            # Give Imperva a chance to clear on a real headed session.
            page.wait_for_timeout(8000)
    except Exception as exc:
        print(f"warmup warning: {exc}", flush=True)


def worker(thread_jobs: list[tuple[int, PageSpec]], delay: float, profile_name: str) -> None:
    """Each process launches its own headed Chrome — sync API is not thread-safe."""
    misses = MissLog()
    profile = PROFILE_BASE / profile_name
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            channel="chrome",
            headless=False,
            locale="en-US",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            warmup(page)
            for year, spec in thread_jobs:
                url = page_url(spec, year)
                if page_complete(year, spec):
                    print(f"skip {year} {spec.seo_name}", flush=True)
                    continue
                html = cache_usable(cache_path(year, spec.seo_name))
                status = "ok-cache"
                if html is None:
                    time.sleep(delay + random.uniform(0.15, 0.55))
                    html, status = fetch_with_page(page, url, cache_path(year, spec.seo_name))
                    if status not in {"ok", "login", "no-table"}:
                        # Blocked/errors are retried later — do not write empty placeholders.
                        misses.write(year, spec.seo_name, status, url)
                        print(f"{year} {spec.seo_name}: {status} files=0", flush=True)
                        continue
                written = write_outputs(
                    year, spec, html, url, misses, status if status != "ok-cache" else "ok"
                )
                print(f"{year} {spec.seo_name}: {status} files={written}", flush=True)
        finally:
            context.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", default="2004-2026")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--delay", type=float, default=1.4)
    args = parser.parse_args()
    if "-" in args.years:
        a, b = args.years.split("-", 1)
        years = list(range(int(a), int(b) + 1))
    else:
        years = [int(x) for x in args.years.split(",") if x.strip()]

    # AEI 2004–2008 are magazine PDFs on the BloodHorse CDN, not HTML tables.
    aei_done = 0
    for year in years:
        if year not in AEI_PDF_YEARS:
            continue
        dest = csv_path(year, "Leading Sires by AEI")
        if csv_has_data(dest):
            continue
        pdf = download_aei_pdf(year)
        if not pdf:
            print(f"{year} lifetime-aei: pdf-missing", flush=True)
            continue
        rows = parse_aei_pdf_file(pdf, year)
        if len(rows) > 2:
            write_csv(dest, rows)
            aei_done += 1
            print(f"{year} lifetime-aei: pdf files=1 rows={len(rows)-1}", flush=True)
        else:
            print(f"{year} lifetime-aei: pdf-parse-empty", flush=True)

    jobs = [(y, p) for y in years for p in PAGES if not page_complete(y, p)]
    print(
        f"Remaining pages: {len(jobs)}  years={years}  "
        f"concurrency={args.concurrency}  aei_pdf={aei_done}",
        flush=True,
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not MISSES_PATH.exists():
        MISSES_PATH.write_text("")

    if not jobs:
        print("Nothing to fetch")
        if 2004 in years:
            verify_2004_general()
        return 0

    n = max(1, min(args.concurrency, 2))
    shards: list[list[tuple[int, PageSpec]]] = [[] for _ in range(n)]
    for i, job in enumerate(jobs):
        shards[i % n].append(job)

    if n == 1:
        worker(shards[0], args.delay, "headed1")
    else:
        procs = [
            Process(target=worker, args=(shard, args.delay, f"headed{i+1}"))
            for i, shard in enumerate(shards)
            if shard
        ]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join()
            if proc.exitcode not in (0, None):
                print(f"worker exitcode={proc.exitcode}", flush=True)

    if 2004 in years:
        verify_2004_general()
    return 0


if __name__ == "__main__":
    sys.exit(main())
