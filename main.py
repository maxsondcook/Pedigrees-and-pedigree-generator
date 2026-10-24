import datetime
import importlib
import sys
import os
import re
import pprint
import copy
import stallion_stats 
import hypomating_engine

# NAME CLEANING
def clean_horse_name(name: str) -> str:
    """
    Normalizes horse names accurately for absolute dictionary matches.
    Transforms things like 'A.P. Indy (1989)' -> 'A P INDY' and strips out punctuation/spaces.
    """
    if not name or not isinstance(name, str):
        return ""
    # Strip any trailing parenthetical years or country suffixes
    cleaned = re.sub(r'\(.*?\)', '', name)
    # Strip dots, punctuation, and enforce clean spacing
    cleaned = cleaned.replace(".", "").replace("'", "").replace(",", "")
    cleaned = " ".join(cleaned.split())
    # Standardize completely to upper-case
    return cleaned.strip().upper()


def foaling_year(name: str) -> str:
    """Four-digit year inside parentheses: 'VATICANA (2003)' -> '2003'."""
    if not name or not isinstance(name, str):
        return ""
    m = re.search(r"\((\d{4})\)", name)
    return m.group(1) if m else ""


def years_for_name(name, pedigree_db=None):
    """Distinct foaling years for a cleaned name from keys and Horse labels."""
    return lookup_pedigree(name, pedigree_db)["years"]


def lookup_pedigree(name, pedigree_db=None):
    """Resolve a horse name to a pedigree tree without prompting.

    Returns a dict:
      tree, key, years, ambiguous, query_year, clean_name
    Name-only queries stay unambiguous when only one year exists.
    A year already in the query (e.g. 'VATICANA (2003)') is used as-is.
    """
    if pedigree_db is None:
        pedigree_db = PEDIGREE_DATABASE if "PEDIGREE_DATABASE" in globals() else {}
    clean = clean_horse_name(name)
    query_year = foaling_year(name)
    empty = {
        "tree": None,
        "key": None,
        "years": [],
        "ambiguous": False,
        "query_year": query_year,
        "clean_name": clean,
    }
    if not clean or not isinstance(pedigree_db, dict):
        return empty

    by_year = {}
    yearless = []
    for key, tree in pedigree_db.items():
        if clean_horse_name(key) != clean:
            continue
        tree = tree if isinstance(tree, dict) else {}
        year = foaling_year(key) or foaling_year(tree.get("Horse", ""))
        if year:
            by_year.setdefault(year, (key, tree))
        else:
            yearless.append((key, tree))

    years = sorted(by_year)
    if query_year:
        if query_year in by_year:
            key, tree = by_year[query_year]
            return {
                "tree": tree,
                "key": key,
                "years": years,
                "ambiguous": False,
                "query_year": query_year,
                "clean_name": clean,
            }
        year_key = f"{clean} ({query_year})"
        if year_key in pedigree_db and isinstance(pedigree_db[year_key], dict):
            return {
                "tree": pedigree_db[year_key],
                "key": year_key,
                "years": years,
                "ambiguous": False,
                "query_year": query_year,
                "clean_name": clean,
            }
        return {**empty, "years": years}

    if len(years) >= 2:
        return {
            "tree": None,
            "key": None,
            "years": years,
            "ambiguous": True,
            "query_year": "",
            "clean_name": clean,
        }

    if len(years) == 1:
        key, tree = by_year[years[0]]
        return {
            "tree": tree,
            "key": key,
            "years": years,
            "ambiguous": False,
            "query_year": years[0],
            "clean_name": clean,
        }

    if yearless:
        key, tree = yearless[0]
        return {
            "tree": tree,
            "key": key,
            "years": [],
            "ambiguous": False,
            "query_year": "",
            "clean_name": clean,
        }

    if clean in pedigree_db and isinstance(pedigree_db[clean], dict):
        return {
            "tree": pedigree_db[clean],
            "key": clean,
            "years": [],
            "ambiguous": False,
            "query_year": "",
            "clean_name": clean,
        }
    return empty


def pedigree_tree(name, pedigree_db=None):
    """Silent tree lookup. Empty dict if missing or year-ambiguous."""
    hit = lookup_pedigree(name, pedigree_db)
    if hit["ambiguous"] or not hit["tree"]:
        return {}
    return hit["tree"]


def prompt_foaling_year(display_name, years):
    """Ask which foaling year to use. Returns the year string, or '' if cancelled."""
    years = [str(y) for y in years if str(y).strip()]
    if not years:
        return ""
    if len(years) == 1:
        return years[0]
    label = clean_horse_name(display_name) or str(display_name).strip().upper()
    print(f"\nMultiple horses named {label} are in the pedigree database.")
    print("Which foaling year do you want?")
    for idx, year in enumerate(years, 1):
        print(f"  [{idx}] {label} ({year})")
    while True:
        choice = input("Enter year or option number (or B to cancel): ").strip()
        if not choice or choice.lower() in ("b", "back", "cancel"):
            return ""
        if choice in years:
            return choice
        if choice.isdigit():
            num = int(choice)
            if 1 <= num <= len(years):
                return years[num - 1]
            if choice in years:
                return choice
        print(f"Please enter one of: {', '.join(years)}.")


def resolve_pedigree(name, pedigree_db=None, prompt=True):
    """Look up a pedigree, prompting for year when 2+ foaling years exist."""
    if pedigree_db is None:
        pedigree_db = PEDIGREE_DATABASE if "PEDIGREE_DATABASE" in globals() else {}
    hit = lookup_pedigree(name, pedigree_db)
    if hit["ambiguous"] and prompt:
        year = prompt_foaling_year(hit["clean_name"], hit["years"])
        if not year:
            return {**hit, "tree": None, "key": None, "cancelled": True}
        chosen = lookup_pedigree(f"{hit['clean_name']} ({year})", pedigree_db)
        chosen["cancelled"] = False
        return chosen
    hit = dict(hit)
    hit["cancelled"] = False
    return hit


# UPPERCASE NAMES
def load_and_sync_all_data():
    """
    Safely reads compiled map registries from pedigrees_database.py 
    and returns a clean dictionary optimized with uppercase keys.
    """
    combined_database = {}

    try:
        import pedigrees_database as dpd
        if "pedigrees_database" in sys.modules:
            importlib.reload(sys.modules["pedigrees_database"])
        db_map = getattr(dpd, "pedigree_map", {})
        if isinstance(db_map, dict):
            for k, v in db_map.items():
                if not (isinstance(v, dict) and "Horse" in v):
                    continue
                clean = clean_horse_name(k)
                year = foaling_year(k) or foaling_year(v.get("Horse", ""))
                payload = copy.deepcopy(v)
                if year:
                    combined_database[f"{clean} ({year})"] = payload
                if clean not in combined_database:
                    combined_database[clean] = payload
    except Exception:
        pass

    return combined_database


# Initialize Global Pedigree Map Cache
PEDIGREE_DATABASE = load_and_sync_all_data()

# Inject common alias maps to guarantee flawless query resolutions
aliases = {
    "CANDY RIDE (ARG)": "CANDY RIDE",
    "LIAMS MAP": "LIAM'S MAP",
    "BOLT DORO": "BOLT D'ORO",
    "MACLEANS MUSIC": "MACLEAN'S MUSIC",
    "HONOR A P": "HONOR A. P.",
    "JACKIES WARRIOR": "JACKIE'S WARRIOR"
}
for alias_key, standard_key in aliases.items():
    norm_std = clean_horse_name(standard_key)
    if norm_std in PEDIGREE_DATABASE:
        PEDIGREE_DATABASE[clean_horse_name(alias_key)] = PEDIGREE_DATABASE[norm_std]


# UPDATE PEDIGREE DATABASE
def save_database_to_file():
    """Writes the updated PEDIGREE_DATABASE back to pedigrees_database.py."""
    try:
        try:
            import pedigrees_database as dpd
            db_file_path = dpd.__file__
            if db_file_path.endswith('.pyc'):
                db_file_path = db_file_path[:-1]
        except Exception:
            db_file_path = "pedigrees_database.py"

        with open(db_file_path, "w", encoding="utf-8") as f:
            f.write('"""\nAutomatically compiled pedigree database\n"""\n\n')
            f.write("pedigree_map = {\n")
            
            for i, (key, val) in enumerate(PEDIGREE_DATABASE.items()):
                formatted_tree = pprint.pformat(val, indent=4, width=100)
                indented_lines = []
                for line_idx, line in enumerate(formatted_tree.splitlines()):
                    if line_idx == 0:
                        indented_lines.append(f"    {repr(key)}: {line}")
                    else:
                        indented_lines.append(f"    {line}")
                
                block_content = "\n".join(indented_lines)
                if i < len(PEDIGREE_DATABASE) - 1:
                    f.write(block_content + ",\n\n")
                else:
                    f.write(block_content + "\n")
                    
            f.write("}\n")
        print("\n💾 Database successfully updated and written to disk!")
    except Exception as e:
        print(f"\n⚠️  Warning: Could not auto-save database changes to disk: {e}")


def save_profiles_to_file(master_profiles):
    """Persist stallion cards to placeholderdatabase/stallion_stats.csv."""
    try:
        import placeholder_store

        placeholder_store.save_stallion_profiles(master_profiles or {})
        print("\n💾 Stallion stats written to placeholderdatabase/stallion_stats.csv")
    except Exception as e:
        print(f"\n⚠️  Warning: Could not save stallion stats CSV: {e}")


# ==============================================================================
# 4. INTERACTIVE AUTO-FILLING GENERATOR ENGINE
# ==============================================================================
def get_horse_input(role="the horse", depth=0, prefilled_data=None, parent_lookup_key=None, parent_role=None):
    """
    Recursively loops generations up to 5 deep. Automatically searches existing database entries,
    converting responses into UPPERCASE layout structures.
    """
    if depth > 5:
        return None

    print(f"\n[Generation {depth}]")
    
    name = ""
    if prefilled_data and isinstance(prefilled_data, dict) and "Horse" in prefilled_data:
        name = prefilled_data["Horse"].strip().upper()
    elif isinstance(prefilled_data, str):
        name = prefilled_data.strip().upper()
        prefilled_data = None

    is_overridden = False

    if name:
        hit = resolve_pedigree(name, PEDIGREE_DATABASE, prompt=True)
        if hit.get("cancelled"):
            return None
        if hit["tree"] and (not prefilled_data or (not prefilled_data.get("Sire") and not prefilled_data.get("Dam"))):
            prefilled_data = copy.deepcopy(hit["tree"])
            if "Horse" in prefilled_data:
                name = prefilled_data["Horse"].upper()

    if not name or "UNKNOWN" in name:
        if name and "UNKNOWN" in name:
            print(f"⚠️  Database gap found: {name}")
            user_input = input(f"Please specify who {role} actually is: ").strip().upper()
        else:
            user_input = input(f"Enter the name of {role}: ").strip().upper()
            
        if user_input:
            hit = resolve_pedigree(user_input, PEDIGREE_DATABASE, prompt=True)
            if hit.get("cancelled"):
                return None
            if hit["tree"]:
                print(f"🌟 Match found for '{user_input}' inside data profiles! Autofilling branches...")
                prefilled_data = copy.deepcopy(hit["tree"])
                name = prefilled_data.get("Horse", user_input).upper()
            else:
                name = user_input
                is_overridden = True
        else:
            name = ""
            prefilled_data = None 
    else:
        print(f"🌱 Autofilled from database: {name}")

    if not name:
        return None

    if not prefilled_data:
        hit = resolve_pedigree(name, PEDIGREE_DATABASE, prompt=True)
        if hit.get("cancelled"):
            return None
        if hit["tree"]:
            print(f"🌟 Match found for '{name}'! Merging ancestral data branches...")
            prefilled_data = copy.deepcopy(hit["tree"])

    horse_data = {"Horse": name}
    
    if depth < 5:
        print(f"\n--- Ancestors for {name} ---")
        db_lookup = pedigree_tree(name, PEDIGREE_DATABASE)
        
        prefilled_sire = (prefilled_data.get("Sire") if prefilled_data else None) or db_lookup.get("Sire")
        prefilled_dam = (prefilled_data.get("Dam") if prefilled_data else None) or db_lookup.get("Dam")
        
        sire_data = get_horse_input(
            role=f"the sire of {name}", 
            depth=depth + 1, 
            prefilled_data=prefilled_sire,
            parent_lookup_key=clean_horse_name(name),
            parent_role="Sire"
        )
        if sire_data:
            horse_data["Sire"] = sire_data
            
        dam_data = get_horse_input(
            role=f"the dam of {name}", 
            depth=depth + 1, 
            prefilled_data=prefilled_dam,
            parent_lookup_key=clean_horse_name(name),
            parent_role="Dam"
        )
        if dam_data:
            horse_data["Dam"] = dam_data

    cleaned_key = clean_horse_name(name)
    if is_overridden or cleaned_key not in PEDIGREE_DATABASE:
        PEDIGREE_DATABASE[cleaned_key] = copy.deepcopy(horse_data)

    if parent_lookup_key and parent_lookup_key in PEDIGREE_DATABASE:
        if parent_role in PEDIGREE_DATABASE[parent_lookup_key]:
            PEDIGREE_DATABASE[parent_lookup_key][parent_role] = copy.deepcopy(horse_data)
            
    return horse_data


# ==============================================================================
# 5. INBREEDING ANALYSIS ENGINE
# ==============================================================================
def compute_inbreeding(horse_dict):
    """
    Parses a 5-generation pedigree dictionary to track ancestor locations,
    computes consolidated cross-matching (Sire x Dam) using an uppercase layout format,
    and flags single-side linebreeding (Sire-side or Dam-side duplicates).
    Returns a JSON-serializable report (no printing).
    """
    sire_occurrences = {}
    dam_occurrences = {}
    
    sire_paths = {}
    dam_paths = {}

    def traverse(node, current_depth, side_map, path_str, path_dict):
        if not node or not isinstance(node, dict) or current_depth > 5:
            return
        
        raw_name = node.get("Horse", "").strip()
        if not raw_name or "UNKNOWN" in raw_name.upper():
            return
            
        display_name = re.sub(r'\s*\(.*?\)', '', raw_name).strip().upper()
        
        if display_name not in side_map:
            side_map[display_name] = []
        side_map[display_name].append(current_depth)
        
        path_dict[path_str] = display_name
        
        db_lookup = pedigree_tree(raw_name, PEDIGREE_DATABASE)
        sire_branch = node.get("Sire") or db_lookup.get("Sire")
        dam_branch = node.get("Dam") or db_lookup.get("Dam")
        
        traverse(sire_branch, current_depth + 1, side_map, f"{path_str}.S", path_dict)
        traverse(dam_branch, current_depth + 1, side_map, f"{path_str}.D", path_dict)

    db_root = pedigree_tree(horse_dict.get("Horse", ""), PEDIGREE_DATABASE)
    sire_root = horse_dict.get("Sire") or db_root.get("Sire")
    dam_root = horse_dict.get("Dam") or db_root.get("Dam")

    traverse(sire_root, 1, sire_occurrences, "S", sire_paths)
    traverse(dam_root, 1, dam_occurrences, "D", dam_paths)

    cross_inbred_results = []
    sire_side_linebred = []
    dam_side_linebred = []
    coefficient_total = 0.0

    shared_ancestors = set(sire_occurrences.keys()) & set(dam_occurrences.keys())

    cross_inbred_sire_paths = {path for path, name in sire_paths.items() if name in shared_ancestors}
    cross_inbred_dam_paths = {path for path, name in dam_paths.items() if name in shared_ancestors}

    for ancestor_name, s_gens in sorted(sire_occurrences.items()):
        if ancestor_name in dam_occurrences:
            d_gens = dam_occurrences[ancestor_name]
            
            this_s_paths = [p for p, name in sire_paths.items() if name == ancestor_name]
            this_d_paths = [p for p, name in dam_paths.items() if name == ancestor_name]
            
            prune_sire_side = False
            for path in this_s_paths:
                child_path = ".".join(path.split(".")[:-1])
                if child_path in cross_inbred_sire_paths:
                    prune_sire_side = True
                    break
                    
            prune_dam_side = False
            for path in this_d_paths:
                child_path = ".".join(path.split(".")[:-1])
                if child_path in cross_inbred_dam_paths:
                    prune_dam_side = True
                    break
            
            if prune_sire_side and prune_dam_side:
                continue

            s_str = " x ".join([f"{g}S" for g in sorted(s_gens)])
            d_str = " x ".join([f"{g}D" for g in sorted(d_gens)])
            consolidated_layout = f"{s_str} x {d_str}"
            cross_inbred_results.append(f"{ancestor_name}: {consolidated_layout}")
            
            for s_gen in s_gens:
                for d_gen in d_gens:
                    coefficient_total += (0.5) ** (s_gen + d_gen)

    for ancestor_name, s_gens in sire_occurrences.items():
        if len(s_gens) > 1:
            gens_str = ", ".join([f"{g}S" for g in sorted(s_gens)])
            sire_side_linebred.append(f"{ancestor_name} ({gens_str})")

    for ancestor_name, d_gens in dam_occurrences.items():
        if len(d_gens) > 1:
            gens_str = ", ".join([f"{g}D" for g in sorted(d_gens)])
            dam_side_linebred.append(f"{ancestor_name} ({gens_str})")

    return {
        "cross_inbreeding": cross_inbred_results,
        "sire_side_linebreeding": sire_side_linebred,
        "dam_side_linebreeding": dam_side_linebred,
        "coefficient": coefficient_total,
        "coefficient_pct": round(coefficient_total * 100, 4),
    }


def analyze_inbreeding(horse_dict):
    """CLI printer for compute_inbreeding."""
    report = compute_inbreeding(horse_dict)
    print("-" * 80)
    print("Pedigree Inbreeding & Linebreeding Report:\n")
    
    print("Cross-Inbreeding (Sire x Dam):")
    if report["cross_inbreeding"]:
        for result in report["cross_inbreeding"]:
            print(f" • {result}")
    else:
        print(" None detected within 5 generations.")
        
    print("\nSire-Side Linebreeding (Duplicates on Sire side):")
    if report["sire_side_linebreeding"]:
        for result in report["sire_side_linebreeding"]:
            print(f" • {result}")
    else:
        print(" None detected.")

    print("\nDam-Side Linebreeding (Duplicates on Dam side):")
    if report["dam_side_linebreeding"]:
        for result in report["dam_side_linebreeding"]:
            print(f" • {result}")
    else:
        print(" None detected.")
        
    print(f"\nInbreeding Coefficient (Wright's Equation): {report['coefficient_pct']:.4f}%")
    print("-" * 80)
    return report


# ==============================================================================
# 6. PROFILE INTERFACE RUNTIME VIEWERS & GRID RENDERER
# ==============================================================================
def load_master_profiles():
    """Load stallion display cards from placeholderdatabase/stallion_stats.csv."""
    try:
        import placeholder_store

        return placeholder_store.load_stallion_profiles()
    except Exception:
        return {}


def print_pedigree_grid(horse_dict):
    """
    Renders a complete 5-generation pedigree grid table:
    - Generation 1 (Sire/Dam): 16 rows
    - Generation 2: 8 rows
    - Generation 3: 4 rows
    - Generation 4: 2 rows (Horse Name / (Year))
    - Generation 5: 1 row (Horse Name (Year))
    Total table height = 32 rows
    """

    def parse_node(node):
        if not node or not isinstance(node, dict):
            return {"name": "UNKNOWN", "year": ""}
        raw = node.get("Horse", "UNKNOWN").strip()
        match = re.search(r'(.*?)\s*\((.*?)\)', raw)
        if match:
            name = match.group(1).strip()
            year = match.group(2).strip()
        else:
            name = raw
            year = str(node.get("Year Born", ""))
        return {"name": name, "year": year}

    nodes_map = {}

    def fill_tree(node, idx, depth):
        if depth > 5 or idx > 62:
            return
        parsed = parse_node(node)
        nodes_map[idx] = parsed

        if depth < 5:
            h_name = parsed["name"]
            year_label = f"{h_name} ({parsed['year']})" if parsed.get("year") else h_name
            db_lookup = pedigree_tree(year_label) if 'PEDIGREE_DATABASE' in globals() else {}
            sire = (node.get("Sire") if isinstance(node, dict) else None) or db_lookup.get("Sire")
            dam = (node.get("Dam") if isinstance(node, dict) else None) or db_lookup.get("Dam")

            fill_tree(sire, 2 * idx + 1, depth + 1)
            fill_tree(dam, 2 * idx + 2, depth + 1)

    fill_tree(horse_dict, 0, 0)

    cols_nodes = [
        [1, 2],                          # Gen 1 Parents (Sire, Dam)
        [3, 4, 5, 6],                    # Gen 2 Grandparents
        list(range(7, 15)),              # Gen 3 Great-Grandparents
        list(range(15, 31)),             # Gen 4 Great-Great-Grandparents
        list(range(31, 63))              # Gen 5 Ancestors
    ]

    # Dynamically calculate exact column widths
    col_widths = []
    for c_idx in range(5):
        max_w = 0
        for n_idx in cols_nodes[c_idx]:
            info = nodes_map.get(n_idx, {})
            name = info.get("name", "").strip().upper()
            year = info.get("year", "").strip()
            year_str = f"({year})" if year else ""

            if c_idx == 4:
                # Measure combined single-line length for Gen 5: "NAME (YEAR)"
                full_str = f"{name} {year_str}".strip() if year_str else name
                max_w = max(max_w, len(full_str))
            else:
                # Measure independent line lengths for stacked Gen 1-4: "NAME" vs "(YEAR)"
                max_w = max(max_w, len(name), len(year_str))

        # Add 2 spaces for standard left/right cell margin padding
        col_widths.append(max_w + 2)

    total_lines = 32
    spans = [16, 8, 4, 2, 1] # Row heights per column cell

    grid = [["" for _ in range(5)] for _ in range(total_lines)]

    # Fill cell contents according to exact row spans
    for c_idx in range(5):
        span = spans[c_idx]
        w = col_widths[c_idx]
        node_list = cols_nodes[c_idx]

        for cell_idx, n_idx in enumerate(node_list):
            info = nodes_map.get(n_idx, {})
            name = info.get("name", "").strip().upper()
            year = info.get("year", "").strip()
            year_str = f"({year})" if year else ""

            start_row = cell_idx * span

            # Generation 5 (1 row height): Single line layout "NAME (YEAR)"
            if c_idx == 4:
                full_str = f"{name} {year_str}".strip() if year_str else name
                grid[start_row][c_idx] = full_str.center(w)

            # Generations 1-4: Stacked layout ("NAME" on top, "(YEAR)" underneath)
            else:
                name_row = start_row + (span // 2) - 1
                year_row = start_row + (span // 2)
                for r in range(start_row, start_row + span):
                    if r == name_row:
                        grid[r][c_idx] = name.center(w)
                    elif r == year_row and year_str:
                        grid[r][c_idx] = year_str.center(w)
                    else:
                        grid[r][c_idx] = " " * w

    # Construct formatted table borders & print output
    top_border = "+" + "+".join(["-" * w for w in col_widths]) + "+"

    print(top_border)

    for r in range(total_lines):
        row_str = "|" + "|".join([grid[r][c] for c in range(5)]) + "|"
        print(row_str)

        # Print horizontal division gridlines between separate lineage slots
        if r < total_lines - 1:
            div_parts = []
            has_line = False
            for c in range(5):
                if (r + 1) % spans[c] == 0:
                    div_parts.append("-" * col_widths[c])
                    has_line = True
                else:
                    div_parts.append(" " * col_widths[c])
            if has_line:
                print("+" + "+".join(div_parts) + "+")

    print(top_border)


def display_stallion_profile(search_name, all_profiles):
    """Prints stallion profile stats together with the combined pedigree tree grid."""
    data = None
    matched_key = None
    clean_search = clean_horse_name(search_name)
    
    for key in all_profiles.keys():
        if clean_horse_name(key) == clean_search:
            data = all_profiles[key]
            matched_key = key
            break

    horse_name = matched_key.upper() if matched_key else search_name.strip().upper()
    hit = resolve_pedigree(search_name, PEDIGREE_DATABASE, prompt=True)
    if hit.get("cancelled"):
        return
    pedigree_data = copy.deepcopy(hit["tree"]) if hit["tree"] else None
    if pedigree_data and pedigree_data.get("Horse"):
        horse_name = pedigree_data.get("Horse")
    
    has_valid_pedigree = False
    if pedigree_data and isinstance(pedigree_data, dict):
        db_lookup = pedigree_data
        if (pedigree_data.get("Sire") or db_lookup.get("Sire") or 
            pedigree_data.get("Dam") or db_lookup.get("Dam")):
            has_valid_pedigree = True

    if data:
        status_raw = data.get("Status", "active")
        current_year = datetime.datetime.now().year
        birth_year = data.get("Year Born", current_year)
        year_entered_stud = data.get("Stud Duty Year", current_year)

        raw_fee = data.get("Stud Fee", 0)
        if isinstance(raw_fee, int) and raw_fee > 0:
            stud_fee_display = f"${raw_fee:,}"
        elif str(raw_fee).strip().upper() == "N/A" or raw_fee == 0:
            stud_fee_display = "Private / N/A"
        else:
            stud_fee_display = str(raw_fee)

        print("=" * 80)
        print(f"🐴 STALLION PROFILE: {horse_name}")
        print("=" * 80)
        print(f"📍 Standing Location:{data.get('Farm', 'Unknown').replace('_', ' ').title()}")
        print(f"📅 Year Foaled:      {birth_year}")
        print(f"🧬 Entered Stud:     {year_entered_stud}")      
        print(f"💰 Current Stud Fee: {stud_fee_display}")
        print(f"🌍 Surface Pref:     {data.get('Surface', 'Both')}")
        
        if status_raw.strip().lower() != "active":
            print(f"⚠️ Status:           {status_raw}")
            
        print("-" * 80)
        print("🎨 CONFORMATION & PHYSICAL PROFILE:")
        print(data.get("Conformation & Physical Profile", "Information unavailable."))
        print(f"📏 Height:           {data.get('Height', 'N/A')}")
        
        print("-" * 80)
        print("🏆 MAJOR CAREER WINS:")
        print(data.get("Major Wins", "N/A").strip())
        
        print("-" * 80)
        print("📝 CAREER OVERVIEW:")
        print(data.get("Career Highlight", "N/A").strip())
        print("-" * 80)

        print("-" * 80)
        print("📊 RACE RECORD TABLE:\n")
        print("| Season   | Age      | Starts | 1st  | 2nd  | 3rd  | Earnings     | Major Accomplishments")
        print("|----------|----------|--------|------|------|------|--------------|----------------------------------------")
        
        race_record = data.get("Race Record", {})
        
        tot_starts = 0
        tot_firsts = 0
        tot_seconds = 0
        tot_thirds = 0
        tot_earnings = 0
        
        if isinstance(race_record, dict) and race_record:
            for age_key, stats in race_record.items():
                starts = stats.get('Starts', 0)
                firsts = stats.get('1sts', 0)
                seconds = stats.get('2nds', 0)
                thirds = stats.get('3rds', 0)
                earnings = stats.get('Earnings', 0)
                major_acc = stats.get('Major Accomplishments', 'n/a')
                
                tot_starts += starts
                tot_firsts += firsts
                tot_seconds += seconds
                tot_thirds += thirds
                
                if stats.get("Season"):
                    estimated_season = stats.get("Season")
                else:
                    age_digits = re.findall(r'\d+', age_key)
                    estimated_season = birth_year + int(age_digits[0]) if age_digits else birth_year
                
                if isinstance(earnings, (int, float)):
                    tot_earnings += earnings
                    earn_str = f"${earnings:,}" if earnings > 0 else "$0"
                else:
                    clean_earn = re.sub(r'[^\d]', '', str(earnings))
                    if clean_earn.isdigit():
                        val = int(clean_earn)
                        tot_earnings += val
                        earn_str = f"${val:,}"
                    else:
                        earn_str = str(earnings)
                
                words = major_acc.split()
                lines = []
                current_line = []
                for word in words:
                    if len(" ".join(current_line + [word])) <= 40:
                        current_line.append(word)
                    else:
                        lines.append(" ".join(current_line))
                        current_line = [word]
                if current_line:
                    lines.append(" ".join(current_line))
                if not lines:
                    lines = ["n/a"]

                print(f"| {estimated_season:<8} | {age_key:<8} | {starts:<6} | {firsts:<4} | {seconds:<4} | {thirds:<4} | {earn_str:<12} | {lines[0]:<40}")
                
                for line in lines[1:]:
                    print(f"| {'':<8} | {'':<8} | {'':<6} | {'':<4} | {'':<4} | {'':<4} | {'':<12} | {line:<40}")
            
            tot_earn_str = f"${tot_earnings:,}" if tot_earnings > 0 else "$0"
            print(f"| {'TOTAL':<8} | {'':<8} | {tot_starts:<6} | {tot_firsts:<4} | {tot_seconds:<4} | {tot_thirds:<4} | {tot_earn_str:<12} | {'':<40}")
            
            print("-" * 80)
            print(f"{search_name.upper()} had a record of {tot_starts}: {tot_firsts}-{tot_seconds}-{tot_thirds}")
            print("-" * 80)
        else:
            print("| N/A      | N/A      | 0      | 0    | 0    | 0    | $0           | n/a                                     ")
            print(f"| {'TOTAL':<8} | {'':<8} | {'0':<6} | {'0':<4} | {'0':<4} | {'0':<4} | {'$0':<12} | {'':<40}")
            print("-" * 80)
            print(f"{search_name.upper()} had a record of 0: 0-0-0")
            print("-" * 80)

        has_expanded_version = "Progeny Racing Statistics" in data

        if has_expanded_version:
            print("🧬 PROGENY RACING STATISTICS:")
            racing_stats = data["Progeny Racing Statistics"]
            avg_win_dist = racing_stats.get("Avg Winning Distance", "N/A")
            avg_max_win = racing_stats.get("Avg Max Win Distance", "N/A")
            avg_min_win = racing_stats.get("Avg Min Win Distance", "N/A")
            
            keys_to_skip = ["Avg Winning Distance", "Avg Max Win Distance", "Avg Min Win Distance"]
            for stat_name, value in racing_stats.items():
                if stat_name not in keys_to_skip:
                    print(f" • {stat_name}: {value}")
            
            print(f" • Avg Winning Distance (Avg Min Win Distance, Avg Max Win Distance): {avg_win_dist} ({avg_min_win},{avg_max_win})")
            print("-" * 80)

        if "Progeny Earnings Statistics" in data:
            print("💰 PROGENY EARNINGS STATISTICS:")
            for stat_name, value in data["Progeny Earnings Statistics"].items():
                print(f" • {stat_name}: {value}")
            print("-" * 80)

        if "Legacy Progeny Stats" in data and not has_expanded_version:
            prog_stats = data.get("Legacy Progeny Stats", {})
            total_earnings_prog = str(prog_stats.get("Total Earnings", "")).strip().lower()
            win_dist = str(prog_stats.get("Average Progeny Win Distance", "")).strip().lower()
            gsw_ratio = str(prog_stats.get("GSW / G1W Ratio", "")).strip().lower()

            has_no_stats = (
                "n/a" in total_earnings_prog or total_earnings_prog == "" or
                "n/a" in win_dist or win_dist == "" or
                "n/a" in gsw_ratio or gsw_ratio == ""
            )

            if not has_no_stats:
                print("🧬 BREEDING STATISTICS:")
                print(f" • Cumulative Progeny Earnings (Average Earnings Per Runner):   {prog_stats.get('Total Earnings', 'N/A')}")
                print(f" • Avg Progeny Winning Distance:  {prog_stats.get('Average Progeny Win Distance', 'N/A')} furlongs")
                print(f" • Graded Stakes/G1 Winners Ratio: {prog_stats.get('GSW / G1W Ratio', 'N/A')}")
                print("-" * 80)

        mares_bred_val = None
        lf_2025_val = None
        lf_2024_val = None

        try:
            import mares_bred_2025_by_stallion as mb_data
            for s in mb_data.mares_bred_database.get("North American Stallions", []):
                if clean_horse_name(s.get("stallion", "")) == clean_search:
                    mares_bred_val = s.get("mares_bred_2025")
                    
                    def format_ratio(ratio_str):
                        if not ratio_str or "/" not in str(ratio_str):
                            return None
                        try:
                            parts = str(ratio_str).split("/")
                            pct = (int(parts[1]) / int(parts[0])) * 100
                            return f"{pct:.1f}% ({parts[1]} foals from {parts[0]} mares)"
                        except Exception:
                            return str(ratio_str)

                    lf_2025_raw = s.get("live_foal_percentage_for_2025_foals")
                    lf_2024_raw = s.get("live_foal_percentage_for_2024_foals")
                    
                    lf_2025_val = format_ratio(lf_2025_raw) if lf_2025_raw else None
                    lf_2024_val = format_ratio(lf_2024_raw) if lf_2024_raw else None
                    break
        except Exception:
            pass

        has_printed_mb_stats = False
        if mares_bred_val is not None and str(mares_bred_val).strip().upper() != "N/A" and mares_bred_val != "":
            print(f"Mares Bred In 2025: {mares_bred_val}")
            has_printed_mb_stats = True

        try:
            from crossr_core.horses import load_book_stats
            _, mares_hist = load_book_stats()
            mares_2026 = (mares_hist.get(clean_search) or {}).get(2026) or {}
            mares_bred_2026 = mares_2026.get("mares_bred")
        except Exception:
            mares_bred_2026 = None
        if mares_bred_2026 is not None:
            print(f"Mares Bred In 2026: {mares_bred_2026}")
            has_printed_mb_stats = True
            
        if lf_2025_val is not None and str(lf_2025_val).strip().upper() != "N/A" and lf_2025_val != "":
            print(f"Live Foal Percentage 2025: {lf_2025_val}")
            has_printed_mb_stats = True
            
        if lf_2024_val is not None and str(lf_2024_val).strip().upper() != "N/A" and lf_2024_val != "":
            print(f"Live Foal Percentage 2024: {lf_2024_val}")
            has_printed_mb_stats = True

        if has_printed_mb_stats:
            print("-" * 80)

        try:
            from crossr_core.horses import broodmare_sire_history
            bms_rows = broodmare_sire_history(matched_key or search_name)
        except Exception:
            bms_rows = []
        if bms_rows:
            print("BROODMARE SIRE:")
            print(f"{'Year':<8} {'Rank':<8} {'Avg Yearling':<16} {'Sold':<8}")
            for row in bms_rows:
                rank = f"#{row['rank']}" if row.get("rank") else "—"
                avg = f"${row['avg_yearling']:,}" if row.get("avg_yearling") else "—"
                sold = row.get("n_yearlings") if row.get("n_yearlings") else "—"
                print(f"{row['year']:<8} {rank:<8} {avg:<16} {sold}")
            print("-" * 80)

        try:
            from crossr_core.horses import stallion_ranking_history
            ranking_payload = stallion_ranking_history(
                matched_key or search_name,
                entered_stud=year_entered_stud if data else None,
            )
        except Exception:
            ranking_payload = {}
        ranking_rows = ranking_payload.get("rows") or ranking_payload
        leading = ranking_rows.get("leading_sire") or []
        if leading:
            print("STALLION RANKINGS (Leading Sire / Mares Bred / Stud Fee):")
            print(f"{'Year':<8} {'Leading Sire':<14} {'Mares Bred':<12} {'Stud Fee':<10}")
            mares_map = {r["year"]: r.get("rank") for r in ranking_rows.get("mares_bred") or []}
            fee_map = {r["year"]: r.get("rank") for r in ranking_rows.get("stud_fee") or []}
            years = sorted(
                set(r["year"] for r in leading)
                | set(mares_map)
                | set(fee_map),
                reverse=True,
            )
            def _rk(val):
                return f"#{val}" if val else "N/A"
            leading_map = {r["year"]: r.get("rank") for r in leading}
            for year in years:
                print(
                    f"{year:<8} {_rk(leading_map.get(year)):<14} "
                    f"{_rk(mares_map.get(year)):<12} {_rk(fee_map.get(year)):<10}"
                )
            extra = [item["label"] for item in (ranking_payload.get("lists") or []) if item.get("group") == "bloodhorse"]
            if extra:
                print(f"  Other lists available: {len(extra)}")
            print("-" * 80)

        if has_valid_pedigree:
            print(f"5 Generation Pedigree for {horse_name.title()}")
            print_pedigree_grid(pedigree_data if pedigree_data else {"Horse": horse_name})
            analyze_inbreeding(pedigree_data if pedigree_data else {"Horse": horse_name})
        else:
            print("=" * 80)
            print(f"There is no pedigree loaded for {horse_name}")
            
        print("=" * 80)
    else:
        print("=" * 80)
        print(f"Pedigree Tree for: {search_name.upper()}")
        print("=" * 80)
        if has_valid_pedigree:
            print_pedigree_grid(pedigree_data)
            analyze_inbreeding(pedigree_data)
        else:
            print(f"There is no pedigree loaded for {horse_name}")
            
        print("=" * 80)


# ==============================================================================
# 7. CENTRAL CONTROL PANEL NAVIGATION MENU
# ==============================================================================
if __name__ == "__main__":
    while True:
        all_profiles = load_master_profiles()
        print("\n=========================================")
        print("            MAIN APPLICATION             ")
        print("=========================================")
        print(" [1] Search by Horse Profile / Pedigree")
        print(" [2] Search by Farm Rosters")
        print(" [3] Run Interactive Pedigree Builder Engine")
        print(" [4] See Stallion Stats")
        print(" [5] Run Hypomating Engine")
        print(" [6] Sales History")
        print(" [E] Exit Application")
        print("=========================================")
        
        choice = input("Select an option (1-6 or E): ").strip()

        if choice.lower() == 'e':
            print("Exiting application. Goodbye!")
            break

        elif choice == "1":
            user_wants = input("Which horse's profile do you want to see? ").strip()
            if user_wants:
                display_stallion_profile(user_wants, all_profiles)

        elif choice == "2":
            # Extract unique farms dynamically out of loaded profiles
            unique_farms = sorted(list({info.get("Farm") for info in all_profiles.values() if info.get("Farm")}))
            
            if not unique_farms:
                print("ℹ️  No logged farms found inside the current stallion profiles registry.")
                continue

            print("\nAvailable Farm Rosters:")
            for idx, farm in enumerate(unique_farms, 1):
                print(f" [{idx}] {farm.replace('_', ' ').title()}")
                
            try:
                farm_choice = input("\nSelect a farm by number (or 'B' to go back): ").strip()
                if farm_choice.lower() == 'b': 
                    continue
                selected_farm_file = unique_farms[int(farm_choice) - 1]
            except (ValueError, IndexError):
                print("❌ Invalid farm selection.")
                continue

            farm_roster = [name for name, info in all_profiles.items() if info.get("Farm") == selected_farm_file]
            
            print(f"\nRoster for {selected_farm_file.replace('_', ' ').title()}:")
            for idx, name in enumerate(farm_roster, 1):
                print(f"  [{idx}] {name.upper()}")
                
            selection = input("\nEnter the horse name or roster number: ").strip()
            if not selection: 
                continue
            
            if selection.isdigit():
                sel_idx = int(selection) - 1
                target_name = farm_roster[sel_idx] if 0 <= sel_idx < len(farm_roster) else None
            else:
                target_name = selection

            if target_name:
                display_stallion_profile(target_name, all_profiles)
            else:
                print(f"❌ Selection '{selection}' not found.")

        elif choice == "3":
            print("\n==================================================")
            print("   🐎 Launching Standalone Pedigree Builder 🐎   ")
            print("==================================================\n")
            try:
                import add_pedigrees
                # Reload ensures any file modifications are read live on successive runs
                importlib.reload(add_pedigrees)
                add_pedigrees.main()
                # Post-run synchronization to update main.py's internal database cache
                PEDIGREE_DATABASE = load_and_sync_all_data()
            except ImportError:
                print("❌ Error: Could not locate 'add_pedigrees.py' in the current working directory.")
            except Exception as e:
                print(f"⚠️ An error occurred while running the pedigree builder: {e}")
                        
        elif choice == "4":
            stallion_stats.run_stats_menu()
            
        elif choice == "5":
            hypomating_engine.run_hypomating_menu(PEDIGREE_DATABASE, all_profiles)
            
        elif choice == "6":  
            import sales_history
            sales_history.run_sales_menu(PEDIGREE_DATABASE)
            
        else:
            if choice:
                print("❌ Invalid entry. Select a valid choice from the menu window.")
print_pedigree = print_pedigree_grid