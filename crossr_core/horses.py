"""Horse search, profiles, and pedigree trees as JSON."""
import csv
import datetime
import glob
import json
import os
import re

import main
import hypomating_engine

_SEARCH_INDEX = None
_FEE_HISTORY = None
_MARES_HISTORY = None
_BMS_RANKS = None
_STALLION_RANK_TABLES = None
_RANK_BY_CLEAN = None
_PARENT_BY_KEY = None
_STALLION_ROSTER = None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_horse_label(raw):
    if not raw:
        return {"name": "UNKNOWN", "year": ""}
    text = str(raw).strip()
    match = re.search(r"(.*?)\s*\((.*?)\)", text)
    if match:
        return {"name": match.group(1).strip(), "year": match.group(2).strip()}
    return {"name": text, "year": ""}


def trim_pedigree(node, depth=0, max_depth=5):
    if not node or not isinstance(node, dict) or depth > max_depth:
        return None
    raw = node.get("Horse", "UNKNOWN")
    parsed = parse_horse_label(raw)
    db_lookup = main.pedigree_tree(raw) if depth < max_depth else {}
    sire = (node.get("Sire") if isinstance(node, dict) else None) or db_lookup.get("Sire")
    dam = (node.get("Dam") if isinstance(node, dict) else None) or db_lookup.get("Dam")
    return {
        "name": parsed["name"],
        "year": parsed["year"],
        "display": raw,
        "key": main.clean_horse_name(raw),
        "sire": trim_pedigree(sire, depth + 1, max_depth) if depth < max_depth else None,
        "dam": trim_pedigree(dam, depth + 1, max_depth) if depth < max_depth else None,
    }


def _format_ratio(ratio_str):
    if not ratio_str or "/" not in str(ratio_str):
        return None
    try:
        parts = str(ratio_str).split("/")
        pct = (int(parts[1]) / int(parts[0])) * 100
        return f"{pct:.1f}% ({parts[1]} foals from {parts[0]} mares)"
    except Exception:
        return str(ratio_str)


def _rank_map():
    global _RANK_BY_CLEAN
    if _RANK_BY_CLEAN is None:
        _RANK_BY_CLEAN = {
            main.clean_horse_name(name): idx
            for idx, name in enumerate(hypomating_engine.RAW_RANKING_ORDER, 1)
        }
    return _RANK_BY_CLEAN


def _stud_rank(name):
    return _rank_map().get(main.clean_horse_name(name))


def _parent_lookup():
    """Sire/dam from placeholder horses.csv — never scans the pedigree DB."""
    global _PARENT_BY_KEY
    if _PARENT_BY_KEY is not None:
        return _PARENT_BY_KEY
    out = {}
    path = os.path.join(ROOT, "placeholderdatabase", "horses.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", errors="ignore") as handle:
            for row in csv.DictReader(handle):
                key = main.clean_horse_name(row.get("name") or row.get("name_key") or "")
                if not key or key in out:
                    continue
                sire = (row.get("sire_name") or "").strip() or None
                dam = (row.get("dam_name") or "").strip() or None
                if sire:
                    sire = re.sub(r"\s*\(\d{4}\)", "", sire).strip() or None
                if dam:
                    dam = re.sub(r"\s*\(\d{4}\)", "", dam).strip() or None
                out[key] = (sire, dam)
    _PARENT_BY_KEY = out
    return out


def _mares_bred_2026_path():
    pattern = os.path.join(ROOT, "live_foal_statistics", "*2026*Breeding Season*.csv")
    hits = sorted(glob.glob(pattern))
    return hits[0] if hits else None


def _load_mares_bred_2026():
    path = _mares_bred_2026_path()
    if not path:
        return []
    rows = []
    with open(path, encoding="utf-8-sig", errors="ignore") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("Stallion") or "").strip()
            if not name:
                continue
            rows.append({
                "name": name,
                "key": main.clean_horse_name(name),
                "mares_bred": _intish(row.get("Mares Bred")),
                "state": (row.get("State") or "").strip() or None,
            })
    return rows


def _profile_by_key(profiles):
    out = {}
    for name, data in (profiles or {}).items():
        key = main.clean_horse_name(name)
        if key and key not in out:
            out[key] = (name, data)
    return out


def build_stallion_roster(profiles=None):
    """Cheap list cache: 2026 mares-bred roster + profile/CSV parents. No pedigree scans."""
    global _STALLION_ROSTER
    if _STALLION_ROSTER is not None:
        return _STALLION_ROSTER
    profiles = profiles if profiles is not None else main.load_master_profiles()
    by_profile = _profile_by_key(profiles)
    parents = _parent_lookup()
    ranks = _rank_map()
    roster = []
    for row in _load_mares_bred_2026():
        key = row["key"]
        display, data = by_profile.get(key, (row["name"], {}))
        status = str((data or {}).get("Status", "")).strip().lower()
        if status == "pensioned":
            continue
        fee = (data or {}).get("Stud Fee", 0)
        fee_n = fee if isinstance(fee, int) else _fee_num(fee)
        fee_n = int(fee_n or 0)
        stud_year = (data or {}).get("Stud Duty Year") or 0
        try:
            stud_year = int(stud_year)
        except (TypeError, ValueError):
            stud_year = 0
        farm_title = str((data or {}).get("Farm", "")).replace("_", " ").title()
        if not farm_title and row.get("state"):
            farm_title = row["state"]
        sire, dam = parents.get(key, (None, None))
        crop_l = crop_label(stud_year)
        rank = ranks.get(key)
        stallion_meta = {
            "rank": rank,
            "crop": crop_l,
            "major_wins": (data or {}).get("Major Wins", ""),
        }
        fee_display = f"${fee_n:,}" if fee_n > 0 else "Private / N/A"
        roster.append({
            "name": display or row["name"],
            "key": key,
            "sire": sire,
            "dam": dam,
            "farm": farm_title,
            "stud_fee": fee_display,
            "stud_fee_num": fee_n,
            "year_foaled": (data or {}).get("Year Born"),
            "entered_stud": stud_year,
            "rank": rank if rank is not None else 9999,
            "crop": crop_l,
            "badge": stallion_badge(stallion_meta),
            "surface": (data or {}).get("Surface", "Both"),
            "mares_bred_2026": row.get("mares_bred"),
            "state": row.get("state"),
            "avatar": (display or row["name"] or "?")[:1].upper(),
        })
    _STALLION_ROSTER = roster
    return roster


def crop_label(entered_stud, current_year=None):
    if not entered_stud:
        return None
    try:
        year = int(entered_stud)
    except (TypeError, ValueError):
        return None
    current_year = current_year or datetime.datetime.now().year
    oldest_age = current_year - (year + 1)
    if oldest_age < 0:
        return "First foals upcoming"
    if oldest_age == 0:
        return "First weanlings"
    if oldest_age == 1:
        return "First yearlings"
    if oldest_age == 2:
        return "First-crop sire"
    if oldest_age == 3:
        return "Second-crop sire"
    return "Established"


def stallion_badge(stallion):
    rank = stallion.get("rank")
    crop = stallion.get("crop") or ""
    wins = str(stallion.get("major_wins") or "").lower()
    if rank and rank <= 3:
        return "Leading Sire"
    if "first-crop" in crop.lower() or "yearling" in crop.lower() or "weanling" in crop.lower():
        return "Top Young Sire"
    if "derby" in wins or "triple crown" in wins or "classic" in wins:
        return "Classic Sire"
    if rank and rank <= 15:
        return f"Sire Rank #{rank}"
    return crop


def _fee_num(raw):
    try:
        return int(str(raw).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return 0


def _progeny_earnings_lookup():
    """Map cleaned horse name -> career earnings from placeholder stallion race records + GSW purses."""
    earn = {}
    try:
        import placeholder_store

        for row in placeholder_store.load_table("stallion_stats"):
            name = main.clean_horse_name(row.get("stallion_name") or "")
            if not name:
                continue
            total = 0
            record = row.get("race_record") or ""
            try:
                parsed = json.loads(record) if isinstance(record, str) and record.strip().startswith("{") else record
            except Exception:
                parsed = {}
            if isinstance(parsed, dict):
                for stats in parsed.values():
                    if not isinstance(stats, dict):
                        continue
                    amount = _intish(stats.get("Earnings"))
                    if amount:
                        total += amount
            if total:
                earn[name] = max(earn.get(name, 0), total)
        for row in placeholder_store.load_table("graded_stakes_winners"):
            name = main.clean_horse_name(row.get("horse_name") or "")
            purse = _intish(row.get("purse"))
            if name and purse:
                earn[name] = earn.get(name, 0) + purse
    except Exception:
        pass
    return earn


def top_progeny_for_sire(sire_name, limit=12):
    payload = hypomating_engine.top_crosses_payload(main.PEDIGREE_DATABASE, sire_name, limit=40)
    earn_lookup = _progeny_earnings_lookup()
    rows = []
    for cross in payload.get("crosses", []):
        for w in cross.get("winners", []):
            name = w["name"]
            earnings = earn_lookup.get(main.clean_horse_name(name)) or 0
            rows.append({
                "name": name,
                "sex": "",
                "broodmare_sire": cross["broodmare_sire"],
                "class": w["status"],
                "dam": w.get("dam"),
                "earnings": earnings or None,
                "earnings_display": f"${earnings:,}" if earnings else None,
            })
    rows.sort(key=lambda row: (row.get("earnings") or 0), reverse=True)
    return rows[:limit]


def parent_names(search_name):
    tree = main.pedigree_tree(search_name)
    if not tree:
        return None, None
    sire = tree.get("Sire") or {}
    dam = tree.get("Dam") or {}
    sire_name = sire.get("Horse") if isinstance(sire, dict) else sire
    dam_name = dam.get("Horse") if isinstance(dam, dict) else dam
    sire_name = re.sub(r"\s*\(\d{4}\)", "", str(sire_name or "")).strip()
    dam_name = re.sub(r"\s*\(\d{4}\)", "", str(dam_name or "")).strip()
    return sire_name or None, dam_name or None


def _horse_id(node):
    if not node:
        return ""
    if not isinstance(node, dict):
        raw = str(node).strip()
    else:
        raw = str(node.get("Horse") or "").strip()
    if not raw or "UNKNOWN" in raw.upper():
        return ""
    clean = main.clean_horse_name(raw)
    year = main.foaling_year(raw)
    return f"{clean}|{year}" if year else clean


def _as_pedigree_node(raw):
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw if _horse_id(raw) else None
    text = str(raw).strip()
    if not text or "UNKNOWN" in text.upper():
        return None
    return {"Horse": text}


def _parents_of(node, cache):
    nid = _horse_id(node)
    if not nid:
        return None, None
    if nid in cache:
        return cache[nid]
    sire = node.get("Sire") if isinstance(node, dict) else None
    dam = node.get("Dam") if isinstance(node, dict) else None
    if not _as_pedigree_node(sire) or not _as_pedigree_node(dam):
        raw = node.get("Horse") if isinstance(node, dict) else ""
        looked = main.pedigree_tree(raw) or {}
        sire = sire or looked.get("Sire")
        dam = dam or looked.get("Dam")
    pair = (_as_pedigree_node(sire), _as_pedigree_node(dam))
    cache[nid] = pair
    return pair


def _hypo_tree(name):
    if not name:
        return None
    try:
        import hypofoals_manager

        db = hypofoals_manager.load_hypo_database()
    except Exception:
        return None
    want = main.clean_horse_name(str(name).replace("×", "x"))
    for key, tree in (db or {}).items():
        if not isinstance(tree, dict):
            continue
        labels = [tree.get("Horse") or "", key, str(key).replace(" x ", " x ")]
        if any(main.clean_horse_name(str(label).replace("×", "x")) == want for label in labels if label):
            return tree
    return None


def resolve_pedigree_tree(name=None, tree=None, sire=None, dam=None, damsire=None):
    """Build a Horse/Sire/Dam node from a name, hypo-foal, or sire×dam pair."""
    if isinstance(tree, dict) and (tree.get("Horse") or tree.get("Sire") or tree.get("Dam") or tree.get("name")):
        if "Horse" not in tree and "name" in tree:
            return _from_trimmed(tree)
        return tree
    if sire or dam:
        sire_tree = main.pedigree_tree(sire) if sire else {}
        dam_tree = main.pedigree_tree(dam) if dam else {}
        if not isinstance(dam_tree, dict) or not dam_tree:
            dam_tree = {"Horse": dam or "UNKNOWN"}
        elif "Horse" not in dam_tree and dam:
            dam_tree = {**dam_tree, "Horse": dam}
        if damsire and isinstance(dam_tree, dict) and not (
            isinstance(dam_tree.get("Sire"), dict) and dam_tree.get("Sire", {}).get("Horse")
        ):
            damsire_tree = main.pedigree_tree(damsire) if damsire else {}
            dam_tree = {
                **dam_tree,
                "Sire": damsire_tree if isinstance(damsire_tree, dict) and damsire_tree else {"Horse": damsire},
            }
        return {
            "Horse": name or f"{sire or 'UNKNOWN'} x {dam or 'UNKNOWN'}",
            "Sire": sire_tree if isinstance(sire_tree, dict) and sire_tree else {"Horse": sire or "UNKNOWN"},
            "Dam": dam_tree,
        }
    if not name:
        return None
    hit = main.pedigree_tree(name)
    if hit:
        return hit
    hypo = _hypo_tree(name)
    if hypo:
        return hypo
    if re.search(r"\s+x\s+", str(name), re.I):
        parts = re.split(r"\s+[x×]\s+", str(name), maxsplit=1, flags=re.I)
        if len(parts) == 2:
            return resolve_pedigree_tree(name=name, sire=parts[0].strip(), dam=parts[1].strip(), damsire=damsire)
    return {"Horse": name}


def _from_trimmed(node):
    if not node or not isinstance(node, dict):
        return None
    raw = node.get("display") or node.get("Horse") or node.get("name")
    if not raw:
        return None
    out = {"Horse": raw}
    if node.get("sire"):
        out["Sire"] = _from_trimmed(node["sire"])
    elif node.get("Sire"):
        out["Sire"] = node["Sire"] if isinstance(node["Sire"], dict) else {"Horse": node["Sire"]}
    if node.get("dam"):
        out["Dam"] = _from_trimmed(node["dam"])
    elif node.get("Dam"):
        out["Dam"] = node["Dam"] if isinstance(node["Dam"], dict) else {"Horse": node["Dam"]}
    return out


def _slot_ids_match(id_a, id_b):
    if not id_a or not id_b:
        return False
    if id_a == id_b:
        return True
    name_a, _, year_a = id_a.partition("|")
    name_b, _, year_b = id_b.partition("|")
    if name_a != name_b:
        return False
    if year_a and year_b:
        return year_a == year_b
    return True


def _ancestor_slots(node, cache, max_depth=5):
    """Path -> horse id for 5 generations of ancestors (62 slots when full)."""
    slots = {}

    def walk(current, path, depth):
        if depth >= max_depth or not current:
            return
        sire, dam = _parents_of(current, cache)
        for letter, parent in (("S", sire), ("D", dam)):
            pid = _horse_id(parent)
            if not pid:
                continue
            slots[path + letter] = pid
            walk(parent, path + letter, depth + 1)

    walk(node, "", 0)
    return slots


def _slot_overlap_percent(tree_a, tree_b, cache):
    slots_a = _ancestor_slots(tree_a, cache)
    slots_b = _ancestor_slots(tree_b, cache)
    both = [path for path in slots_a if path in slots_b]
    if not both:
        return 0
    matches = sum(1 for path in both if _slot_ids_match(slots_a[path], slots_b[path]))
    return int(round(min(100.0, 100.0 * matches / len(both))))


def _full_siblings(sire_a, dam_a, sire_b, dam_b):
    return bool(
        _horse_id(sire_a)
        and _slot_ids_match(_horse_id(sire_a), _horse_id(sire_b))
        and _horse_id(dam_a)
        and _slot_ids_match(_horse_id(dam_a), _horse_id(dam_b))
    )


def pedigree_similarity(a=None, b=None, a_tree=None, b_tree=None, a_sire=None, a_dam=None, b_sire=None, b_dam=None):
    """Percent of matching 5-generation ancestor slots; sibling floors as a safety net."""
    tree_a = resolve_pedigree_tree(name=a, tree=a_tree, sire=a_sire, dam=a_dam)
    tree_b = resolve_pedigree_tree(name=b, tree=b_tree, sire=b_sire, dam=b_dam)
    if not _horse_id(tree_a) or not _horse_id(tree_b):
        return None
    cache = {}
    percent = _slot_overlap_percent(tree_a, tree_b, cache)
    sa, da = _parents_of(tree_a, cache)
    sb, db = _parents_of(tree_b, cache)
    same_sire = bool(_horse_id(sa) and _slot_ids_match(_horse_id(sa), _horse_id(sb)))
    same_dam = bool(_horse_id(da) and _slot_ids_match(_horse_id(da), _horse_id(db)))
    sire_bros = _full_siblings(*_parents_of(sa, cache), *_parents_of(sb, cache)) if sa and sb else False
    dam_sis = _full_siblings(*_parents_of(da, cache), *_parents_of(db, cache)) if da and db else False
    three_quarter = (same_sire and dam_sis) or (same_dam and sire_bros)
    label = None
    if _slot_ids_match(_horse_id(tree_a), _horse_id(tree_b)):
        percent = 100
        label = "Same horse"
    elif same_sire and same_dam:
        percent = max(percent, 100)
        label = "Full siblings"
    elif three_quarter:
        percent = max(percent, 75)
        label = "3/4 siblings"
    elif same_dam:
        percent = max(percent, 50)
        label = "Same dam"
    elif same_sire:
        percent = max(percent, 50)
        label = "Same sire"
    return {
        "percent": percent,
        "label": label,
        "a": a or (tree_a.get("Horse") if isinstance(tree_a, dict) else None),
        "b": b or (tree_b.get("Horse") if isinstance(tree_b, dict) else None),
    }


def similar_cross_rows(sire_name, reference_tree=None, reference_name=None, reference_sire=None, reference_dam=None, limit=20):
    """Proven GSWs by this sire, with pedigree similarity to a reference horse."""
    payload = hypomating_engine.top_crosses_payload(main.PEDIGREE_DATABASE, sire_name, limit=40)
    ref = resolve_pedigree_tree(name=reference_name, tree=reference_tree, sire=reference_sire, dam=reference_dam)
    rows = []
    for cross in payload.get("crosses") or []:
        for winner in cross.get("winners") or []:
            sim = None
            if ref and _horse_id(ref):
                sim = pedigree_similarity(a_tree=ref, b=winner.get("name"))
            rows.append({
                "name": winner.get("name"),
                "broodmare_sire": cross.get("broodmare_sire"),
                "class": winner.get("status"),
                "dam": winner.get("dam"),
                "similarity": (sim or {}).get("percent"),
                "similarity_label": (sim or {}).get("label"),
            })
    tier = {"MG1W": 0, "G1W": 1, "MGSW": 2, "G2W": 3, "G3W": 4, "MSW": 5, "SW": 6}
    rows.sort(key=lambda row: (-(row["similarity"] if row["similarity"] is not None else -1), tier.get(row["class"], 9)))
    return rows[:limit]


def _clean_attr(value):
    text = "" if value is None else str(value).strip()
    if text.lower() in {"", "nan", "none", "null", "n/a", "na", "information unavailable."}:
        return None
    return text


def _year_only(value):
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return match.group(0) if match else ""


def profile_lookup(profiles):
    return {main.clean_horse_name(key): data for key, data in (profiles or {}).items()}


def sire_height(sire_name, lookup):
    data = (lookup or {}).get(main.clean_horse_name(sire_name or ""))
    if not data:
        return None
    return _clean_attr(data.get("Height"))


def _profile_for(name, profiles):
    if not name or not profiles:
        return None
    return profile_lookup(profiles).get(main.clean_horse_name(name))


def _sire_class(sire_name, profile):
    if profile:
        wins = _clean_attr(profile.get("Major Wins"))
        if wins:
            return wins.split(",")[0].strip()[:48]
    rank = _stud_rank(sire_name) if sire_name else None
    return f"#{rank}" if rank else None


def _is_catalog_placeholder(name):
    label = (name or "").strip()
    if not label:
        return True
    if re.match(r"^hip\s*\d+$", label, re.I):
        return True
    if re.match(r"^\d{4}-", label):
        return True
    if re.search(r"\s+x\s+", label, re.I):
        return True
    return False


def catalog_pedigree(name=None, year=None, sire=None, dam=None, damsire=None):
    """Subject tree when the horse is on file, otherwise the sire × dam catalog fallback."""
    label = (name or "").strip()
    # Upcoming yearlings often use 2025-DAM or "Sire x Dam" labels — prefer catalog parents.
    if sire or dam:
        if _is_catalog_placeholder(label):
            return resolve_pedigree_tree(name=label, sire=sire, dam=dam, damsire=damsire)
    year_s = _year_only(year)
    lookup = label
    if year_s and label and not re.search(r"\(\d{4}\)", label) and not _is_catalog_placeholder(label):
        lookup = f"{label} ({year_s})"
    direct = main.pedigree_tree(lookup) if lookup and not _is_catalog_placeholder(label) else None
    if not direct and label and label != lookup and not _is_catalog_placeholder(label):
        direct = main.pedigree_tree(label)
    if isinstance(direct, dict) and direct.get("Sire"):
        return direct
    return resolve_pedigree_tree(name=lookup or label, sire=sire, dam=dam, damsire=damsire)


def _fee_amount(raw):
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def expected_market_value(
    sire_name=None,
    profiles=None,
    sire_profile=None,
    *,
    sex=None,
    sold_as=None,
    dam=None,
    name=None,
    damsire=None,
    covering_sire=None,
    catalog_title=None,
    sale_year=None,
    birth_year=None,
    catalog_default_kind=None,
):
    """Expected Market Value from empirical fee-band sales / ValueProjector fallback."""
    from crossr_core import projections as proj_svc

    profile = sire_profile if sire_profile is not None else _profile_for(sire_name, profiles or {})
    bundled = proj_svc.project_lot_market(
        sire=sire_name or "",
        sex=sex or "",
        sold_as=sold_as or "",
        catalog_title=catalog_title or "",
        sire_profile=profile,
        dam=dam or "",
        name=name or "",
        damsire=damsire or "",
        covering_sire=covering_sire or "",
        sale_year=sale_year,
        birth_year=birth_year,
        catalog_default_kind=catalog_default_kind,
    )
    return bundled["expected_market"]


def sale_workspace(
    name,
    sire=None,
    dam=None,
    year=None,
    sex=None,
    color=None,
    foaled=None,
    sold_as=None,
    covering_sire=None,
    damsire=None,
    profiles=None,
    catalog_title=None,
    sale_year=None,
    birth_year=None,
    catalog_default_kind=None,
):
    """Pedigree, female family, similar crosses for one sale horse. Physical stays blank."""
    from crossr_core import projections as proj_svc

    profiles = profiles or {}
    year_s = _year_only(year)
    tree = catalog_pedigree(name=name, year=year, sire=sire, dam=dam, damsire=damsire)
    family = female_family(tree, name or "") if tree else []
    crosses = similar_cross_rows(
        sire,
        reference_name=name,
        reference_sire=sire,
        reference_dam=dam,
        limit=20,
    ) if sire else []
    sire_profile = _profile_for(sire, profiles)
    market = proj_svc.project_lot_market(
        sire=sire or "",
        sex=sex or "",
        sold_as=sold_as or "",
        catalog_title=catalog_title or "",
        sire_profile=sire_profile,
        dam=dam or "",
        name=name or "",
        damsire=damsire or "",
        covering_sire=covering_sire or "",
        sale_year=sale_year,
        birth_year=birth_year if birth_year is not None else year,
        catalog_default_kind=catalog_default_kind,
    )
    return {
        "year": year_s,
        "pedigree": trim_pedigree(tree) if tree else None,
        "female_family": family,
        "similar_crosses": crosses,
        "sire_class": _sire_class(sire, sire_profile),
        "dam_class": family[0].get("status") if family else None,
        "expected_market": market["expected_market"],
        "market_prediction": market["market_prediction"],
        # Sales Physical panel is intentionally a blank placeholder.
        "physical": None,
    }


def list_farms(profiles=None):
    roster = build_stallion_roster(profiles)
    farms = sorted({row["farm"] for row in roster if row.get("farm")})
    return farms


def list_stallions(
    profiles=None,
    q="",
    sort="rank",
    farm="",
    min_fee=None,
    max_fee=None,
    stud_year_min=None,
    stud_year_max=None,
    crop="",
):
    """2026 mares-bred roster. No pedigree DB scans — parents come from horses.csv."""
    rows = list(build_stallion_roster(profiles))
    qn = main.clean_horse_name(q) if q else ""
    farm_n = farm.replace("_", " ").strip().lower() if farm else ""
    kept = []
    for row in rows:
        if qn and qn not in row["key"] and qn not in main.clean_horse_name(row["name"]):
            continue
        if farm_n and farm_n not in (row.get("farm") or "").lower():
            continue
        fee_n = row.get("stud_fee_num") or 0
        if min_fee is not None and fee_n < int(min_fee):
            continue
        if max_fee is not None and fee_n > int(max_fee):
            continue
        stud_year = row.get("entered_stud") or 0
        if stud_year_min is not None and stud_year < int(stud_year_min):
            continue
        if stud_year_max is not None and stud_year > int(stud_year_max):
            continue
        if crop and crop.lower() not in (row.get("crop") or "").lower():
            continue
        kept.append(row)
    reverse = False
    keyfn = lambda r: (r["rank"], r["name"])
    if sort == "name":
        keyfn = lambda r: r["name"].lower()
    elif sort == "fee_desc":
        keyfn = lambda r: r["stud_fee_num"]
        reverse = True
    elif sort == "fee_asc":
        keyfn = lambda r: r["stud_fee_num"]
    elif sort == "stud_year":
        keyfn = lambda r: r["entered_stud"] or 0
        reverse = True
    elif sort == "mares":
        keyfn = lambda r: r.get("mares_bred_2026") or 0
        reverse = True
    kept.sort(key=keyfn, reverse=reverse)
    if sort == "rank":
        kept.sort(key=lambda r: (r["rank"], -(r.get("mares_bred_2026") or 0), r["name"]))
    return kept


def _index_id(clean, year):
    year = str(year or "").strip()
    return f"{clean} ({year})" if year else clean


def build_search_index(profiles=None):
    global _SEARCH_INDEX
    profiles = profiles if profiles is not None else main.load_master_profiles()
    entries = {}
    for key, tree in main.PEDIGREE_DATABASE.items():
        display = tree.get("Horse", key) if isinstance(tree, dict) else key
        parsed = parse_horse_label(display)
        ck = main.clean_horse_name(key)
        year = parsed["year"] or main.foaling_year(key)
        eid = _index_id(ck, year)
        if eid in entries and entries[eid].get("has_pedigree"):
            continue
        entries[eid] = {
            "key": eid,
            "name": parsed["name"] or ck,
            "year": year,
            "display": display,
            "has_pedigree": True,
            "has_profile": False,
        }
    for key, data in profiles.items():
        ck = main.clean_horse_name(key)
        year = str(data.get("Year Born", "") or "")
        eid = _index_id(ck, year) if year else ck
        if eid in entries:
            entries[eid]["has_profile"] = True
            entries[eid]["farm"] = str(data.get("Farm", "")).replace("_", " ").title()
            if year and not entries[eid]["year"]:
                entries[eid]["year"] = year
        else:
            same_name = [
                k for k, item in entries.items()
                if main.clean_horse_name(item.get("name", "")) == ck
            ]
            if len(same_name) == 1:
                entries[same_name[0]]["has_profile"] = True
                entries[same_name[0]]["farm"] = str(data.get("Farm", "")).replace("_", " ").title()
            else:
                entries[eid] = {
                    "key": eid,
                    "name": key,
                    "year": year,
                    "display": key,
                    "has_pedigree": False,
                    "has_profile": True,
                    "farm": str(data.get("Farm", "")).replace("_", " ").title(),
                }
    _SEARCH_INDEX = list(entries.values())
    return _SEARCH_INDEX


def search_horses(query, limit=15, profiles=None):
    q = main.clean_horse_name(query)
    if not q:
        return []
    q_year = main.foaling_year(query)
    index = _SEARCH_INDEX if _SEARCH_INDEX is not None else build_search_index(profiles)
    scored = []
    for item in index:
        if q_year and item.get("year") and item["year"] != q_year:
            continue
        key = main.clean_horse_name(item["key"])
        name = main.clean_horse_name(item["name"])
        if key == q or name == q:
            scored.append((0, item))
        elif key.startswith(q) or name.startswith(q):
            scored.append((1, item))
        elif q in key or q in name:
            scored.append((2, item))
    scored.sort(key=lambda x: (x[0], x[1]["name"], x[1].get("year") or ""))
    return [item for _, item in scored[:limit]]


def _format_stud_fee(raw):
    text = str(raw or "").strip()
    if not text:
        return None
    if text.lower() == "private":
        return "Private"
    usd = re.match(r"^USD\s*([\d,]+)$", text, re.I)
    if usd:
        return f"${int(usd.group(1).replace(',', '')):,}"
    return text


def _intish(val):
    if val is None or str(val).strip() == "":
        return None
    digits = re.sub(r"[^\d]", "", str(val))
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _csv_earnings(row):
    """Total progeny earnings column (not chief earner) from a ranking CSV row."""
    for key, val in (row or {}).items():
        label = re.sub(r"\s+", " ", str(key or "")).strip().lower()
        if "chief" in label or "earner" in label:
            continue
        if "earnings" in label:
            return _intish(val)
    return None


def load_book_stats():
    """Load historical stud fees and mares-bred rows, keyed by cleaned stallion name."""
    global _FEE_HISTORY, _MARES_HISTORY
    if _FEE_HISTORY is not None and _MARES_HISTORY is not None:
        return _FEE_HISTORY, _MARES_HISTORY

    fees = {}
    fee_path = os.path.join(ROOT, "stud_fee_database.csv")
    if os.path.exists(fee_path):
        with open(fee_path, encoding="utf-8-sig", errors="ignore") as f:
            for row in csv.DictReader(f):
                name = main.clean_horse_name(row.get("Stallion") or "")
                year = _intish(row.get("Year"))
                if not name or not year:
                    continue
                fees.setdefault(name, {})[year] = _format_stud_fee(row.get("Stud Fee"))

    mares = {}
    pattern = os.path.join(ROOT, "live_foal_statistics", "*.csv")
    for path in glob.glob(pattern):
        match = re.search(r"(\d{4}) Breeding Season", os.path.basename(path))
        year = int(match.group(1)) if match else None
        if not year:
            continue
        with open(path, encoding="utf-8-sig", errors="ignore") as f:
            for row in csv.DictReader(f):
                name = main.clean_horse_name(row.get("Stallion") or "")
                if not name:
                    continue
                mares.setdefault(name, {})[year] = {
                    "year": year,
                    "mares_bred": _intish(row.get("Mares Bred")),
                    "live_foals": _intish(row.get("Live Foals")),
                    "live_foal_pct": (row.get("Live Foal %") or "").strip() or None,
                    "state": (row.get("State") or "").strip() or None,
                }

    try:
        import mares_bred_2025_by_stallion as mb_data
        for s in mb_data.mares_bred_database.get("North American Stallions", []):
            name = main.clean_horse_name(s.get("stallion") or "")
            if not name:
                continue
            raw_lf = s.get("live_foal_percentage_for_2025_foals")
            live_foals = None
            live_pct = None
            if raw_lf and "/" in str(raw_lf):
                parts = str(raw_lf).split("/")
                try:
                    reports, foals = int(parts[0]), int(parts[1])
                    live_foals = foals
                    live_pct = f"{(foals / reports) * 100:.0f}%" if reports else None
                except Exception:
                    live_pct = str(raw_lf)
            mares.setdefault(name, {})[2025] = {
                "year": 2025,
                "mares_bred": _intish(s.get("mares_bred_2025")),
                "live_foals": live_foals,
                "live_foal_pct": live_pct,
                "state": s.get("state_prov"),
            }
    except Exception:
        pass

    _FEE_HISTORY = fees
    _MARES_HISTORY = mares
    return fees, mares


def _csv_year(path):
    year_m = re.search(r"(?:19|20)\d{2}", os.path.basename(path)) or re.search(
        r"(?:19|20)\d{2}", os.path.dirname(path)
    )
    return int(year_m.group(0)) if year_m else None


def _load_csv_rank_map(filename_glob):
    """Parse BloodHorse ranking CSVs into {clean_name: {year: rank}} plus sorted years."""
    ranks = {}
    years = set()
    pattern = os.path.join(ROOT, "stallion_rankings_data", "*", filename_glob)
    for path in glob.glob(pattern):
        year = _csv_year(path)
        if not year:
            continue
        years.add(year)
        with open(path, encoding="utf-8-sig", errors="ignore", newline="") as f:
            for row in csv.DictReader(f):
                raw_name = (row.get("Stallion") or "").strip()
                if not raw_name:
                    continue
                first = raw_name.splitlines()[0].strip()
                name = main.clean_horse_name(first)
                rank = _intish(row.get("#") or row.get("Rank"))
                if not name or not rank:
                    continue
                ranks.setdefault(name, {})[year] = rank
    return ranks, sorted(years, reverse=True)


def _assign_ranks(name_to_value):
    items = [(n, v) for n, v in name_to_value.items() if v is not None]
    items.sort(key=lambda kv: kv[1], reverse=True)
    out = {}
    last_val = object()
    last_rank = 0
    for i, (name, val) in enumerate(items, 1):
        if val != last_val:
            last_rank = i
            last_val = val
        out[name] = last_rank
    return out


def _fee_amount(raw):
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            return int(raw) if raw > 0 else None
        except (TypeError, ValueError):
            return None
    text = str(raw or "").strip()
    if not text or text.lower() == "private":
        return None
    if re.search(r"\b(JPY|EUR|GBP|AUD|HKD|IRE|NZD|CAD)\b", text, re.I):
        return None
    if not re.search(r"USD|\$", text, re.I) and re.search(r"[A-Za-z]", text):
        return None
    match = re.search(r"([\d,]+)", text)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _rank_metric_maps(year_values):
    """year_values: {year: {clean_name: number}} -> ({name: {year: rank}}, years desc)."""
    ranks = {}
    years = sorted(year_values, reverse=True)
    for year, by_name in year_values.items():
        for name, rank in _assign_ranks(by_name).items():
            ranks.setdefault(name, {})[year] = rank
    return ranks, years


def load_broodmare_ranks():
    """Year -> rank for each cleaned stallion name from Leading Broodmare Sires CSVs."""
    global _BMS_RANKS
    if _BMS_RANKS is not None:
        return _BMS_RANKS
    ranks, _years = _load_csv_rank_map("*Leading Broodmare Sires.csv")
    _BMS_RANKS = ranks
    return ranks


_RANK_LIST_ORDER = [
    "Leading Sire Rankings",
    "Leading Sires by AEI",
    "Leading First Crop Sires",
    "Leading Second-Crop Sires",
    "Leading Third-Crop Sires",
    "Leading Two-Year-Old Sires",
    "Leading Turf Sires",
    "Leading Broodmare Sires",
    "Leading International Sires",
    "Leading International Sires — North America",
    "Leading International Sires — Europe & Dubai",
    "Leading International Sires — Japan & Hong Kong",
    "Leading International First-Crop Sires",
    "Leading International First-Crop Sires — North America",
    "Leading International First-Crop Sires — Europe & Dubai",
    "Leading International First-Crop Sires — Japan & Hong Kong",
    "Leading International 2nd-Crop Sires",
    "Leading International 2nd-Crop Sires — North America",
    "Leading International 2nd-Crop Sires — Europe & Dubai",
    "Leading International 2nd-Crop Sires — Japan & Hong Kong",
    "Leading International 3rd-Crop Sires",
    "Leading International 3rd-Crop Sires — North America",
    "Leading International 3rd-Crop Sires — Europe & Dubai",
    "Leading International 3rd-Crop Sires — Japan & Hong Kong",
    "Leading International Two-Year-Old Sires",
    "Leading International Two-Year-Old Sires — North America",
    "Leading International Two-Year-Old Sires — Europe & Dubai",
    "Leading International Two-Year-Old Sires — Japan & Hong Kong",
]
_FEE_RANK_MAX_YEAR = 2026


def _norm_rank_key(text):
    t = (text or "").lower().replace("&", "and")
    t = t.replace("hong kong", "hongkong")
    t = t.replace("north america", "northamerica")
    t = t.replace("two-year-old", "twoyearold").replace("two year old", "twoyearold")
    t = t.replace("first-crop", "firstcrop").replace("first crop", "firstcrop")
    t = t.replace("second-crop", "secondcrop").replace("second crop", "secondcrop")
    t = t.replace("2nd-crop", "2ndcrop").replace("2nd crop", "2ndcrop")
    t = t.replace("third-crop", "thirdcrop").replace("third crop", "thirdcrop")
    t = t.replace("3rd-crop", "3rdcrop").replace("3rd crop", "3rdcrop")
    return re.sub(r"[^a-z0-9]", "", t)


_RANK_LABEL_BY_KEY = {_norm_rank_key(label): label for label in _RANK_LIST_ORDER}


def _ranking_file_label(filename):
    name = os.path.basename(filename)
    name = re.sub(r"^\d{4}StallionRankings\s*-\s*", "", name)
    name = re.sub(r"\.csv$", "", name, flags=re.I)
    return name.strip()


def _pretty_rank_label(raw):
    text = raw or ""
    text = re.sub(r"LeadingInternational(?=\S)", "Leading International ", text)
    text = text.replace("TwoYearOldSires", "Two-Year-Old Sires")
    text = text.replace("FirstCropSires", "First-Crop Sires")
    text = text.replace("First-CropSires", "First-Crop Sires")
    text = text.replace("2ndCrop", "2nd-Crop")
    text = text.replace("3rdCrop", "3rd-Crop")
    for src, dst in (
        ("-Japan&HongKong", " — Japan & Hong Kong"),
        ("-Japan&Hong Kong", " — Japan & Hong Kong"),
        ("-Europe&Dubai", " — Europe & Dubai"),
        ("-NorthAmerica", " — North America"),
        ("-North America", " — North America"),
    ):
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip()


def _rank_list_id(label):
    if _norm_rank_key(label) == _norm_rank_key("Leading Sire Rankings"):
        return "leading_sire"
    slug = label.lower().replace("&", " and ").replace("—", " ").replace("–", " ")
    return re.sub(r"[^a-z0-9]+", "_", slug).strip("_")


def _stud_start_year(entered_stud):
    year = _intish(entered_stud)
    return year if year and year > 1900 else None


def _years_for_view(years, entered_stud=None, max_year=None):
    start = _stud_start_year(entered_stud)
    out = []
    for year in years:
        if start and year < start:
            continue
        if max_year is not None and year > max_year:
            continue
        out.append(year)
    return out


def load_stallion_ranking_tables():
    """All BloodHorse ranking CSVs plus mares-bred / stud-fee yearly ranks."""
    global _STALLION_RANK_TABLES
    if _STALLION_RANK_TABLES is not None:
        return _STALLION_RANK_TABLES

    grouped = {}
    data_root = os.path.join(ROOT, "stallion_rankings_data")
    for year_name in os.listdir(data_root):
        year_dir = os.path.join(data_root, year_name)
        if not os.path.isdir(year_dir) or not re.fullmatch(r"(?:19|20)\d{2}", year_name):
            continue
        year = int(year_name)
        for fname in os.listdir(year_dir):
            if not fname.lower().endswith(".csv"):
                continue
            path = os.path.join(year_dir, fname)
            raw_label = _ranking_file_label(fname)
            norm = _norm_rank_key(raw_label)
            if not norm:
                continue
            bucket = grouped.setdefault(
                norm,
                {
                    "label": _RANK_LABEL_BY_KEY.get(norm) or _pretty_rank_label(raw_label),
                    "ranks": {},
                    "extras": {},
                    "years": set(),
                },
            )
            bucket["years"].add(year)
            capture_earnings = norm == _norm_rank_key("Leading Sire Rankings")
            try:
                with open(path, encoding="utf-8-sig", errors="ignore", newline="") as f:
                    for row in csv.DictReader(f):
                        raw_name = (row.get("Stallion") or "").strip()
                        if not raw_name:
                            continue
                        first = raw_name.splitlines()[0].strip()
                        name = main.clean_horse_name(first)
                        rank = _intish(row.get("#") or row.get("Rank"))
                        if not name or not rank:
                            continue
                        bucket["ranks"].setdefault(name, {})[year] = rank
                        if capture_earnings:
                            earnings = _csv_earnings(row)
                            if earnings is not None:
                                bucket["extras"].setdefault(name, {})[year] = {"earnings": earnings}
            except Exception:
                continue

    lists = []
    tables = {}
    seen = set()
    ordered_keys = [_norm_rank_key(label) for label in _RANK_LIST_ORDER] + [
        k for k in grouped if k not in _RANK_LABEL_BY_KEY
    ]
    for norm in ordered_keys:
        bucket = grouped.get(norm)
        if not bucket or norm in seen:
            continue
        seen.add(norm)
        list_id = _rank_list_id(bucket["label"])
        item = {"id": list_id, "label": bucket["label"], "group": "bloodhorse"}
        if list_id == "leading_sire":
            item["metric"] = "earnings"
            item["metric_label"] = "Total Progeny Earnings"
        lists.append(item)
        tables[list_id] = {
            "ranks": bucket["ranks"],
            "years": sorted(bucket["years"], reverse=True),
            "extras": bucket.get("extras") or {},
        }

    fees, mares = load_book_stats()
    mares_by_year = {}
    for name, by_year in mares.items():
        for year, row in by_year.items():
            count = row.get("mares_bred") if isinstance(row, dict) else None
            if not count:
                continue
            mares_by_year.setdefault(year, {})[name] = count
    mares_ranks, mares_years = _rank_metric_maps(mares_by_year)

    fee_by_year = {}
    fee_extras = {}
    fee_path = os.path.join(ROOT, "stud_fee_database.csv")
    if os.path.exists(fee_path):
        with open(fee_path, encoding="utf-8-sig", errors="ignore") as f:
            for row in csv.DictReader(f):
                name = main.clean_horse_name(row.get("Stallion") or "")
                year = _intish(row.get("Year"))
                raw_fee = row.get("Stud Fee")
                amount = _fee_amount(raw_fee)
                if not name or not year or year > _FEE_RANK_MAX_YEAR or amount is None:
                    continue
                fee_by_year.setdefault(year, {})[name] = amount
                fee_extras.setdefault(name, {})[year] = {
                    "stud_fee": _format_stud_fee(raw_fee),
                    "stud_fee_num": amount,
                }
    fee_ranks, fee_years = _rank_metric_maps(fee_by_year)

    lists.append({"id": "mares_bred", "label": "Mares Bred Rankings", "group": "book"})
    lists.append({
        "id": "stud_fee",
        "label": "Stud Fee Rankings",
        "group": "book",
        "metric": "stud_fee",
        "metric_label": "Stud Fee",
    })
    tables["mares_bred"] = {"ranks": mares_ranks, "years": mares_years, "extras": {}}
    tables["stud_fee"] = {"ranks": fee_ranks, "years": fee_years, "extras": fee_extras}

    _STALLION_RANK_TABLES = {"lists": lists, "tables": tables}
    return _STALLION_RANK_TABLES


def stallion_ranking_history(stallion_name, entered_stud=None):
    """Yearly ranks + full BloodHorse metrics (AEI, CI, earnings, runners, …)."""
    key = main.clean_horse_name(stallion_name)
    try:
        from crossr_core.stallion_rankings_rich import rich_rankings_from_db
        rich = rich_rankings_from_db(stallion_name, entered_stud=entered_stud)
    except Exception:
        rich = {"lists": [], "rows": {}, "columns": {}}

    lists = list(rich.get("lists") or [])
    rows = dict(rich.get("rows") or {})
    columns = dict(rich.get("columns") or {})
    have_rich = bool(lists)

    payload = load_stallion_ranking_tables()
    for item in payload["lists"]:
        list_id = item["id"]
        is_book = item.get("group") == "book"
        # Prefer rich DB BloodHorse rows; only fall back to thin CSV when DB empty.
        if not is_book and have_rich:
            continue
        if list_id in rows:
            continue
        table = payload["tables"][list_id]
        by_name = table["ranks"]
        years = table["years"]
        extras = (table.get("extras") or {}).get(key, {})
        stallion_years = by_name.get(key, {})
        max_year = _FEE_RANK_MAX_YEAR if list_id == "stud_fee" else None
        view_years = _years_for_view(years, entered_stud=entered_stud, max_year=max_year)
        ranked = []
        for year in view_years:
            rank = stallion_years.get(year)
            if not rank:
                continue
            row = {"year": year, "rank": rank}
            extra = extras.get(year) or {}
            if extra.get("earnings") is not None:
                row["earnings"] = extra["earnings"]
            if extra.get("stud_fee"):
                row["stud_fee"] = extra["stud_fee"]
            if extra.get("stud_fee_num") is not None:
                row["stud_fee_num"] = extra["stud_fee_num"]
            ranked.append(row)
        if not ranked:
            continue
        lists.append(item)
        rows[list_id] = ranked
        if list_id == "stud_fee":
            columns[list_id] = [
                {"key": "year", "label": "Year", "type": "number"},
                {"key": "rank", "label": "Rank", "type": "number"},
                {"key": "stud_fee", "label": "Stud Fee", "type": "money"},
            ]
        elif list_id == "leading_sire":
            columns[list_id] = [
                {"key": "year", "label": "Year", "type": "number"},
                {"key": "rank", "label": "Rank", "type": "number"},
                {"key": "earnings", "label": "Total Progeny Earnings", "type": "money"},
            ]
        else:
            columns[list_id] = [
                {"key": "year", "label": "Year", "type": "number"},
                {"key": "rank", "label": "Rank", "type": "number"},
            ]

    return {"lists": lists, "rows": rows, "columns": columns}


def _broodmare_ranking_rows(stallion_name):
    """Year/rank/earnings/runners from Leading Broodmare Sires CSVs + placeholder stats."""
    key = main.clean_horse_name(stallion_name)
    by_year = {}
    pattern = os.path.join(ROOT, "stallion_rankings_data", "*", "*Leading Broodmare Sires.csv")
    for path in sorted(glob.glob(pattern)):
        year_match = re.search(r"(?:19|20)\d{2}", os.path.basename(os.path.dirname(path)))
        if not year_match:
            continue
        year = int(year_match.group(0))
        try:
            with open(path, encoding="utf-8-sig", errors="ignore", newline="") as handle:
                for row in csv.DictReader(handle):
                    raw_name = (row.get("Stallion") or "").strip()
                    if not raw_name:
                        continue
                    first = raw_name.splitlines()[0].strip()
                    if main.clean_horse_name(first) != key:
                        continue
                    rank = _intish(row.get("#") or row.get("Rank"))
                    earnings = _csv_earnings(row)
                    runners = _intish(row.get("Rnrs") or row.get("Runners") or row.get("Dams"))
                    count_label = "Runners" if (row.get("Rnrs") or row.get("Runners")) else ("Dams" if row.get("Dams") else "Runners")
                    by_year[year] = {
                        "year": year,
                        "rank": rank,
                        "earnings": earnings,
                        "count": runners,
                        "count_label": count_label,
                    }
        except Exception:
            continue
    try:
        import placeholder_store

        for entry in placeholder_store.load_broodmare_sire_rows():
            if placeholder_store.broodmare_clean_horse_name(entry.get("stallion") or "") != key:
                # also try main cleaner
                if main.clean_horse_name(entry.get("stallion") or "") != key:
                    continue
            year = 2026
            if year not in by_year:
                by_year[year] = {
                    "year": year,
                    "rank": entry.get("rank"),
                    "earnings": entry.get("earnings_2026"),
                    "count": entry.get("rnrs") or entry.get("dams"),
                    "count_label": "Runners" if entry.get("rnrs") not in (None, "") else "Dams",
                }
    except Exception:
        pass
    return [by_year[y] for y in sorted(by_year, reverse=True)]


def broodmare_sire_history(stallion_name):
    """Yearly BMS rank, earnings, and runners/dams count from broodmare rankings data."""
    return _broodmare_ranking_rows(stallion_name)


def stud_book_history(stallion_name, entered_stud=None):
    fees, mares = load_book_stats()
    key = main.clean_horse_name(stallion_name)
    fee_years = fees.get(key, {})
    mare_years = mares.get(key, {})
    years = _years_for_view(
        sorted(set(fee_years) | set(mare_years), reverse=True),
        entered_stud=entered_stud,
        max_year=_FEE_RANK_MAX_YEAR,
    )
    rows = []
    for year in years:
        mb = mare_years.get(year) or {}
        rows.append({
            "year": year,
            "stud_fee": fee_years.get(year),
            "mares_bred": mb.get("mares_bred"),
            "live_foals": mb.get("live_foals"),
            "live_foal_pct": mb.get("live_foal_pct"),
            "state": mb.get("state"),
        })
    return rows


_DAM_INDEX = None
_STAKES_BY_KEY = None
_STATUS_WEIGHT = {"MG1W": 7, "G1W": 6, "MGSW": 5, "G2W": 4, "G3W": 3, "MSW": 2, "SW": 1}


def _sex_letter(sex):
    s = str(sex or "").strip().upper()
    if s.startswith("F") or s.startswith("M"):
        return "f"
    if s.startswith("G"):
        return "g"
    if s.startswith("H") or s.startswith("C") or s.startswith("S"):
        return "c"
    return ""


def _race_labels(records):
    labels = []
    seen = set()
    for rec in records or []:
        name = str(rec.get("Race Name") or "").strip()
        if not name:
            continue
        grade = str(rec.get("Grade") or rec.get("Group") or "").strip().upper()
        year = str(rec.get("Race Year") or "").strip()
        label = name
        if grade:
            label = f"{name} [{grade}]"
        if year:
            label = f"{label} ({year})"
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        labels.append(label)
    return labels


def load_stakes_index():
    """Index of graded/group stakes *winners* (Place==1) from the IFHA CSV."""
    global _STAKES_BY_KEY
    if _STAKES_BY_KEY is not None:
        return _STAKES_BY_KEY
    raw = hypomating_engine.load_stakes_data()
    summaries = hypomating_engine.build_horse_summaries(raw)
    grouped = {}
    for rec in raw:
        key = main.clean_horse_name(rec.get("Horse Name") or "")
        if not key:
            continue
        grouped.setdefault(key, []).append(rec)
    by_key = {}
    for key, recs in grouped.items():
        first = recs[0]
        summary = summaries.get(first.get("Horse Name")) or {}
        by_key[key] = {
            "name": first.get("Horse Name") or key,
            "sex": _sex_letter(first.get("Sex") or summary.get("sex")),
            "status": summary.get("status"),
            "races": _race_labels(recs),
        }
    _STAKES_BY_KEY = by_key
    return _STAKES_BY_KEY


def dam_produce_index():
    global _DAM_INDEX
    if _DAM_INDEX is not None:
        return _DAM_INDEX
    idx = {}
    for key, tree in main.PEDIGREE_DATABASE.items():
        if not isinstance(tree, dict):
            continue
        dam = tree.get("Dam")
        dam_raw = dam.get("Horse") if isinstance(dam, dict) else dam
        dam_key = main.clean_horse_name(dam_raw or "")
        if not dam_key:
            continue
        sire = tree.get("Sire")
        sire_raw = sire.get("Horse") if isinstance(sire, dict) else sire
        parsed = parse_horse_label(tree.get("Horse") or key)
        sire_parsed = parse_horse_label(sire_raw or "")
        idx.setdefault(dam_key, []).append({
            "name": parsed["name"],
            "year": parsed["year"],
            "key": main.clean_horse_name(tree.get("Horse") or key),
            "sire": sire_parsed["name"],
        })
    _DAM_INDEX = idx
    return _DAM_INDEX


def _produce_rows(dam_key, subject_key, include_grandkids=True, limit=20):
    stakes = load_stakes_index()
    children = dam_produce_index().get(dam_key) or []
    uniq = {}
    for child in children:
        uniq.setdefault(child["key"], child)
    rows = []
    for child in uniq.values():
        rec = stakes.get(child["key"]) or {}
        grand = []
        if include_grandkids:
            for gk in (dam_produce_index().get(child["key"]) or [])[:8]:
                gk_rec = stakes.get(gk["key"]) or {}
                if not gk_rec.get("status") and not gk_rec.get("races"):
                    continue
                grand.append({
                    "name": gk["name"],
                    "year": gk["year"],
                    "sire": gk["sire"],
                    "sex": gk_rec.get("sex") or "",
                    "status": gk_rec.get("status"),
                    "races": gk_rec.get("races") or [],
                    "is_subject": gk["key"] == subject_key,
                })
        rows.append({
            "name": child["name"],
            "year": child["year"],
            "sire": child["sire"],
            "sex": rec.get("sex") or "",
            "status": rec.get("status"),
            "races": rec.get("races") or [],
            "is_subject": child["key"] == subject_key,
            "produce": grand,
        })
    rows.sort(key=lambda r: (
        0 if r["is_subject"] else 1,
        -_STATUS_WEIGHT.get(r.get("status") or "", 0),
        r["name"].lower(),
    ))
    return rows[:limit]


def female_family(pedigree_data, subject_name=""):
    ordinals = ["1st dam", "2nd dam", "3rd dam", "4th dam"]
    subject_key = main.clean_horse_name(subject_name)
    stakes = load_stakes_index()
    dams = []
    curr = pedigree_data.get("Dam") if isinstance(pedigree_data, dict) else None
    for i in range(4):
        if not curr or not isinstance(curr, dict):
            break
        parsed = parse_horse_label(curr.get("Horse") or "")
        sire_node = curr.get("Sire")
        sire_raw = sire_node.get("Horse") if isinstance(sire_node, dict) else sire_node
        sire_parsed = parse_horse_label(sire_raw or "")
        dam_key = main.clean_horse_name(curr.get("Horse") or "")
        rec = stakes.get(dam_key) or {}
        dams.append({
            "ordinal": ordinals[i],
            "name": parsed["name"],
            "year": parsed["year"],
            "sire": sire_parsed["name"],
            "status": rec.get("status"),
            "racing": rec.get("races") or [],
            "produce": _produce_rows(dam_key, subject_key, include_grandkids=(i == 0)),
        })
        curr = curr.get("Dam")
    return dams


def get_horse_profile(search_name, profiles=None):
    profiles = profiles if profiles is not None else main.load_master_profiles()
    clean_search = main.clean_horse_name(search_name)
    data = None
    matched_key = None
    for key in profiles.keys():
        if main.clean_horse_name(key) == clean_search:
            data = profiles[key]
            matched_key = key
            break

    hit = main.lookup_pedigree(search_name)
    if hit["ambiguous"]:
        return {
            "ambiguous": True,
            "key": hit["clean_name"],
            "name": hit["clean_name"],
            "years": hit["years"],
            "display": hit["clean_name"],
        }
    pedigree_data = hit["tree"]

    horse_name = matched_key.upper() if matched_key else search_name.strip().upper()
    if pedigree_data and isinstance(pedigree_data, dict) and pedigree_data.get("Horse"):
        horse_name = pedigree_data.get("Horse")

    has_valid_pedigree = False
    if pedigree_data and isinstance(pedigree_data, dict):
        db_lookup = pedigree_data
        if (
            pedigree_data.get("Sire")
            or db_lookup.get("Sire")
            or pedigree_data.get("Dam")
            or db_lookup.get("Dam")
        ):
            has_valid_pedigree = True

    if not data and not has_valid_pedigree:
        return None

    race_rows = []
    race_totals = {"starts": 0, "firsts": 0, "seconds": 0, "thirds": 0, "earnings": 0}
    stallion = None
    if data:
        current_year = datetime.datetime.now().year
        birth_year = data.get("Year Born", current_year)
        raw_fee = data.get("Stud Fee", 0)
        if isinstance(raw_fee, int) and raw_fee > 0:
            stud_fee_display = f"${raw_fee:,}"
        elif str(raw_fee).strip().upper() == "N/A" or raw_fee == 0:
            stud_fee_display = "Private / N/A"
        else:
            stud_fee_display = str(raw_fee)

        race_record = data.get("Race Record", {}) or {}
        if isinstance(race_record, dict):
            for age_key, stats in race_record.items():
                starts = stats.get("Starts", 0) or 0
                firsts = stats.get("1sts", 0) or 0
                seconds = stats.get("2nds", 0) or 0
                thirds = stats.get("3rds", 0) or 0
                earnings = stats.get("Earnings", 0)
                if stats.get("Season"):
                    estimated_season = stats.get("Season")
                else:
                    age_digits = re.findall(r"\d+", age_key)
                    estimated_season = birth_year + int(age_digits[0]) if age_digits else birth_year
                earn_num = 0
                if isinstance(earnings, (int, float)):
                    earn_num = earnings
                else:
                    clean_earn = re.sub(r"[^\d]", "", str(earnings))
                    if clean_earn.isdigit():
                        earn_num = int(clean_earn)
                race_totals["starts"] += starts
                race_totals["firsts"] += firsts
                race_totals["seconds"] += seconds
                race_totals["thirds"] += thirds
                race_totals["earnings"] += earn_num
                race_rows.append({
                    "season": estimated_season,
                    "age": age_key,
                    "starts": starts,
                    "firsts": firsts,
                    "seconds": seconds,
                    "thirds": thirds,
                    "earnings": earn_num,
                    "earnings_display": f"${earn_num:,}" if earn_num else "$0",
                    "accomplishments": stats.get("Major Accomplishments", "n/a"),
                })

        mares_bred_val = None
        lf_2025_val = None
        lf_2024_val = None
        try:
            import mares_bred_2025_by_stallion as mb_data
            for s in mb_data.mares_bred_database.get("North American Stallions", []):
                if main.clean_horse_name(s.get("stallion", "")) == clean_search:
                    mares_bred_val = s.get("mares_bred_2025")
                    lf_2025_val = _format_ratio(s.get("live_foal_percentage_for_2025_foals"))
                    lf_2024_val = _format_ratio(s.get("live_foal_percentage_for_2024_foals"))
                    break
        except Exception:
            pass

        stallion = {
            "farm": str(data.get("Farm", "Unknown")).replace("_", " ").title(),
            "year_foaled": birth_year,
            "entered_stud": data.get("Stud Duty Year", current_year),
            "stud_fee": stud_fee_display,
            "stud_fee_num": raw_fee if isinstance(raw_fee, int) else 0,
            "surface": data.get("Surface", "Both"),
            "status": data.get("Status", "active"),
            "height": data.get("Height", "N/A"),
            "conformation": data.get("Conformation & Physical Profile", "Information unavailable."),
            "major_wins": data.get("Major Wins", "N/A"),
            "career_highlight": data.get("Career Highlight", "N/A"),
            "rank": _stud_rank(matched_key or search_name),
            "broodmare_rank": None,
            "progeny_racing": data.get("Progeny Racing Statistics"),
            "progeny_earnings": data.get("Progeny Earnings Statistics"),
            "legacy_progeny": data.get("Legacy Progeny Stats"),
            "mares_bred_2025": mares_bred_val,
            "live_foal_2025": lf_2025_val,
            "live_foal_2024": lf_2024_val,
        }

    inbreeding = None
    tree = None
    if has_valid_pedigree:
        tree = trim_pedigree(pedigree_data)
        inbreeding = main.compute_inbreeding(pedigree_data)

    parsed = parse_horse_label(horse_name)
    if stallion:
        stallion["crop"] = crop_label(stallion.get("entered_stud"))
        stallion["badge"] = stallion_badge(stallion)
        stallion["sire"] = tree["sire"]["name"] if tree and tree.get("sire") else None
        stallion["dam"] = tree["dam"]["name"] if tree and tree.get("dam") else None
    if has_valid_pedigree or data:
        payload_top = top_progeny_for_sire(clean_search)
    else:
        payload_top = []
    entered_stud = data.get("Stud Duty Year") if data else None
    bms_rows = broodmare_sire_history(matched_key or search_name)
    try:
        ranking_rows = stallion_ranking_history(matched_key or search_name, entered_stud=entered_stud)
    except Exception:
        ranking_rows = {"lists": [], "rows": {}}
    if stallion:
        stallion["broodmare_rank"] = next((row["rank"] for row in bms_rows if row.get("rank")), None)
    result = {
        "key": clean_search,
        "name": parsed["name"],
        "year": parsed["year"] or (str(stallion["year_foaled"]) if stallion else ""),
        "display": horse_name,
        "has_profile": data is not None,
        "has_pedigree": has_valid_pedigree,
        "stallion": stallion,
        "race_record": race_rows,
        "race_totals": race_totals,
        "pedigree": tree,
        "inbreeding": inbreeding,
        "top_progeny": payload_top,
        "stud_book": stud_book_history(matched_key or search_name, entered_stud=entered_stud) if data else [],
        "broodmare_sire": bms_rows,
        "sire_rankings": ranking_rows,
        "female_family": female_family(pedigree_data, parsed["name"]) if pedigree_data else [],
        "ambiguous": False,
        "years": [parsed["year"]] if parsed.get("year") else hit.get("years") or [],
    }
    return result
