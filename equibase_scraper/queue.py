"""Queue the top-level pedigree_map keys without executing pedigrees_database.py."""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PEDIGREE_PATH = REPO / "pedigrees_database.py"
_YEAR_RE = re.compile(r"\((\d{4})\)")
_clean_horse_name = None


def load_clean_horse_name():
    """Use main.clean_horse_name without importing main.

    Importing main executes load_and_sync_all_data(), which execs the 34MB
    pedigree file and deep-copies every tree.
    """
    global _clean_horse_name
    if _clean_horse_name is not None:
        return _clean_horse_name
    tree = ast.parse((REPO / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "clean_horse_name":
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            namespace = {"re": re}
            exec(compile(module, str(REPO / "main.py"), "exec"), namespace)
            _clean_horse_name = namespace["clean_horse_name"]
            return _clean_horse_name
    raise RuntimeError("main.clean_horse_name was not found")


def clean_name(value: str) -> str:
    return load_clean_horse_name()(fold_quotes(value or ""))


def fold_quotes(value: str) -> str:
    return (
        (value or "")
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u02bc", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )


def foaling_year(value: str) -> str:
    if not value:
        return ""
    match = _YEAR_RE.search(value)
    return match.group(1) if match else ""


def strip_year(value: str) -> str:
    return re.sub(r"\s*\(\d{4}\)\s*$", "", value or "").strip()


def _read_string(line: str, index: int) -> tuple[str, int]:
    quote = line[index]
    index += 1
    chars: list[str] = []
    limit = len(line)
    while index < limit:
        char = line[index]
        if char == "\\":
            if index + 1 < limit:
                chars.append(line[index + 1])
                index += 2
                continue
        if char == quote:
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    return "".join(chars), index


def _root_horse_label(line: str, start: int) -> str | None:
    """Horse label on the root dict, not the first ancestor Horse in the tree."""
    index = start
    limit = len(line)
    depth = 0
    while index < limit:
        char = line[index]
        if char in "'\"":
            word, index = _read_string(line, index)
            if depth == 1 and word == "Horse":
                cursor = index
                while cursor < limit and line[cursor] in " \t":
                    cursor += 1
                if cursor < limit and line[cursor] == ":":
                    cursor += 1
                    while cursor < limit and line[cursor] in " \t":
                        cursor += 1
                    if cursor < limit and line[cursor] in "'\"":
                        value, _end = _read_string(line, cursor)
                        return value
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth <= 0:
                return None
        index += 1
    return None


def subject_from_line(line: str) -> dict | None:
    """One top-level pedigree line -> pedigree_key, name_key, foal_year, display_name."""
    if not line.startswith("    ") or len(line) < 6 or line[4] not in "'\"":
        return None
    key, after = _read_string(line, 4)
    if not key:
        return None
    index = after
    limit = len(line)
    while index < limit and line[index] in " \t":
        index += 1
    if index >= limit or line[index] != ":":
        return None
    index += 1
    while index < limit and line[index] in " \t":
        index += 1
    if index >= limit or line[index] != "{":
        return None
    label = _root_horse_label(line, index) or ""
    year = foaling_year(label) or foaling_year(key)
    shown = fold_quotes(strip_year(label) if label else strip_year(key)).strip()
    return {
        "pedigree_key": key,
        "name_key": clean_name(label or key),
        "foal_year": year,
        "display_name": shown or key,
    }


def iter_subjects(path: Path | None = None):
    pedigree = path or PEDIGREE_PATH
    with pedigree.open(encoding="utf-8") as handle:
        for line in handle:
            if not (line.startswith("    '") or line.startswith('    "')):
                continue
            subject = subject_from_line(line)
            if subject:
                yield subject


def find_subjects(name: str, year: str, path: Path | None = None) -> list[dict]:
    want = clean_name(name)
    year = str(year or "").strip()
    raw = name.strip()
    hits = []
    for subject in iter_subjects(path):
        key_match = (
            subject["pedigree_key"] == raw
            or subject["pedigree_key"] == raw.upper()
            or subject["name_key"] == want
            or clean_name(subject["pedigree_key"]) == want
        )
        if not key_match:
            continue
        if year and subject["foal_year"] and subject["foal_year"] != year:
            continue
        hits.append(subject)
    if year:
        with_year = [row for row in hits if row["foal_year"] == year]
        if with_year:
            return with_year
    return hits
