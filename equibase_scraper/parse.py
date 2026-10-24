"""Parse Equibase horse profile and name-search HTML."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

BASE = "https://www.equibase.com"
_MONTHS = {
    name: i
    for i, name in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}
_GRADE_RE = re.compile(
    r"\(\s*(?:Grade|Gr\.?|G)\s*([1-3]|I{1,3}|IV|V)\s*\)",
    re.IGNORECASE,
)
_FOALED_RE = re.compile(
    r"foaled\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def is_blocked(html: str) -> bool:
    if not html:
        return False
    low = html.lower()
    if "pardon our interruption" in low:
        return True
    if "access denied" in low and "error 15" in low:
        return True
    if "request unsuccessful" in low and ("incapsula" in low or "imperva" in low):
        return True
    return False


def is_profile(html: str) -> bool:
    return "horseProfileInfo" in html or "horse-name-header" in html


def page_is_clear(html: str) -> bool:
    """A loaded Equibase page, not a block page and not an empty frame."""
    if not html or is_blocked(html):
        return False
    if is_profile(html):
        return True
    return "equibase" in html.lower()


def is_search_list(html: str) -> bool:
    low = html.lower()
    if "click on a horse name to see the history" in low:
        return True
    return ">yob<" in low and "refno=" in low


def is_empty_search(html: str) -> bool:
    """Equibase name search that returned the profiles form and no horse."""
    return "could not be found" in (html or "").lower()


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def text_of(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).replace("\xa0", " ").split())


def money_to_int(value: str) -> int | None:
    raw = " ".join((value or "").replace("\xa0", " ").split())
    if not raw or raw in {"-", "—", "–"}:
        return None
    neg = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")"))
    digits = re.sub(r"[^0-9]", "", raw)
    if not digits:
        return None
    val = int(digits)
    return -val if neg else val


def plain_int(value: str) -> int | None:
    raw = " ".join((value or "").replace("\xa0", " ").split()).replace(",", "")
    if not raw or raw in {"-", "—", "–"}:
        return None
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return None


def parse_grade(race_name: str) -> str | None:
    match = _GRADE_RE.search(race_name or "")
    if not match:
        return None
    token = match.group(1)
    return token if token.isdigit() else token.upper()


def parse_race_date(value: str) -> str:
    raw = " ".join((value or "").split())
    match = _DATE_RE.search(raw)
    if not match:
        iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
        return iso.group(0) if iso else raw
    month, day, year = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def absolute_url(href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    return urljoin(BASE + "/", href)


def query_param(href: str | None, key: str) -> str | None:
    if not href:
        return None
    values = parse_qs(urlparse(href).query).get(key)
    return values[0] if values else None


def profile_url_for(refno: str | None, registry: str | None) -> str | None:
    if not refno or not registry:
        return None
    return (
        f"{BASE}/profiles/Results.cfm?type=Horse&refno={refno}&registry={registry}"
    )


def _parse_header(soup: BeautifulSoup) -> tuple[str, str | None]:
    header = soup.select_one("h2.horse-name-header")
    text = text_of(header)
    match = re.match(r"^(.*?)\s*\(([A-Z]{2,3})\)\s*$", text)
    if not match:
        return text, None
    return match.group(1).strip(), match.group(2)


def _parse_bio(soup: BeautifulSoup) -> dict:
    out = {
        "breed": None,
        "color": None,
        "sex": None,
        "foaled": None,
        "foal_year": None,
    }
    for heading in soup.select("h5.horse-profile-top-bar-headings"):
        text = text_of(heading)
        match = _FOALED_RE.search(text)
        if not match:
            continue
        month = _MONTHS.get(match.group(1).capitalize())
        day = int(match.group(2))
        year = match.group(3)
        out["foal_year"] = year
        if month:
            out["foaled"] = f"{int(year):04d}-{month:02d}-{day:02d}"
        prefix = text[: match.start()].strip(" ,")
        parts = [part.strip() for part in prefix.split(",") if part.strip()]
        if parts:
            out["breed"] = parts[0]
        if len(parts) >= 3:
            out["sex"] = parts[-1]
            out["color"] = " ".join(parts[1:-1]).strip()
        elif len(parts) == 2:
            out["color"] = parts[1]
        break
    return out


def _parse_pedigree(soup: BeautifulSoup) -> dict:
    empty = {
        "sire": None,
        "sire_refno": None,
        "dam": None,
        "dam_refno": None,
        "damsire": None,
        "damsire_refno": None,
    }
    for heading in soup.select("h5.horse-profile-top-bar-headings"):
        if " by " not in f" {text_of(heading).lower()} ":
            continue
        links = []
        for anchor in heading.find_all("a"):
            href = anchor.get("href") or ""
            if "refno=" not in href:
                continue
            links.append((text_of(anchor), query_param(href, "refno")))
        if len(links) < 3:
            continue
        empty["sire"], empty["sire_refno"] = links[0]
        empty["dam"], empty["dam_refno"] = links[1]
        empty["damsire"], empty["damsire_refno"] = links[2]
        return empty
    return empty


def _parse_connections(soup: BeautifulSoup) -> dict:
    out = {"jockey": None, "trainer": None, "owner": None, "breeder": None}
    for para in soup.select("p.horse-profile-top-bar-para"):
        raw = para.get_text("\n", strip=True)
        if "Jockey:" not in raw and "Breeder:" not in raw and "Trainer:" not in raw:
            continue
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        index = 0
        while index < len(lines):
            line = lines[index]
            if ":" not in line:
                index += 1
                continue
            label, value = line.split(":", 1)
            key = label.strip().lower()
            value = " ".join(value.split())
            # Equibase puts the linked name on the next line: "Jockey:" / "Victor Espinoza"
            if not value and index + 1 < len(lines) and ":" not in lines[index + 1]:
                value = " ".join(lines[index + 1].split())
                index += 1
            if key in out and value:
                out[key] = value
            index += 1
        if out["jockey"] or out["breeder"]:
            break
    return out


def _parse_best_class(soup: BeautifulSoup) -> str | None:
    for node in soup.find_all(string=re.compile(r"Best Racing Class Achieved")):
        parent = node.find_parent()
        nxt = parent.find_next("p") if parent else None
        value = text_of(nxt)
        if value:
            return value
    return None


def _parse_ids(soup: BeautifulSoup, html: str) -> tuple[str | None, str | None]:
    box = soup.select_one("#addCompare")
    refno = box.get("data-comid") if box else None
    registry = box.get("data-comreg") if box else None
    if not refno:
        match = re.search(r'var\s+refno\s*=\s*"(\d+)"', html)
        refno = match.group(1) if match else None
    if not registry:
        match = re.search(r'var\s+registry\s*=\s*"([^"]+)"', html)
        registry = match.group(1) if match else None
    return refno or None, registry or None


def _parse_year_stats(soup: BeautifulSoup) -> list[dict]:
    table = soup.select_one("table#data-table")
    if table is None:
        return []
    body = table.select_one("tbody#data") or table.find("tbody")
    if body is None:
        return []
    rows = []
    for tr in body.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 7:
            continue
        year = text_of(cells[0])
        if not year:
            continue
        # Year, Starts, Firsts, Seconds, Thirds, Highest ESF, Earnings, Earnings Per Start
        esf_cell = cells[5] if len(cells) >= 8 else None
        earn_cell = cells[6] if len(cells) >= 8 else cells[5]
        per_cell = cells[7] if len(cells) >= 8 else (cells[6] if len(cells) >= 7 else None)
        rows.append(
            {
                "year": year,
                "starts": plain_int(text_of(cells[1])),
                "firsts": plain_int(text_of(cells[2])),
                "seconds": plain_int(text_of(cells[3])),
                "thirds": plain_int(text_of(cells[4])),
                "highest_esf": plain_int(text_of(esf_cell)) if esf_cell else None,
                "earnings": money_to_int(text_of(earn_cell)),
                "earnings_per_start": money_to_int(text_of(per_cell)) if per_cell else None,
            }
        )
    return rows


def _parse_starts(soup: BeautifulSoup) -> list[dict]:
    table = soup.select_one("table.results")
    if table is None:
        return []
    body = table.find("tbody") or table
    starts = []
    for tr in body.find_all("tr"):
        if tr.find("th"):
            continue
        track_td = tr.select_one("td.track")
        date_td = tr.select_one("td.date")
        if track_td is None or date_td is None:
            continue
        track_link = track_td.find("a")
        track_href = track_link.get("href") if track_link else None
        type_td = tr.select_one("td.type")
        type_link = type_td.find("a") if type_td else None
        type_href = type_link.get("href") if type_link else None
        chart = tr.select_one("td.chart a")
        video = tr.select_one("td.video a")
        race_name = text_of(type_td)
        race_number = text_of(tr.select_one("td.race"))
        starts.append(
            {
                "race_date": parse_race_date(text_of(date_td)),
                "track": text_of(track_td),
                "track_code": query_param(track_href, "trk"),
                "country": query_param(track_href, "cy"),
                "race_number": race_number or None,
                "race_name": race_name or None,
                "grade": parse_grade(race_name),
                "breed": text_of(tr.select_one("td.breed")) or None,
                "place": text_of(tr.select_one("td.finish")) or None,
                "esf": plain_int(text_of(tr.select_one("td.speedFigure"))),
                "stakes_id": query_param(type_href, "stkid"),
                "chart_url": absolute_url(chart.get("href") if chart else None),
                "video_url": absolute_url(video.get("href") if video else None),
            }
        )

    def sort_key(row: dict) -> tuple:
        number = row.get("race_number") or ""
        try:
            number_i = int(number)
        except ValueError:
            number_i = 0
        return (row.get("race_date") or "", number_i)

    starts.sort(key=sort_key)
    return starts


def parse_profile(html: str, source_url: str | None = None) -> dict:
    soup = _soup(html)
    display_name, foaled_in = _parse_header(soup)
    bio = _parse_bio(soup)
    pedigree = _parse_pedigree(soup)
    connections = _parse_connections(soup)
    refno, registry = _parse_ids(soup, html)
    if source_url:
        refno = refno or query_param(source_url, "refno")
        registry = registry or query_param(source_url, "registry")
    return {
        "display_name": display_name or None,
        "foaled_in": foaled_in,
        "breed": bio["breed"],
        "color": bio["color"],
        "sex": bio["sex"],
        "foaled": bio["foaled"],
        "foal_year": bio["foal_year"],
        "sire": pedigree["sire"],
        "sire_refno": pedigree["sire_refno"],
        "dam": pedigree["dam"],
        "dam_refno": pedigree["dam_refno"],
        "damsire": pedigree["damsire"],
        "damsire_refno": pedigree["damsire_refno"],
        "jockey": connections["jockey"],
        "trainer": connections["trainer"],
        "owner": connections["owner"],
        "breeder": connections["breeder"],
        "best_class": _parse_best_class(soup),
        "equibase_refno": refno,
        "registry": registry,
        "profile_url": profile_url_for(refno, registry),
        "year_stats": _parse_year_stats(soup),
        "starts": _parse_starts(soup),
    }


def parse_search_candidates(html: str) -> list[dict]:
    soup = _soup(html)
    table = None
    for candidate in soup.find_all("table"):
        heads = [text_of(th).lower() for th in candidate.find_all("th")]
        if "yob" in heads and "horse" in heads:
            table = candidate
            break
    if table is None:
        return []
    body = table.find("tbody") or table
    found = []
    for tr in body.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        anchor = cells[0].find("a")
        href = anchor.get("href") if anchor else ""
        if not href or "type=Horse" not in href or "refno=" not in href:
            continue
        yob = text_of(cells[1])
        if not re.fullmatch(r"\d{4}", yob):
            continue
        sire_a = cells[3].find("a") if len(cells) > 3 else None
        dam_a = cells[4].find("a") if len(cells) > 4 else None
        refno = query_param(href, "refno")
        registry = query_param(href, "registry")
        found.append(
            {
                "name": text_of(anchor),
                "yob": yob,
                "sex": text_of(cells[2]) if len(cells) > 2 else None,
                "sire": text_of(sire_a or (cells[3] if len(cells) > 3 else None)),
                "dam": text_of(dam_a or (cells[4] if len(cells) > 4 else None)),
                "refno": refno,
                "registry": registry,
                "breed": query_param(href, "rbt"),
                "url": profile_url_for(refno, registry) or absolute_url(href),
            }
        )
    return found


def _clean_parent(value: str | None) -> str:
    """Same cleaning as horse names. Empty when the caller did not pass a parent."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    from equibase_scraper.queue import clean_name

    return clean_name(text)


def _parent_matches(row: dict, sire_key: str, dam_key: str) -> bool:
    if sire_key and _clean_parent(row.get("sire")) != sire_key:
        return False
    if dam_key and _clean_parent(row.get("dam")) != dam_key:
        return False
    return True


def resolve_html(
    html: str,
    foal_year: str | None,
    sire: str | None = None,
    dam: str | None = None,
) -> dict:
    """Decide what an Equibase response is for a pedigree foal year.

    Optional sire and dam, cleaned like horse names, narrow search hits after
    the year filter. Callers that pass only the year keep the old behavior.

    kind is one of: blocked, profile, candidate, not_found, year_mismatch,
    ambiguous, unknown.
    """
    year = str(foal_year).strip() if foal_year else ""
    if is_blocked(html):
        return {"kind": "blocked", "detail": "Pardon Our Interruption / Access Denied"}
    if is_empty_search(html) and not is_profile(html):
        return {"kind": "not_found", "candidates": [], "detail": "could not be found"}
    if is_profile(html):
        profile = parse_profile(html)
        page_year = profile.get("foal_year") or ""
        if year and page_year and page_year != year:
            return {
                "kind": "year_mismatch",
                "profile": profile,
                "detail": f"profile foaled {page_year}",
            }
        return {"kind": "profile", "profile": profile, "detail": ""}
    if not is_search_list(html):
        return {"kind": "unknown", "detail": "unrecognized response"}

    candidates = parse_search_candidates(html)
    if not candidates:
        return {"kind": "not_found", "candidates": [], "detail": "no search hits"}
    matches = [row for row in candidates if row["yob"] == year] if year else list(candidates)
    if not matches:
        years = ", ".join(sorted({row["yob"] for row in candidates}))
        return {
            "kind": "year_mismatch",
            "candidates": candidates,
            "detail": f"years={years}",
        }
    sire_key = _clean_parent(sire)
    dam_key = _clean_parent(dam)
    if sire_key or dam_key:
        parent_hits = [row for row in matches if _parent_matches(row, sire_key, dam_key)]
        if not parent_hits:
            return {
                "kind": "not_found",
                "candidates": [],
                "detail": "parent mismatch",
            }
        matches = parent_hits
    if len(matches) > 1:
        detail = ",".join(
            f"{row['refno']}:{row['registry']}" for row in matches if row.get("refno")
        )
        return {
            "kind": "ambiguous",
            "candidates": matches,
            "detail": detail,
        }
    return {"kind": "candidate", "candidate": matches[0], "candidates": matches, "detail": ""}
