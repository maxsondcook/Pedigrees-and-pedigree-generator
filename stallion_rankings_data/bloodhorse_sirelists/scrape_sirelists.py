#!/usr/bin/env python3
"""Scrape BloodHorse archive sire lists (2004–2026) into 28 CSV types.

Does not import or touch the Pedigrees / pq_scraper codebase.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup, Tag

BASE_DIR = Path("/Users/maxsoncook/Desktop/stallion_rankings_data")
SCRAPER_DIR = BASE_DIR / "bloodhorse_sirelists"
CACHE_DIR = SCRAPER_DIR / "cache"
PROGRESS_PATH = SCRAPER_DIR / "progress.json"
MISSES_PATH = SCRAPER_DIR / "misses.log"
ARCHIVE_URL = (
    "https://www.bloodhorse.com/horse-racing/thoroughbred-breeding/sire-lists/archive"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

YEARS = list(range(2004, 2027))


@dataclass(frozen=True)
class PageSpec:
    seo_name: str
    kind: str  # "na" or "intl"
    outputs: dict[str, str]  # table_key -> title


# table_key for NA pages is always "main"
PAGES: list[PageSpec] = [
    PageSpec("general", "na", {"main": "Leading Sire Rankings"}),
    PageSpec("first-crop", "na", {"main": "Leading First Crop Sires"}),
    PageSpec("second-crop", "na", {"main": "Leading Second-Crop Sires"}),
    PageSpec("third-crop", "na", {"main": "Leading Third-Crop Sires"}),
    PageSpec("two-year-old", "na", {"main": "Leading Two-Year-Old Sires"}),
    PageSpec("turf", "na", {"main": "Leading Turf Sires"}),
    PageSpec("lifetime-aei", "na", {"main": "Leading Sires by AEI"}),
    PageSpec("broodmare", "na", {"main": "Leading Broodmare Sires"}),
    PageSpec(
        "international",
        "intl",
        {
            "summary": "Leading International Sires",
            "north-america": "Leading International Sires-North America",
            "europe-dubai": "Leading International Sires-Europe&Dubai",
            "japan-hongkong": "Leading International Sires-Japan&Hong Kong",
        },
    ),
    PageSpec(
        "international-first-crop",
        "intl",
        {
            "summary": "Leading International First-Crop Sires",
            "north-america": "Leading International First-CropSires-NorthAmerica",
            "europe-dubai": "Leading International First-CropSires-Europe&Dubai",
            "japan-hongkong": "LeadingInternational FirstCropSires-Japan&HongKong",
        },
    ),
    PageSpec(
        "international-second-crop",
        "intl",
        {
            "summary": "Leading International 2ndCrop Sires",
            "north-america": "Leading International 2ndCrop Sires-NorthAmerica",
            "europe-dubai": "Leading International 2ndCrop Sires-Europe&Dubai",
            "japan-hongkong": "Leading International 2ndCrop Sires-Japan&HongKong",
        },
    ),
    PageSpec(
        "international-third-crop",
        "intl",
        {
            "summary": "Leading International 3rdCrop Sires",
            "north-america": "Leading International 3rdCrop Sires-NorthAmerica",
            "europe-dubai": "Leading International 3rdCrop Sires-Europe&Dubai",
            "japan-hongkong": "Leading International 3rdCrop Sires-Japan&HongKong",
        },
    ),
    PageSpec(
        "international-two-year-old",
        "intl",
        {
            "summary": "Leading International Two-Year-Old Sires",
            "north-america": "LeadingInternational TwoYearOldSires-NorthAmerica",
            "europe-dubai": "LeadingInternational TwoYearOldSires-Europe&Dubai",
            "japan-hongkong": "LeadingInternationalTwoYearOldSires-Japan&HongKong",
        },
    ),
]


INTL_SUMMARY_GROUP = [
    "",
    "",
    "",
    "North America",
    "Europe & Dubai",
    "Japan & Hong Kong",
    "International",
]
INTL_SUMMARY_COLS = [
    "#",
    "Stallion",
    "Country",
    "Earnings",
    "Earnings",
    "Earnings",
    "{yy} Earnings",
]
INTL_REGION_GROUP = {
    "north-america": "North America",
    "europe-dubai": "Europe & Dubai",
    "japan-hongkong": "Japan & Hong Kong",
}
INTL_REGION_COLS = [
    "#",
    "Stallion",
    "Country",
    "Runners",
    "Winners",
    "SWnrs",
    "Earnings",
    "SWnrs",
    "SHs",
    "{yy} Earnings",
]


def yy(year: int) -> str:
    return f"{year % 100:02d}"


def fallback_headers(title: str, year: int) -> list[list[str]]:
    """2001-style headers with the target year substituted."""
    y = yy(year)
    earn = f"{y} Earnings"
    fee = f"{year - 3} Stud Fee / Farm"
    if title.startswith("Leading International") or title.startswith(
        "LeadingInternational"
    ):
        if any(
            x in title
            for x in (
                "Europe&Dubai",
                "Japan&Hong",
                "NorthAmerica",
                "North America",
            )
        ) and not title.endswith("Sires"):
            region = "North America"
            if "Europe" in title:
                region = "Europe & Dubai"
            elif "Japan" in title:
                region = "Japan & Hong Kong"
            group = ["", "", "", region, "", "", "", "International", "", ""]
            cols = [c.replace("{yy} Earnings", earn) for c in INTL_REGION_COLS]
            return [group, cols]
        # summary / overall international files end with "Sires" and have no region suffix
        cols = [c.replace("{yy} Earnings", earn) for c in INTL_SUMMARY_COLS]
        return [INTL_SUMMARY_GROUP, cols]
    if title == "Leading Broodmare Sires":
        return [
            [
                "#",
                "Stallion",
                "Dams",
                "Rnrs",
                "Wnrs",
                "SWrs",
                "Chief Earner, Earnings",
                earn,
                "Cum. SWrs",
                "Cum. Foals",
            ]
        ]
    if title == "Leading First Crop Sires":
        return [
            [
                "#",
                "Stallion",
                fee,
                "Current\n2YOs",
                "Rnrs",
                "Wnrs",
                "Rpt. Wnrs",
                "SWrs",
                "GSWrs",
                "SHs",
                "Yearling\nAverage",
                "Chief Earner\n(Earnings)",
                earn,
            ]
        ]
    if title == "Leading Second-Crop Sires":
        return [
            [
                "#",
                "Stallion",
                fee,
                "Rnrs",
                "Wnrs",
                "SWrs",
                "BT\nSWs",
                "Chief Earner\n(Earnings)",
                earn,
            ]
        ]
    if title == "Leading Third-Crop Sires":
        return [
            [
                "#",
                "Stallion",
                fee,
                "Rnrs",
                "Wnrs",
                "SWrs",
                "BT\nSWs",
                "Chief Earner\n(Earnings)",
                earn,
            ]
        ]
    if title == "Leading Two-Year-Old Sires":
        return [
            [
                "#",
                "Stallion",
                fee,
                "Current 2YOs",
                "Rnrs",
                "Wnrs",
                "SWrs",
                "SHs",
                "Chief Earner\n(Earnings)",
                earn,
                "(%)",
            ]
        ]
    if title == "Leading Turf Sires":
        return [
            ["", "", "", "All Surfaces", "", "", "Turf", "", "", "", ""],
            [
                "#",
                "Stallion",
                "Chief Earner\n(Earnings)",
                "Rnrs",
                "Wnrs",
                "SWrs",
                "Rnrs",
                "Wnrs",
                "SWrs",
                earn,
                "(%)",
            ],
        ]
    if title == "Leading Sires by AEI":
        return [
            [
                "Rank",
                "Stallion (Foreign foaled), Year, Sire, Where Stands",
                f"{year + 1} Stud Fee",
                "Crops / Avg Size",
                "Named Foals",
                "Lifetime Yearlings Sold / Average",
                f"{year - 3}–{year} Yearlings Sold / Average",
                "Stakes Winners",
                "Graded Stakes Winners",
                "Grade 1 Stakes Winners",
                "Comp Index",
                "AE Index",
            ]
        ]
    # Leading Sire Rankings
    return [
        [
            "#",
            "Stallion",
            fee,
            "Rnrs",
            "Wnrs",
            "Rpt. Wnrs",
            "SWrs",
            "BT\nSWs",
            "GSWrs",
            "G1SWrs",
            "Chief Earner\n(Earnings)",
            earn,
        ]
    ]


AEI_PDF_URL = (
    "https://cdn.bloodhorse.com/downloads/breeding/sirelists/pdfs/"
    "leading-sires-by-aei-{year}.pdf"
)
AEI_PDF_YEARS = set(range(2004, 2009))


def aei_headers(year: int) -> list[str]:
    return [
        "Rank",
        "Stallion (Foreign foaled), Year, Sire, Where Stands",
        f"{year + 1} Stud Fee",
        "Crops / Avg Size",
        "Named Foals",
        "Lifetime Yearlings Sold / Average",
        f"{year - 3}–{year} Yearlings Sold / Average",
        "Stakes Winners",
        "Graded Stakes Winners",
        "Grade 1 Stakes Winners",
        "Comp Index",
        "AE Index",
    ]


def parse_aei_pdf_text(text: str, year: int) -> list[list[str]]:
    """Parse BloodHorse magazine-style AEI PDF text into 2001-like rows."""
    raw = [re.sub(r"[.\u2026]{3,}", " ", ln) for ln in text.splitlines()]
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw]
    lines = [ln for ln in lines if ln]

    # 2007–2008: one field per line, or tab-separated blocks.
    block_re = re.compile(
        r"(?:^|\n)\s*(\d+)\.\s+([A-Z0-9 .'’/\-]+?(?:\([A-Za-z]+\))?)\s*,\s*"
        r"\((\d{2}),\s*([^)]+)\)(?:,\s*([^\n$]*?))?\s*\n"
        r"\s*(\$[0-9,]+M?|N/?A)\s*\n"
        r"\s*(\d+\s*/\s*\d+)\s*\n"
        r"\s*(\d[\d,]*)\s*\n"
        r"\s*(\d+)\s*/\s*\$([0-9,]+)\s*\n"
        r"\s*(\d+)\s*/\s*\$([0-9,]+)\s*\n"
        r"\s*(\d+)\s*-\s*(\d+%)\s*\n"
        r"\s*(\d+)\s*-\s*(\d+%)\s*\n"
        r"\s*(\d+)\s*-\s*(\d+%)\s*\n"
        r"\s*(\d+\.\d+)\s*\n"
        r"\s*(\d+\.\d+)",
        re.M,
    )
    block_rows: list[list[str]] = []
    for m in block_re.finditer("\n".join(lines)):
        g = m.groups()
        stands = (g[4] or "").strip().rstrip(",")
        stallion = f"{g[1].strip()} ({g[2]}, {g[3].strip()})"
        if stands:
            stallion += f", {stands}"
        block_rows.append(
            [
                g[0],
                stallion,
                g[5],
                g[6].replace(" ", ""),
                g[7],
                f"{g[8]} / ${g[9]}",
                f"{g[10]} / ${g[11]}",
                f"{g[12]} - {g[13]}",
                f"{g[14]} - {g[15]}",
                f"{g[16]} - {g[17]}",
                g[19],
                g[18],
            ]
        )
    if len(block_rows) >= 20:
        return [aei_headers(year)] + block_rows

    name_re = re.compile(
        r"^(?:(\d+)\.?\s+)?([A-Z][A-Z0-9 .'’/\-]+(?:\([A-Za-z]+\))?)\s+"
        r"\((\d{2}),\s*([^)]+)\),\s*(.+?)\s+"
        r"(\$[0-9,]+M?|NA|N/A)\s+"
        r"(\d+\s*/\s*\d+)\s+"
        r"(\d[\d,]*)\s*$"
    )
    yrlg_re = re.compile(
        r"(\d+)\s*/\s*\$?\s*([0-9,]+)\s+(\d+)\s*/\s*\$?\s*([0-9,]+)"
    )
    pct_re = re.compile(
        r"(\d+)\s*-?\s*(\d+%)\s+(\d+)\s*-?\s*(\d+%)\s+(\d+)\s*-?\s*(\d+%)"
    )
    idx_re = re.compile(r"(\d+\.\d+)\D+(\d+\.\d+)")

    rows: list[list[str]] = [aei_headers(year)]
    i = 0
    implied_rank = 0
    while i < len(lines):
        m = name_re.match(lines[i])
        if not m:
            i += 1
            continue
        rank, name, yob, sire, stands, fee, crops, foals = m.groups()
        implied_rank = int(rank) if rank else implied_rank + 1
        stallion = f"{name.strip()} ({yob}, {sire.strip()}), {stands.strip().rstrip(',. ')}"
        yrlg = pct = idx = None
        j = i + 1
        while j < min(i + 5, len(lines)) and not (yrlg and pct and idx):
            if yrlg is None:
                ym = yrlg_re.search(lines[j])
                if ym:
                    yrlg = ym
                    j += 1
                    continue
            if pct is None:
                pm = pct_re.search(lines[j])
                if pm:
                    pct = pm
                    j += 1
                    continue
            if idx is None:
                im = idx_re.search(lines[j])
                if im:
                    idx = im
                    j += 1
                    continue
            j += 1
        if not (yrlg and pct and idx):
            i += 1
            continue
        rows.append(
            [
                str(implied_rank),
                stallion,
                fee,
                crops.replace(" ", ""),
                foals,
                f"{yrlg.group(1)} / ${yrlg.group(2)}",
                f"{yrlg.group(3)} / ${yrlg.group(4)}",
                f"{pct.group(1)} - {pct.group(2)}",
                f"{pct.group(3)} - {pct.group(4)}",
                f"{pct.group(5)} - {pct.group(6)}",
                idx.group(2),
                idx.group(1),
            ]
        )
        i = j
    return rows


def download_aei_pdf(year: int) -> Path | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / f"{year}_lifetime-aei.pdf"
    if dest.exists() and dest.stat().st_size > 2000:
        return dest
    url = AEI_PDF_URL.format(year=year)
    try:
        resp = requests.get(url, timeout=45, headers={"User-Agent": UA})
    except requests.RequestException:
        return None
    if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
        return None
    dest.write_bytes(resp.content)
    return dest


def parse_aei_pdf_file(path: Path, year: int) -> list[list[str]]:
    import pymupdf

    doc = pymupdf.open(path)
    text = "\n".join(page.get_text("text") for page in doc)
    return parse_aei_pdf_text(text, year)


def csv_path(year: int, title: str) -> Path:
    return BASE_DIR / str(year) / f"{year}StallionRankings - {title}.csv"


def cache_path(year: int, seo_name: str) -> Path:
    return CACHE_DIR / f"{year}_{seo_name}.html"


def page_url(page: PageSpec, year: int) -> str:
    if page.kind == "na":
        q = {
            "RegionOptions": "region-america",
            "seoName": page.seo_name,
            "region": "",
            "year": str(year),
        }
    else:
        q = {"seoName": page.seo_name, "year": str(year)}
    return f"{ARCHIVE_URL}?{urlencode(q)}"


def is_blocked(html: str) -> bool:
    low = html.lower()
    if "pardon our interruption" in low:
        return True
    if "request unsuccessful" in low and "incapsula" in low:
        return True
    if "pardon our interruption" in unescape(html).lower():
        return True
    return False


def is_login_wall(html: str) -> bool:
    low = html.lower()
    if "sign in to continue" in low or "subscribe to view" in low:
        return True
    if "this content is for subscribers" in low:
        return True
    return False


def normalize_ws(text: str) -> str:
    text = unescape(text).replace("\xa0", " ").replace("\u200b", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def collapse_header_cell(text: str) -> str:
    text = normalize_ws(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text).strip()
    # BloodHorse: "'04 Earnings" -> "04 Earnings" to match 2001/2002
    text = re.sub(r"^'?(\d{2})\s+Earnings$", r"\1 Earnings", text)
    return text


def clean_data_cell(td: Tag) -> str:
    # Prefer structured stallion / fee / earner reconstruction.
    name_span = td.select_one("span.stallion-name")
    if name_span:
        name = name_span.get_text(" ", strip=True)
        name = re.sub(r"\s+", " ", name).strip()
        # pedigree is typically after <br> following the span
        rest_bits = []
        for sib in name_span.next_siblings:
            if isinstance(sib, str):
                bit = normalize_ws(sib).strip()
                if bit:
                    rest_bits.append(bit)
            elif isinstance(sib, Tag):
                if sib.name in {"br", "svg", "use"}:
                    continue
                bit = sib.get_text(" ", strip=True)
                bit = re.sub(r"\s+", " ", bit).strip()
                if bit:
                    rest_bits.append(bit)
        pedigree = " ".join(rest_bits).strip(" ,")
        if pedigree:
            return f"{name}\n{pedigree}"
        return name

    # Convert <br> to newlines, then tidy.
    for br in td.find_all("br"):
        br.replace_with("\n")
    text = normalize_ws(td.get_text("\n", strip=True))
    lines = [re.sub(r"[ \t]+", " ", ln).strip(" ,") for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    # Farm cells often become ["$10,000", "Farm", ", KY"] or ["$10,000", "Farm", "KY"]
    if len(lines) >= 3 and re.fullmatch(r"[A-Z]{2}|CAN", lines[-1]):
        farm = " ".join(lines[1:-1]).strip(" ,")
        lines = [lines[0], f"{farm}, {lines[-1]}"]
    elif len(lines) >= 2 and re.match(r"^,\s*[A-Z]{2}\b", lines[-1]):
        lines = [lines[0], f"{lines[1]}{lines[-1]}"] if len(lines) == 2 else [
            lines[0],
            f"{' '.join(lines[1:-1])}{lines[-1]}",
        ]
    # Chief earner: "Name" + "($123)" -> keep two-line form used in 2001 files
    return "\n".join(lines)


def classify_intl_table(table: Tag) -> str | None:
    first_cells: list[str] = []
    thead = table.find("thead")
    if thead:
        first_tr = thead.find("tr")
        if first_tr:
            first_cells = [
                collapse_header_cell(th.get_text(" ", strip=True)).lower()
                for th in first_tr.find_all(["th", "td"])
            ]
    blob = " | ".join(first_cells)
    has_europe = "europe" in blob
    has_japan = "japan" in blob
    has_na = "north america" in blob
    has_intl = "international" in blob
    if has_europe and has_japan and has_na:
        return "summary"
    if has_europe:
        return "europe-dubai"
    if has_japan:
        return "japan-hongkong"
    if has_na and has_intl:
        return "north-america"
    # nearby heading
    prev = table.find_previous(["h2", "h3", "h4", "caption"])
    if prev:
        label = collapse_header_cell(prev.get_text(" ", strip=True)).lower()
        if "summary" in label:
            return "summary"
        if "europe" in label:
            return "europe-dubai"
        if "japan" in label:
            return "japan-hongkong"
        if "north america" in label:
            return "north-america"
    return None


def parse_table(table: Tag, year: int, kind: str, table_key: str) -> list[list[str]]:
    thead = table.find("thead")
    header_rows: list[list[str]] = []
    if thead:
        for tr in thead.find_all("tr"):
            cells = [collapse_header_cell(th.get_text(" ", strip=True)) for th in tr.find_all(["th", "td"])]
            header_rows.append(cells)

    # Prefer 2001 grouped headers for international tables (same columns).
    if kind == "intl":
        y = yy(year)
        if table_key == "summary":
            header_rows = [
                INTL_SUMMARY_GROUP,
                [c.replace("{yy} Earnings", f"{y} Earnings") for c in INTL_SUMMARY_COLS],
            ]
        elif table_key in INTL_REGION_GROUP:
            region = INTL_REGION_GROUP[table_key]
            header_rows = [
                ["", "", "", region, "", "", "", "International", "", ""],
                [c.replace("{yy} Earnings", f"{y} Earnings") for c in INTL_REGION_COLS],
            ]

    body = table.find("tbody") or table
    data_rows: list[list[str]] = []
    for tr in body.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        row = [clean_data_cell(td) for td in tds]
        if not any(row):
            continue
        # skip leftover header-looking rows
        if row[0] in {"#", "Rank"}:
            continue
        data_rows.append(row)

    return header_rows + data_rows


def parse_page(html: str, page: PageSpec, year: int) -> dict[str, list[list[str]]]:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.select("table.sire-list")
    if not tables:
        tables = [t for t in soup.find_all("table") if t.find("th")]
    out: dict[str, list[list[str]]] = {}
    if page.kind == "na":
        if tables:
            out["main"] = parse_table(tables[0], year, "na", "main")
        return out
    used: set[str] = set()
    for table in tables:
        key = classify_intl_table(table)
        if not key or key in used:
            continue
        if key not in page.outputs:
            continue
        out[key] = parse_table(table, year, "intl", key)
        used.add(key)
    return out


def write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\r\n")
        for row in rows:
            writer.writerow(row)
    tmp.replace(path)


def csv_has_data(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
    except Exception:
        return False
    # header-only (1 or 2 rows) counts as empty/unpublished placeholder
    return len(rows) > 2 and any(any(c.strip() for c in row) for row in rows[2:])


class RateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.min_interval
        if delay > 0:
            time.sleep(delay)


class Scraper:
    def __init__(self, concurrency: int, delay: float) -> None:
        self.concurrency = concurrency
        self.limiter = RateLimiter(delay)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            }
        )
        self.lock = threading.Lock()
        self.progress = self._load_progress()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        MISSES_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _load_progress(self) -> dict:
        if PROGRESS_PATH.exists():
            try:
                return json.loads(PROGRESS_PATH.read_text())
            except json.JSONDecodeError:
                return {"pages": {}}
        return {"pages": {}}

    def _save_progress(self) -> None:
        PROGRESS_PATH.write_text(json.dumps(self.progress, indent=2, sort_keys=True))

    def log_miss(self, year: int, title: str, reason: str, url: str) -> None:
        line = f"{year}\t{title}\t{reason}\t{url}\n"
        with self.lock:
            with MISSES_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def fetch(self, url: str, dest: Path, retries: int = 6) -> tuple[str, str]:
        """Return (html, status) where status is ok|blocked|http|empty."""
        if dest.exists():
            html = dest.read_text(encoding="utf-8", errors="replace")
            if html and not is_blocked(html) and "<table" in html.lower():
                return html, "ok-cache"
            if html and is_blocked(html):
                dest.unlink(missing_ok=True)

        last_err = "empty"
        for attempt in range(1, retries + 1):
            self.limiter.wait()
            try:
                resp = self.session.get(url, timeout=45)
            except requests.RequestException as exc:
                last_err = f"error:{exc}"
                time.sleep(min(30, 3 * attempt) + random.uniform(0.2, 0.8))
                continue
            html = resp.text or ""
            if resp.status_code >= 400:
                last_err = f"http:{resp.status_code}"
                time.sleep(min(30, 3 * attempt))
                continue
            if is_blocked(html):
                last_err = "blocked"
                time.sleep(min(45, 5 * attempt) + random.uniform(0.5, 1.5))
                continue
            dest.write_text(html, encoding="utf-8")
            if is_login_wall(html):
                return html, "login"
            if "<table" not in html.lower():
                return html, "no-table"
            return html, "ok"
        return "", last_err

    def process_page(self, year: int, page: PageSpec) -> dict:
        url = page_url(page, year)
        titles = list(page.outputs.values())
        pending = [t for t in titles if not csv_has_data(csv_path(year, t))]
        if not pending:
            return {"year": year, "seo": page.seo_name, "status": "skipped-complete", "files": 0}

        html, status = self.fetch(url, cache_path(year, page.seo_name))
        if status in {"blocked", "http", "empty"} or status.startswith("error") or status.startswith("http"):
            for title in pending:
                write_csv(csv_path(year, title), fallback_headers(title, year))
                self.log_miss(year, title, status, url)
            return {"year": year, "seo": page.seo_name, "status": status, "files": 0}

        if status == "login":
            for title in pending:
                write_csv(csv_path(year, title), fallback_headers(title, year))
                self.log_miss(year, title, "login-wall", url)
            return {"year": year, "seo": page.seo_name, "status": "login-wall", "files": 0}

        parsed = parse_page(html, page, year) if html else {}
        written = 0
        for key, title in page.outputs.items():
            dest = csv_path(year, title)
            if csv_has_data(dest):
                continue
            rows = parsed.get(key)
            if not rows or len(rows) <= 2:
                write_csv(dest, fallback_headers(title, year))
                reason = "unpublished-or-empty"
                if status == "no-table":
                    reason = "no-table"
                # 2026 partial empty is still a miss/note
                if year == 2026:
                    reason = f"{reason}-2026-partial"
                self.log_miss(year, title, reason, url)
                continue
            # If NA live headers exist, keep them (already in rows).
            write_csv(dest, rows)
            written += 1

        key = f"{year}:{page.seo_name}"
        with self.lock:
            self.progress.setdefault("pages", {})[key] = {
                "status": "ok",
                "written": written,
                "url": url,
            }
            self._save_progress()
        return {"year": year, "seo": page.seo_name, "status": "ok", "files": written}

    def warmup(self) -> None:
        self.limiter.wait()
        try:
            self.session.get(
                f"{ARCHIVE_URL}?RegionOptions=region-america&seoName=general&region=&year=2004",
                timeout=45,
            )
        except requests.RequestException:
            pass
        time.sleep(1.0)

    def run(self, years: Iterable[int]) -> None:
        jobs = [(year, page) for year in years for page in PAGES]
        print(f"Jobs: {len(jobs)} pages  years={list(years)}  concurrency={self.concurrency}")
        self.warmup()
        done = 0
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futs = {pool.submit(self.process_page, y, p): (y, p) for y, p in jobs}
            for fut in as_completed(futs):
                y, p = futs[fut]
                done += 1
                try:
                    info = fut.result()
                except Exception as exc:
                    print(f"[{done}/{len(jobs)}] FAIL {y} {p.seo_name}: {exc}")
                    continue
                print(
                    f"[{done}/{len(jobs)}] {info['year']} {info['seo']}: "
                    f"{info['status']} files={info['files']}",
                    flush=True,
                )


def verify_2004_general() -> None:
    path = csv_path(2004, "Leading Sire Rankings")
    if not path.exists():
        print("VERIFY: 2004 Leading Sire Rankings missing")
        return
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    names = " | ".join((r[1].split("\n")[0] if len(r) > 1 else "") for r in rows[1:8])
    print("VERIFY 2004 Leading Sire Rankings top names:", names)
    blob = "\n".join(r[1] if len(r) > 1 else "" for r in rows)
    for must in ("Elusive Quality", "A.P. Indy", "Storm Cat"):
        print(f"  {must}: {'FOUND' if must in blob else 'MISSING'}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", default="2004-2026")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--delay", type=float, default=0.9)
    args = parser.parse_args()
    if "-" in args.years:
        a, b = args.years.split("-", 1)
        years = list(range(int(a), int(b) + 1))
    else:
        years = [int(x) for x in args.years.split(",") if x.strip()]
    scraper = Scraper(concurrency=max(1, min(args.concurrency, 3)), delay=max(0.5, args.delay))
    scraper.run(years)
    if 2004 in years:
        verify_2004_general()
    return 0


if __name__ == "__main__":
    sys.exit(main())
