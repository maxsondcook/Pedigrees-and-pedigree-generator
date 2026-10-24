"""Parse Pedigree Query 5-generation HTML into Horse/Sire/Dam trees."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

YEAR_RE = re.compile(r"\b((?:17|18|19|20)\d{2})\b")
# Colors as they appear next to names/years. `b` is bay — only match as a color token
# with a trailing period or before a year, never interior initials like "A.P.".
COLOR_TOKEN = r"(?:dkb/br|blk/br|gr/ro|dkb|blk|pal|gr|ro|ch|br|wh|gd|b)"
TRAILING_COLOR_RE = re.compile(rf"\s+{COLOR_TOKEN}\.?\s*$", re.I)
COLOR_BEFORE_YEAR_RE = re.compile(rf"\s+{COLOR_TOKEN}\.?\s+(?=\d{{4}})", re.I)
FAMILY_RE = re.compile(r"\{[^}]*\}")
BRACKET_RE = re.compile(r"\[.*?\]")
COUNTRY_RE = re.compile(r"\(\s*([A-Z]{1,4})\s*\)")
SEX_YEAR_RE = re.compile(r"\b([A-Z]),\s*((?:17|18|19|20)\d{2})\b")
SUBJECT_NAME_RE = re.compile(
    r'class="nounderline"[^>]*>\s*([^<]+?)\s*</a></b>',
    re.I,
)
ROWSPAN_TO_GENS = {8: 4, 16: 5, 32: 6, 64: 7, 128: 8, 256: 9}

UNKNOWN_NAMES = {
    "",
    "UNKNOWN",
    "UNKNOWN SIRE",
    "UNKNOWN DAM",
    "N/A",
    "NA",
    "NONE",
    "UNNAMED",
    "?",
    "—",
    "-",
}


class _CellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cells: list[dict[str, Any]] = []
        self._cur: dict[str, Any] | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "td" and a.get("class") in ("f", "m"):
            try:
                rs = int(a.get("rowspan") or 0)
            except ValueError:
                rs = 0
            self._cur = {
                "class": a.get("class"),
                "rowspan": rs,
                "hrefs": [],
                "text": "",
            }
        elif self._cur is not None and tag == "a":
            href = a.get("href") or ""
            if href:
                self._cur["hrefs"].append(href)

    def handle_endtag(self, tag):
        if self._cur is not None and tag == "td":
            self._cur["text"] = " ".join(self._cur["text"].split())
            self.cells.append(self._cur)
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None:
            self._cur["text"] += data


def is_year_only_cell(cell: dict[str, Any]) -> bool:
    if cell.get("hrefs"):
        return False
    text = cell.get("text") or ""
    if not YEAR_RE.search(text):
        return False
    if re.search(r"[A-Z]{3,}", text):
        return False
    return len(text) < 48


def parse_name_year(text: str, extra_year_text: str = "") -> tuple[str, str | None, str]:
    blob = " ".join((text or "").split())
    extra = " ".join((extra_year_text or "").split())

    blob = FAMILY_RE.sub(" ", blob)
    blob = blob.replace("*", " ")
    extra = FAMILY_RE.sub(" ", extra)
    extra = BRACKET_RE.sub(" ", extra)

    country = ""
    cm = COUNTRY_RE.search(blob)
    if cm:
        country = cm.group(1).upper()
        blob = blob[: cm.start()] + blob[cm.end() :]
        blob = " ".join(blob.split())

    year = None
    for src in (blob, extra):
        ym = YEAR_RE.search(src)
        if ym:
            year = ym.group(1)
            break

    blob = BRACKET_RE.sub(" ", blob)
    blob = COLOR_BEFORE_YEAR_RE.sub(" ", blob)
    if year:
        blob = re.sub(rf"\b{year}\b", " ", blob)
    blob = TRAILING_COLOR_RE.sub(" ", blob)
    blob = re.sub(r"\s+", " ", blob).strip(" .-")

    # Sex letters that survived as a trailing token: "C," "H," etc.
    blob = re.sub(r"\s+[A-Z],?\s*$", "", blob).strip(" .-")
    return blob, year, country


def format_horse(name: str, year: str | None) -> str:
    name = " ".join((name or "").split()).upper()
    if year:
        return f"{name} ({year})"
    return name


def parse_subject(html: str) -> dict[str, Any]:
    m = SUBJECT_NAME_RE.search(html or "")
    if not m:
        return {"name": None, "year": None, "country": "", "blob": ""}
    name = m.group(1).strip()
    window = html[m.end() : m.end() + 900]
    country = ""
    cm = COUNTRY_RE.search(window)
    if cm:
        country = cm.group(1).upper()
    year = None
    sm = SEX_YEAR_RE.search(window)
    if sm:
        year = sm.group(2)
    else:
        ym = YEAR_RE.search(window)
        if ym:
            year = ym.group(1)
    return {"name": name, "year": year, "country": country, "blob": window[:300]}


def collect_ancestor_horses(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    i = 0
    n = len(cells)
    while i < n:
        cell = cells[i]
        if is_year_only_cell(cell):
            i += 1
            continue
        extra = ""
        if i + 1 < n and is_year_only_cell(cells[i + 1]):
            extra = cells[i + 1]["text"]
            i += 1
        name, year, country = parse_name_year(cell.get("text") or "", extra)
        if not name:
            i += 1
            continue
        hrefs = cell.get("hrefs") or []
        out.append(
            {
                "name": name,
                "year": year,
                "country": country,
                "rowspan": cell.get("rowspan") or 0,
                "href": hrefs[0] if hrefs else None,
            }
        )
        i += 1
    return out


def _is_unknown(name: str | None) -> bool:
    if not name:
        return True
    return " ".join(name.split()).upper() in UNKNOWN_NAMES


def _build_from_horses(
    horses: list[dict[str, Any]], idx: int, remaining_depth: int
) -> tuple[dict[str, Any] | None, int]:
    if idx >= len(horses):
        return None, idx
    h = horses[idx]
    idx += 1
    if _is_unknown(h["name"]):
        node: dict[str, Any] | None = None
    else:
        node = {"Horse": format_horse(h["name"], h["year"])}
    if remaining_depth > 0:
        sire, idx = _build_from_horses(horses, idx, remaining_depth - 1)
        dam, idx = _build_from_horses(horses, idx, remaining_depth - 1)
        if node is not None:
            if sire:
                node["Sire"] = sire
            if dam:
                node["Dam"] = dam
    return node, idx


def detect_generations(horses: list[dict[str, Any]]) -> int:
    max_rs = max((h.get("rowspan") or 0 for h in horses), default=0)
    return ROWSPAN_TO_GENS.get(max_rs, 5)


def trim_to_generations(node: dict[str, Any] | None, depth: int, max_depth: int) -> dict[str, Any] | None:
    if not node:
        return None
    if depth >= max_depth:
        return {"Horse": node.get("Horse", "")}
    out: dict[str, Any] = {"Horse": node.get("Horse", "")}
    if "Sire" in node:
        child = trim_to_generations(node["Sire"], depth + 1, max_depth)
        if child:
            out["Sire"] = child
    if "Dam" in node:
        child = trim_to_generations(node["Dam"], depth + 1, max_depth)
        if child:
            out["Dam"] = child
    return out


def looks_like_pedigree_page(html: str) -> bool:
    if not html:
        return False
    low = html.lower()
    if "just a moment" in low and "cloudflare" in low:
        return False
    if "<title>wayback machine</title>" in low:
        return False
    if "rowspan=16" in low or 'rowspan="16"' in low:
        return True
    if "rowspan=8" in low or 'rowspan="8"' in low:
        return True
    if "rowspan=32" in low or 'rowspan="32"' in low:
        return True
    return False


def looks_like_not_found(html: str) -> bool:
    if not html:
        return True
    low = html.lower()
    if "<title>wayback machine</title>" in low and "rowspan=" not in low:
        return True
    for needle in (
        "no matching horses",
        "no horses found",
        "horse not found",
        "no horses were found",
        "could not find",
    ):
        if needle in low:
            return True
    return False


def looks_like_challenge(html: str) -> bool:
    if not html:
        return False
    low = html.lower()
    return "just a moment" in low or "cf-mitigated" in low or "performing security verification" in low


def parse_pedigree_html(html: str, generations: int = 5) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (tree, meta). Raises ValueError on unusable HTML."""
    if looks_like_challenge(html):
        raise ValueError("cloudflare challenge")
    if looks_like_not_found(html) and not looks_like_pedigree_page(html):
        raise ValueError("not found")
    if not looks_like_pedigree_page(html):
        raise ValueError("not a pedigree page")

    subject = parse_subject(html)
    parser = _CellParser()
    parser.feed(html)
    horses = collect_ancestor_horses(parser.cells)
    if not horses:
        raise ValueError("no ancestor cells")

    detected = detect_generations(horses)
    ancestor_depth = max(detected - 1, 1)

    root_name = subject.get("name") or "UNKNOWN"
    tree: dict[str, Any] = {"Horse": format_horse(root_name, subject.get("year"))}
    sire, i = _build_from_horses(horses, 0, ancestor_depth)
    dam, i = _build_from_horses(horses, i, ancestor_depth)
    if sire:
        tree["Sire"] = sire
    if dam:
        tree["Dam"] = dam
    tree = trim_to_generations(tree, 0, generations) or tree

    meta = {
        "name": subject.get("name"),
        "year": subject.get("year"),
        "country": subject.get("country") or "",
        "detected_gens": detected,
        "n_ancestors": len(horses),
        "consumed": i,
        "header_blob": subject.get("blob") or "",
    }
    return tree, meta


def node_at(tree: dict[str, Any] | None, path: str) -> dict[str, Any] | None:
    node = tree
    for part in path.split("."):
        if not part:
            continue
        if not node or part not in node:
            return None
        node = node[part]
    return node


def horse_year(label: str | None) -> str | None:
    if not label:
        return None
    m = re.search(r"\((\d{4})\)\s*$", label)
    return m.group(1) if m else None
