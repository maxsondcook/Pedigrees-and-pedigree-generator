"""Stream sale-catalog pages into anchored horses.

Fasig-Tipton pages use `. . .` leaders. Keeneland pages use `........`.
Both are eight undotted great-grandparents, then the dotted parents.
A name is queued only with a foaling year, a sire, or a dam.
"""

from __future__ import annotations

import re
from collections import defaultdict

from equibase_scraper.queue import clean_name

_MONTHS = (
    "January|February|March|April|May|June|July|August|"
    "September|October|November|December"
)
_HYPHEN_BREAK = re.compile(r"([A-Za-z])-\n([A-Za-z])")
# Two dots is enough: short names leave only ". ." on the leader.
_DOTTED = re.compile(r"(?:\s*\.\s*){2,}\s*$")
_YEAR_LINE = re.compile(r"^\(?(\d{4})\)?$")
_FOALED_YEAR = re.compile(r"\bfoaled\s+(\d{4})\b", re.I)
_FOALED_IN = re.compile(r"\bfoaled\s+in\b", re.I)
_DATE_YEAR = re.compile(rf"\b(?:{_MONTHS})\s+\d{{1,2}},\s*(\d{{4}})\b", re.I)
_BY_LINE = re.compile(r"\bBy\s+([^(\n]{1,70}?)\s*\((\d{4})\)")
_DAM_SPLIT = re.compile(r"(?m)^(?=\d(?:st|nd|rd|th)\s+dam\b)", re.I)
_DAM_LEVEL = re.compile(r"^(\d)(?:st|nd|rd|th)\s+dam\b", re.I)
_DAM_BY = re.compile(
    r"^\s*(?:\d(?:st|nd|rd|th)\s+dam\s+)?(.+?),\s+by\s+([^.\n]{1,90})\.",
    re.I | re.M,
)
_PRODUCE = re.compile(
    r"(?:^|--)[ \t]*([A-Za-z*][A-Za-z0-9.'’*\-\s]{0,55}?)\s*"
    r"\(\s*([cfghr])\.\s+by\s+([^)\n]{1,90})\)",
    re.I | re.M,
)
_SIBLING = re.compile(
    r"\b((?:half[-\s]+)?)(sister|brother)\s+to\s+",
    re.I,
)
_COUNTRY_SUFFIX = re.compile(
    r"-(?:IRE|GB|ARG|BRZ|CHI|JPN|AUS|FR|GER|SAF|USA|CAN|PER|URU|NZ|ENG|ITY|UAE|KOR|MEX)$",
    re.I,
)
_SEX_WORDS = {"COLT", "FILLY", "GELDING", "HORSE", "MARE", "RIDGLING", "RIG"}
_COLOR_WORDS = {
    "BAY", "DARK", "BROWN", "CHESTNUT", "GRAY", "GREY", "ROAN", "BLACK",
    "WHITE", "DK", "BR", "OR", "LIGHT", "CH", "GR", "BLK", "B",
}
_STOP = {
    "BY", "DAM", "SIRE", "WINNER", "WINNERS", "UNRACED", "PLACED",
    "INCLUDING", "CHAMPION", "CHAMPIONS", "PRODUCER", "ABOVE", "BLACK",
    "TYPE", "SEE", "TOTAL", "FOAL", "FOALS", "WIN", "WINS", "NTR", "ETC",
    "AND", "OR", "THE", "HER", "HIS", "FROM", "WITH", "INTO", "OVER",
    "UNPLACED", "NOT", "FOR", "SALE",
}
_WEEKDAYS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}
_SEX_CODE = {
    "c": "C", "f": "F", "g": "G", "h": "H", "r": "R", "m": "M",
    "colt": "C", "filly": "F", "gelding": "G", "horse": "H",
    "ridgling": "R", "mare": "M",
}


def normalize_text(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\u2011", "-").replace("\u2010", "-")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _HYPHEN_BREAK.sub(r"\1\2", text)


def tidy_name(name: str) -> str:
    text = (name or "").replace("\u2019", "'").replace("\u2018", "'").replace("\u02bc", "'")
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\s+", " ", text).strip(" *.,;:-")
    text = _COUNTRY_SUFFIX.sub("", text).strip()
    return text


def norm_year(value) -> str:
    match = re.search(r"\d{4}", str(value or ""))
    if not match:
        return ""
    year = int(match.group(0))
    if 1700 <= year <= 2027:
        return str(year)
    return ""


def is_unnamed(name: str) -> bool:
    tokens = re.findall(r"[A-Z0-9]+", clean_name(name).replace("/", " "))
    if not tokens or not any(token in _SEX_WORDS for token in tokens):
        return False
    return all(token in _SEX_WORDS or token in _COLOR_WORDS for token in tokens)


def plausible(name: str) -> bool:
    key = clean_name(tidy_name(name))
    if len(key) < 3 or key in _STOP:
        return False
    words = key.split()
    if not words or len(words) > 8:
        return False
    if not any(char.isalpha() for char in key):
        return False
    return True


def sex_from_text(text: str) -> str:
    for word in re.findall(r"[A-Za-z]+", text or ""):
        code = _SEX_CODE.get(word.lower())
        if code:
            return code
    return ""


def line_foal_year(line: str) -> str:
    if _FOALED_IN.search(line):
        return ""
    match = _FOALED_YEAR.search(line)
    if match:
        return norm_year(match.group(1))
    match = _DATE_YEAR.search(line)
    if match:
        return norm_year(match.group(1))
    return ""


def skip_line(line: str) -> bool:
    low = line.lower().strip(" {}.")
    if not low:
        return True
    if low in _WEEKDAYS or low in {"hip no", "ktdf"}:
        return True
    if low.startswith("hip no") or low.startswith("barn") or low.startswith("consigned by"):
        return True
    if low.startswith("property of") or low.startswith("engagements") or low.startswith("foaled in"):
        return True
    if low.startswith("breeders") or "nominated" in low:
        return True
    if re.fullmatch(r"[\d\s\-./]+", line):
        return True
    return False


def dotted_name(line: str) -> str | None:
    match = _DOTTED.search(line)
    if not match:
        return None
    name = tidy_name(line[: match.start()])
    return name or None


def cut_sentence(text: str) -> str:
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "." and depth == 0:
            return text[:index]
    return text


def split_depth0(text: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == sep and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def leading_name(part: str) -> str | None:
    text = part.strip(" .;-")
    text = re.sub(r"^\d+\s+champions?\s+", "", text, flags=re.I)
    text = re.split(r"\s*[\[($]", text, maxsplit=1)[0]
    text = tidy_name(text)
    text = re.sub(r"\s+(?:champion|horse of the year)$", "", text, flags=re.I).strip()
    if not plausible(text) or is_unnamed(text):
        return None
    return text


def progeny_names(clause: str) -> list[str]:
    found: list[str] = []
    for chunk in split_depth0(clause, ","):
        bits = re.split(r"\s+and\s+", chunk)
        buffer = bits[0]
        grouped = []
        for piece in bits[1:]:
            if re.search(r"\[[GL1-3]|champion|\(\$", buffer, re.I):
                grouped.append(buffer)
                buffer = piece
            else:
                buffer = buffer + " and " + piece
        grouped.append(buffer)
        for item in grouped:
            name = leading_name(item)
            if name:
                found.append(name)
    return found


class HorseIndex:
    def __init__(self) -> None:
        self.by_name: dict[str, list[dict]] = defaultdict(list)
        self.bare: dict[str, str] = {}

    def add(
        self,
        name: str,
        source: str,
        year: str = "",
        sire: str = "",
        dam: str = "",
        sex: str = "",
    ) -> None:
        display = tidy_name(name)
        if not display or is_unnamed(display) or not plausible(display):
            return
        key = clean_name(display)
        year = norm_year(year)
        sire_display = tidy_name(sire) if sire else ""
        dam_display = tidy_name(dam) if dam else ""
        if sire_display and (is_unnamed(sire_display) or not plausible(sire_display)):
            sire_display = ""
        if dam_display and (is_unnamed(dam_display) or not plausible(dam_display)):
            dam_display = ""
        sire_key = clean_name(sire_display) if sire_display else ""
        dam_key = clean_name(dam_display) if dam_display else ""
        sex = (sex or "")[:1].upper()
        if not year and not sire_key and not dam_key:
            self.bare.setdefault(key, f"{display}\t{source}")
            return
        clusters = self.by_name[key]
        fits = [
            row for row in clusters
            if not _conflicts(row, year, sire_key, dam_key)
        ]
        if len(fits) == 1:
            _fill(fits[0], display, year, sire_display, sire_key, dam_display, dam_key, sex, source)
            return
        if len(fits) > 1 and _mutually_compatible(fits):
            primary = fits[0]
            for other in fits[1:]:
                _fill(
                    primary,
                    other["display_name"],
                    other["year"],
                    other["sire"],
                    other["sire_key"],
                    other["dam"],
                    other["dam_key"],
                    other["sex"],
                    "",
                )
                primary["sources"].update(other["sources"])
                clusters.remove(other)
            _fill(primary, display, year, sire_display, sire_key, dam_display, dam_key, sex, source)
            return
        clusters.append(
            {
                "name_key": key,
                "display_name": display,
                "year": year,
                "sire": sire_display,
                "sire_key": sire_key,
                "dam": dam_display,
                "dam_key": dam_key,
                "sex": sex,
                "sources": {source} if source else set(),
            }
        )

    def rows(self) -> list[dict]:
        out = []
        for clusters in self.by_name.values():
            out.extend(clusters)
        return out

    def review_rows(self) -> list[tuple[str, str, str]]:
        anchored = set(self.by_name)
        rows = []
        for key, packed in sorted(self.bare.items()):
            if key in anchored:
                continue
            display, source = packed.split("\t", 1)
            rows.append((display, key, source))
        return rows


def _conflicts(row: dict, year: str, sire_key: str, dam_key: str) -> bool:
    if year and row["year"] and year != row["year"]:
        return True
    if sire_key and row["sire_key"] and sire_key != row["sire_key"]:
        return True
    if dam_key and row["dam_key"] and dam_key != row["dam_key"]:
        return True
    return False


def _mutually_compatible(rows: list[dict]) -> bool:
    for index, left in enumerate(rows):
        for right in rows[index + 1 :]:
            if _conflicts(left, right["year"], right["sire_key"], right["dam_key"]):
                return False
    return True


def _prefer(old: str, new: str) -> str:
    if not old:
        return new
    if not new:
        return old
    if old.isupper() and not new.isupper():
        return new
    return old


def _fill(row, display, year, sire, sire_key, dam, dam_key, sex, source) -> None:
    row["display_name"] = _prefer(row["display_name"], display)
    if year and not row["year"]:
        row["year"] = year
    if sire_key and not row["sire_key"]:
        row["sire"] = sire
        row["sire_key"] = sire_key
    if dam_key and not row["dam_key"]:
        row["dam"] = dam
        row["dam_key"] = dam_key
    if sex and not row["sex"]:
        row["sex"] = sex
    if source:
        row["sources"].add(source)


def _chart(lines: list[str]) -> dict | None:
    dot_at = next((i for i, line in enumerate(lines) if dotted_name(line)), None)
    if dot_at is None:
        return None
    names: list[str] = []
    foal_year = ""
    cursor = dot_at - 1
    while cursor >= 0 and len(names) < 8:
        line = lines[cursor].replace("{", " ").replace("}", " ").strip()
        cursor -= 1
        if not line or skip_line(line):
            continue
        found_year = line_foal_year(line)
        if found_year:
            foal_year = foal_year or found_year
            continue
        if _YEAR_LINE.match(line):
            continue
        if dotted_name(line):
            break
        names.append(line)
    if len(names) != 8:
        return None
    names.reverse()
    if any(is_unnamed(name) or not plausible(name) for name in names):
        return None

    dotted: list[str] = []
    paren_year = ""
    subject = ""
    sex = ""
    cursor = dot_at
    while cursor < len(lines):
        raw = lines[cursor].strip()
        line = raw.replace("{", " ").replace("}", " ").strip()
        if re.match(r"^By\s+\S", line) or re.match(r"^\d(?:st|nd|rd|th)\s+dam\b", line, re.I):
            break
        name = dotted_name(line)
        if name:
            dotted.append(name)
            cursor += 1
            continue
        year_match = _YEAR_LINE.match(line)
        if year_match:
            paren_year = norm_year(year_match.group(1))
            cursor += 1
            continue
        found_year = line_foal_year(line)
        if found_year:
            foal_year = found_year
            cursor += 1
            continue
        if not line or skip_line(line):
            cursor += 1
            continue
        if is_unnamed(line):
            sex = sex or sex_from_text(line)
            if len(dotted) >= 6 and not subject:
                subject = line
            cursor += 1
            continue
        if len(dotted) >= 6 and plausible(line) and not subject:
            subject = line
            sex = sex or sex_from_text(line)
            cursor += 1
            continue
        if len(dotted) >= 6:
            break
        cursor += 1
    if len(dotted) < 6:
        return None
    if len(dotted) >= 7:
        subject = dotted[6]
        sex = sex or sex_from_text(subject)
    return {
        "gg": names,
        "gp": dotted[:4],
        "sire": dotted[4],
        "dam": dotted[5],
        "paren_year": paren_year,
        "subject": subject,
        "foal_year": foal_year,
        "sex": sex or sex_from_text(subject),
    }


def _remember(known: dict, name: str, sire: str = "", dam: str = "") -> None:
    display = tidy_name(name)
    if not display or not plausible(display):
        return
    row = known.setdefault(clean_name(display), {"sire": "", "dam": ""})
    if sire and not row["sire"]:
        row["sire"] = tidy_name(sire)
    if dam and not row["dam"]:
        row["dam"] = tidy_name(dam)


def parse_page(text: str, source: str, index: HorseIndex) -> None:
    text = normalize_text(text or "")
    if "1st dam" not in text.lower() and ". ." not in text and "...." not in text:
        return
    lines = [line.strip() for line in text.splitlines()]
    known: dict[str, dict] = {}

    def add(name, year="", sire="", dam="", sex=""):
        index.add(name, source, year=year, sire=sire, dam=dam, sex=sex)
        _remember(known, name, sire=sire, dam=dam)

    chart = _chart(lines)
    if chart:
        gg, gp = chart["gg"], chart["gp"]
        add(gp[0], sire=gg[0], dam=gg[1])
        add(gp[1], sire=gg[2], dam=gg[3])
        add(gp[2], sire=gg[4], dam=gg[5])
        add(gp[3], sire=gg[6], dam=gg[7])
        paren_year = chart["paren_year"]
        sire_year = paren_year
        dam_year = ""
        by_match_early = _BY_LINE.search(text)
        if by_match_early and clean_name(tidy_name(by_match_early.group(1))) == clean_name(chart["sire"]):
            by_year = norm_year(by_match_early.group(2))
            if paren_year and by_year and paren_year != by_year:
                # Keeneland prints the dam's year in the chart; the By line is the sire.
                dam_year = paren_year
                sire_year = by_year
            else:
                sire_year = by_year or paren_year
        add(chart["sire"], year=sire_year, sire=gp[0], dam=gp[1])
        add(chart["dam"], year=dam_year, sire=gp[2], dam=gp[3])
        if chart["subject"] and not is_unnamed(chart["subject"]):
            add(
                chart["subject"],
                year=chart["foal_year"],
                sire=chart["sire"],
                dam=chart["dam"],
                sex=chart["sex"],
            )

    by_match = _BY_LINE.search(text)
    by_name = ""
    if by_match:
        by_name = tidy_name(by_match.group(1))
        by_year = norm_year(by_match.group(2))
        if chart and clean_name(by_name) == clean_name(chart["sire"]):
            add(by_name, year=by_year, sire=chart["gp"][0], dam=chart["gp"][1])
        else:
            add(by_name, year=by_year)
        rest = text[by_match.end() :]
        dam_at = re.search(r"\b1st\s+dam\b", rest, re.I)
        paragraph = rest[: dam_at.start()] if dam_at else rest[:2000]
        including = re.search(r"\bincluding\b", paragraph, re.I)
        if including and by_name:
            for progeny in progeny_names(cut_sentence(paragraph[including.end() :])):
                add(progeny, sire=by_name)

    siblings: list[tuple[str, str, str]] = []
    mares: dict[int, str] = {}
    for section in _DAM_SPLIT.split(text):
        level_match = _DAM_LEVEL.match(section)
        if not level_match:
            continue
        level = int(level_match.group(1))
        intro = _DAM_BY.search(section)
        if not intro:
            continue
        mare = tidy_name(intro.group(1))
        mare_sire = tidy_name(intro.group(2))
        if not plausible(mare):
            continue
        mares[level] = mare
        add(mare, sire=mare_sire)
        if level > 1 and (level - 1) in mares:
            add(mares[level - 1], dam=mare)
        if level == 1 and chart and clean_name(mare) == clean_name(chart["dam"]):
            add(mare, sire=chart["gp"][2], dam=chart["gp"][3])
        for produced in _PRODUCE.finditer(section):
            add(
                tidy_name(produced.group(1)),
                sire=tidy_name(produced.group(3)),
                dam=mare,
                sex=_SEX_CODE.get(produced.group(2).lower(), ""),
            )
        for sib in _SIBLING.finditer(section):
            kind = "half" if (sib.group(1) or "").strip() else "full"
            clause = cut_sentence(section[sib.end() :])
            for part in split_depth0(clause, ","):
                name = leading_name(part)
                if name:
                    siblings.append((kind, name, mare))

    for kind, name, mare in siblings:
        info = known.get(clean_name(mare), {})
        if kind == "full" and info.get("sire") and info.get("dam"):
            add(name, sire=info["sire"], dam=info["dam"])
        elif kind == "half" and info.get("dam"):
            add(name, dam=info["dam"])
        else:
            index.add(name, source)


def parse_pdf(path, index: HorseIndex) -> int:
    import pymupdf

    doc = pymupdf.open(path)
    source = path.name
    try:
        total = doc.page_count
        for number in range(total):
            parse_page(doc[number].get_text(), source, index)
        return total
    finally:
        doc.close()


def pedigree_key_for(row: dict, shared_years: set[tuple[str, str]]) -> str:
    if row["year"]:
        base = f"{row['name_key']} ({row['year']})"
        if (row["name_key"], row["year"]) in shared_years:
            return f"{base} | {row['sire_key']} | {row['dam_key']}"
        return base
    return f"{row['name_key']} | {row['sire_key']} | {row['dam_key']}"


def source_label(sources: set[str]) -> str:
    files = sorted(item for item in sources if item != "graded_stakes")
    bits = []
    if len(files) == 1:
        bits.append(files[0])
    elif files:
        bits.append(f"catalogs:{len(files)}")
    if "graded_stakes" in sources:
        bits.append("graded_stakes")
    return "+".join(bits)
