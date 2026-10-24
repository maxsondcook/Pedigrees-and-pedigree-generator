import os
import re
import sys

def clean_horse_name(name: str) -> str:
    """Normalizes horse names precisely for dictionary keys."""
    if not name or not isinstance(name, str): 
        return ""
    cleaned = name.upper()
    cleaned = cleaned.replace("’", "").replace("'", "").replace(".", "").replace("-", "")
    cleaned = cleaned.replace("(", " ").replace(")", " ")
    return " ".join(cleaned.split()).strip()

PEDIGREE_DB_FILE = "pedigrees_database.py"
BYPASS_DB_FILE = "permanent_bypass_list.py"

def load_databases():
    pedigrees = {}
    bypass_list = []
    
    if os.path.exists(PEDIGREE_DB_FILE):
        try:
            with open(PEDIGREE_DB_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            if content.strip():
                loc = {}
                exec(content, {}, loc)
                pedigrees = loc.get("pedigree_map", {})
        except Exception as e:
            print(f"⚠️ Error loading pedigrees database: {e}")
            
    if os.path.exists(BYPASS_DB_FILE):
        try:
            with open(BYPASS_DB_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            if content.strip():
                loc = {}
                exec(content, {}, loc)
                bypass_list = loc.get("PERMANENT_BYPASS_LIST", [])
        except Exception as e:
            print(f"⚠️ Error loading bypass database: {e}")
            
    return pedigrees, bypass_list

def save_databases(pedigrees, bypass_list):
    try:
        with open(PEDIGREE_DB_FILE, "w", encoding="utf-8") as f:
            f.write('"""\nAutomatically compiled pedigree database\n"""\n\n')
            f.write("pedigree_map = {\n")
            for horse, tree in sorted(pedigrees.items()):
                # 🌟 FIX: Forces dictionary keys to be ALL CAPS when written to the database
                f.write(f"    {repr(horse.upper())}: {repr(tree)},\n")
            f.write("}\n")
    except Exception as e:
        print(f"❌ Error saving pedigrees database: {e}")

    try:
        with open(BYPASS_DB_FILE, "w", encoding="utf-8") as f:
            f.write("# Horses to permanently ignore for incomplete ancestry cleanups\n")
            f.write(f"PERMANENT_BYPASS_LIST = {repr(sorted(list(set(bypass_list))))}\n")
    except Exception as e:
        print(f"❌ Error saving bypass database: {e}")

def count_tree_depth(tree: dict) -> int:
    if not isinstance(tree, dict):
        return 0
    sire_depth = count_tree_depth(tree.get("Sire")) if "Sire" in tree else 0
    dam_depth = count_tree_depth(tree.get("Dam")) if "Dam" in tree else 0
    return 1 + max(sire_depth, dam_depth)

def find_all_horse_sub_trees(tree: dict, target_full_name: str, results: list):
    if not isinstance(tree, dict):
        return
    if tree.get("Horse") == target_full_name:
        results.append(tree)
    if "Sire" in tree:
        find_all_horse_sub_trees(tree["Sire"], target_full_name, results)
    if "Dam" in tree:
        find_all_horse_sub_trees(tree["Dam"], target_full_name, results)

def find_autofill_template(database: dict, target_name: str, target_year: str, index=None) -> dict:
    from main import clean_horse_name as main_clean
    from pq_scraper.ancestors import build_lookup_index, lookup_tree

    if index is None:
        index = build_lookup_index(database, main_clean)
    hit = lookup_tree(index, target_name, target_year, main_clean)
    if hit:
        return hit

    cleaned_key = clean_horse_name(target_name)
    year_key = f"{cleaned_key} ({target_year})" if target_year and str(target_year) not in ("", "None") else ""
    if year_key and year_key in database:
        top_tree = database[year_key]
        if top_tree:
            return top_tree
    if cleaned_key in database:
        top_tree = database[cleaned_key]
        expected_full_title = f"{target_name.upper()} ({target_year})" if target_year and target_year != "None" else target_name.upper()
        if top_tree.get("Horse") == expected_full_title:
            return top_tree

    full_target_string = f"{target_name.upper()} ({target_year})" if target_year and target_year != "None" else target_name.upper()
    all_matches = []
    
    for key, top_tree in database.items():
        find_all_horse_sub_trees(top_tree, full_target_string, all_matches)
        
    if not all_matches:
        return None
        
    all_matches.sort(key=count_tree_depth, reverse=True)
    return all_matches[0]

def check_tree_is_incomplete(node, current_gen=0, max_gen=5):
    if current_gen >= max_gen - 1:
        return False 

    if not node or not isinstance(node, dict):
        return True

    sire_node = node.get("Sire")
    dam_node = node.get("Dam")

    if not sire_node or not isinstance(sire_node, dict) or "Horse" not in sire_node:
        return True
    if not dam_node or not isinstance(dam_node, dict) or "Horse" not in dam_node:
        return True

    sire_name = sire_node.get("Horse", "")
    dam_name = dam_node.get("Horse", "")

    if "unknown" in sire_name.lower() or "unknown" in dam_name.lower():
        return True

    return check_tree_is_incomplete(sire_node, current_gen + 1, max_gen) or check_tree_is_incomplete(dam_node, current_gen + 1, max_gen)

def extract_all_ancestor_names_and_nodes(node, found_horses=None):
    """Recursively crawls a tree branch to find every unique horse node."""
    if found_horses is None:
        found_horses = {}
        
    if not node or not isinstance(node, dict):
        return found_horses
        
    horse_full_name = node.get("Horse", "").strip()
    if horse_full_name and "UNKNOWN" not in horse_full_name.upper():
        match = re.match(r"(.*) \((\d{4})\)", horse_full_name)
        base_name = match.group(1).strip() if match else horse_full_name
        year = match.group(2).strip() if match else ""
        cleaned = clean_horse_name(base_name)
        ident = (cleaned, year)
        
        if ident not in found_horses or count_tree_depth(node) > count_tree_depth(found_horses[ident]["node"]):
            found_horses[ident] = {
                "full_name": horse_full_name,
                "base_name": base_name,
                "year": year,
                "cleaned": cleaned,
                "node": node
            }
            
    if "Sire" in node:
        extract_all_ancestor_names_and_nodes(node["Sire"], found_horses)
    if "Dam" in node:
        extract_all_ancestor_names_and_nodes(node["Dam"], found_horses)
        
    return found_horses

def extract_and_register_ancestors(node, pedigrees):
    if not node or not isinstance(node, dict):
        return

    horse_name = node.get("Horse", "").strip()
    if not horse_name or "UNKNOWN" in horse_name.upper():
        return

    match = re.match(r"(.*) \((\d{4})\)", horse_name)
    base_name = match.group(1).strip() if match else horse_name
    year = match.group(2).strip() if match else ""
    from main import clean_horse_name as main_clean
    from pq_scraper.dbio import storage_key_for

    cleaned_key = main_clean(base_name)
    store_key = storage_key_for(cleaned_key, year, pedigrees, main_clean)
    
    if store_key not in pedigrees or check_tree_is_incomplete(pedigrees[store_key], 0, 5):
        pedigrees[store_key] = {
            "Horse": horse_name.upper(),
            "Sire": node.get("Sire", {"Horse": "UNKNOWN SIRE"}),
            "Dam": node.get("Dam", {"Horse": "UNKNOWN DAM"})
        }

    if "Sire" in node:
        extract_and_register_ancestors(node["Sire"], pedigrees)
    if "Dam" in node:
        extract_and_register_ancestors(node["Dam"], pedigrees)

def generate_linear_prompt_plan(current_depth: int, max_depth: int, node_id: str, relation_context: str) -> list:
    if current_depth >= max_depth:
        return []
        
    steps = []
    sire_node_id = f"{node_id}_Sire"
    dam_node_id = f"{node_id}_Dam"
    
    steps.append({
        "type": "NAME",
        "node_id": sire_node_id,
        "parent_id": node_id,
        "relation_label": "Sire",
        "context_string": relation_context
    })
    steps.append({
        "type": "YEAR",
        "node_id": sire_node_id,
        "parent_id": node_id,
        "relation_label": "Sire"
    })
    
    steps.append({
        "type": "NAME",
        "node_id": dam_node_id,
        "parent_id": node_id,
        "relation_label": "Dam",
        "context_string": relation_context
    })
    steps.append({
        "type": "YEAR",
        "node_id": dam_node_id,
        "parent_id": node_id,
        "relation_label": "Dam"
    })
    
    steps.extend(generate_linear_prompt_plan(current_depth + 1, max_depth, sire_node_id, "Sire"))
    steps.extend(generate_linear_prompt_plan(current_depth + 1, max_depth, dam_node_id, "Dam"))
    
    return steps

def execute_interactive_pedigree_builder(database: dict, initial_name: str, initial_year: str) -> dict:
    from main import clean_horse_name as main_clean
    from pq_scraper.ancestors import build_lookup_index

    lookup_index = build_lookup_index(database, main_clean)
    flat_steps = generate_linear_prompt_plan(0, 5, "Root", "")
    
    # 🌟 FIX: Ensures initial values are kept consistently capitalized
    initial_name = initial_name.upper()
    collected_values = {
        "Root_NAME": initial_name,
        "Root_YEAR": initial_year if initial_year else "None",
        "Root_FULL": f"{initial_name} ({initial_year})" if initial_year and initial_year != "None" else initial_name
    }
    
    step_idx = 0  
    while step_idx < len(flat_steps):
        step = flat_steps[step_idx]
        node_id = step["node_id"]
        parent_id = step["parent_id"]
        step_type = step["type"]
        val_key = f"{node_id}_{step_type}"
        
        parent_name = collected_values.get(f"{parent_id}_NAME", "")
        parent_year = collected_values.get(f"{parent_id}_YEAR", "None")
        parent_full = collected_values.get(f"{parent_id}_FULL", parent_name)
        
        if "UNKNOWN" in parent_name.upper():
            if step_type == "NAME":
                collected_values[val_key] = f"UNKNOWN {step['relation_label'].upper()}"
                collected_values[f"{node_id}_FULL"] = f"UNKNOWN {step['relation_label'].upper()}"
            else:
                collected_values[val_key] = "None"
            step_idx += 1
            continue

        autofill_tree = find_autofill_template(database, parent_name, parent_year, index=lookup_index)
        if autofill_tree and isinstance(autofill_tree, dict):
            autofill_tree = autofill_tree.get(step["relation_label"])
        
        if autofill_tree and isinstance(autofill_tree, dict) and autofill_tree.get("Horse") and "unknown" not in autofill_tree.get("Horse", "").lower():
            full_title = autofill_tree["Horse"].upper()
            match = re.match(r"(.*) \((\d{4})\)", full_title)
            h_name = match.group(1) if match else full_title
            h_year = match.group(2) if match else "None"
            
            collected_values[f"{node_id}_NAME"] = h_name
            collected_values[f"{node_id}_YEAR"] = h_year
            collected_values[f"{node_id}_FULL"] = full_title
            
            if step_type == "NAME":
                print(f"🔄 Autofilled {parent_full}'s {step['relation_label']}: {full_title}")
            step_idx += 1
            continue

        if step_type == "NAME":
            prompt_msg = f"Enter {parent_full}'s {step['relation_label']} (or 'b' to go back): "
            ui = input(prompt_msg).strip().upper()  # 🌟 FIX: Auto-caps input typed in terminal
            
            if ui in ['B', 'BACK']:
                if step_idx > 0:
                    step_idx -= 1
                    while step_idx > 0:
                        prev_step = flat_steps[step_idx]
                        p_name = collected_values.get(f"{prev_step['parent_id']}_NAME", "")
                        p_year = collected_values.get(f"{prev_step['parent_id']}_YEAR", "")
                        
                        p_tree = find_autofill_template(database, p_name, p_year, index=lookup_index)
                        has_autofill = p_tree.get(prev_step['relation_label']) if isinstance(p_tree, dict) else None
                        
                        if "UNKNOWN" in p_name.upper() or has_autofill:
                            step_idx -= 1
                        else:
                            break
                    print("👈 Rolled back one step.")
                    continue
                else:
                    print("❌ Cannot roll back past the primary horse details.")
                    continue
            
            if not ui:
                ui = f"UNKNOWN {step['relation_label'].upper()}"
                
            collected_values[val_key] = ui
            collected_values[f"{node_id}_FULL"] = ui
            step_idx += 1

        elif step_type == "YEAR":
            current_name = collected_values.get(f"{node_id}_NAME", "")
            if "UNKNOWN" in current_name.upper():
                collected_values[val_key] = "None"
                collected_values[f"{node_id}_FULL"] = current_name
                step_idx += 1
                continue
                
            ui = input(f"Enter {current_name}'s foaling year (or 'b' to go back): ").strip()
            
            if ui.upper() in ['B', 'BACK']:
                step_idx -= 1
                print("👈 Rolled back one step.")
                continue
                
            collected_values[val_key] = ui if ui else "None"
            collected_values[f"{node_id}_FULL"] = f"{current_name} ({ui})" if ui else current_name
            step_idx += 1

    def assemble_node(node_id: str) -> dict:
        name = collected_values.get(f"{node_id}_NAME", "UNKNOWN").upper()
        year = collected_values.get(f"{node_id}_YEAR", "None")
        full_title = f"{name} ({year})" if year != "None" else name
        
        node = {"Horse": full_title}
        sire_id = f"{node_id}_Sire"
        dam_id = f"{node_id}_Dam"
        
        if f"{sire_id}_NAME" in collected_values:
            node["Sire"] = assemble_node(sire_id)
        if f"{dam_id}_NAME" in collected_values:
            node["Dam"] = assemble_node(dam_id)
            
        return node

    return assemble_node("Root")

def run_cleaner():
    print("=========================================================")
    print("   AUTOMATED 5-GENERATION PEDIGREE CLEANER & FILLER     ")
    print("=========================================================")
    
    pedigrees, bypass_list = load_databases()
    if not pedigrees:
        print("ℹ️ The pedigree database is empty. Nothing to clean.")
        return

    session_skips = set()

    while True:
        all_discovered_horses = {}
        for top_key, top_tree in pedigrees.items():
            extract_all_ancestor_names_and_nodes(top_tree, all_discovered_horses)

        incomplete_targets = []
        for _ident, meta in sorted(all_discovered_horses.items(), key=lambda kv: kv[0]):
            cleaned_hk = meta.get("cleaned") or clean_horse_name(meta["base_name"])
            cleaned_hk_no_year = re.sub(r'\s\d{4}$', '', cleaned_hk).strip()
            
            if (cleaned_hk in bypass_list or 
                cleaned_hk_no_year in bypass_list or 
                cleaned_hk in session_skips or 
                cleaned_hk_no_year in session_skips):
                continue
                
            if check_tree_is_incomplete(meta["node"], current_gen=0, max_gen=5):
                incomplete_targets.append(meta)

        if not incomplete_targets:
            print("\n✅ Success! All processed deep-ancestor records meet 5-generation completion thresholds.")
            save_databases(pedigrees, bypass_list)
            break

        print(f"\n📋 Found {len(incomplete_targets)} distinct ancestral records requiring backfills.")
        
        target_meta = incomplete_targets[0]
        horse_display_name = target_meta["full_name"]
        base_name = target_meta["base_name"]
        birth_year = target_meta["year"]
        
        cleaned_key = clean_horse_name(base_name)
        cleaned_key_no_year = re.sub(r'\s\d{4}$', '', cleaned_key).strip()

        print("\n" + "="*75)
        print(f"⚠️  INCOMPLETE ANCESTRY PROFILE DETECTED: {horse_display_name.upper()}")
        print("="*75)
        print(" [1] Input missing pedigree lines now (Linear Builder Mode)")
        print(" [2] Skip for now (Ask me again next runtime loop)")
        print(" [3] Skip forever (Log to permanent bypass list)")
        print(" [X] Save current session progress and exit tool")
        print("="*75)
        
        choice = input("Select operation choice: ").strip().upper()
        
        if choice == "1":
            print(f"\nBuilding/Completing 5-generation tree for: {horse_display_name.upper()}")
            print("-" * 50)
            updated_tree = execute_interactive_pedigree_builder(pedigrees, base_name, birth_year)
            
            pedigrees[cleaned_key.upper()] = updated_tree
            
            extract_and_register_ancestors(updated_tree, pedigrees)
            save_databases(pedigrees, bypass_list)
            print(f"✅ Saved structural records for {horse_display_name.upper()} and all registered ancestors.")
        elif choice == "2":
            print(f"⏭️ Skipping {horse_display_name.upper()} for this session.")
            session_skips.add(cleaned_key.upper())
            session_skips.add(cleaned_key_no_year.upper())
        elif choice == "3":
            print(f"🛑 Adding {horse_display_name.upper()} to permanent bypass filtering.")
            if cleaned_key.upper() not in bypass_list:
                bypass_list.append(cleaned_key.upper())
            if cleaned_key_no_year.upper() not in bypass_list:
                bypass_list.append(cleaned_key_no_year.upper())
            save_databases(pedigrees, bypass_list)
        elif choice == "X":
            print("💾 Saving progress and closing environment. Goodbye!")
            save_databases(pedigrees, bypass_list)
            sys.exit(0)
        else:
            print("❌ Invalid entry sequence. Defaulting to session skip step.")
            session_skips.add(cleaned_key.upper())
            session_skips.add(cleaned_key_no_year.upper())
            
    print("\n🏁 Finished running all cleaner operations.")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--stitch", "stitch"):
        from pq_scraper.stitch import main as stitch_main
        raise SystemExit(stitch_main())
    run_cleaner()