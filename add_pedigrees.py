import os
import re
import pprint

# File path to the database
DB_FILE = "pedigrees_database.py"

def clean_horse_name(name: str) -> str:
    """Normalizes horse names precisely for dictionary keys (matching pedigrees_cleaner)."""
    if not name or not isinstance(name, str):
        return ""
    cleaned = name.upper()
    cleaned = cleaned.replace("’", "").replace("'", "").replace(".", "").replace("-", "")
    cleaned = cleaned.replace("(", " ").replace(")", " ")
    return " ".join(cleaned.split()).strip()

def load_database() -> dict:
    """Loads the pedigree database map dynamically."""
    if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0:
        return {}
    try:
        namespace = {}
        with open(DB_FILE, "w" if not os.path.exists(DB_FILE) else "r", encoding="utf-8") as f:
            if os.path.exists(DB_FILE):
                exec(f.read(), namespace)
        return namespace.get("pedigree_map", {})
    except Exception as e:
        print(f"⚠️ Warning loading database ({e}). Starting fresh.")
        return {}

def save_database(pedigree_map: dict):
    """Saves the database matching the exact structural layout of pedigrees_cleaner."""
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            f.write('"""\nAutomatically compiled pedigree database\n"""\n\n')
            f.write("pedigree_map = {\n")
            for horse, tree in sorted(pedigree_map.items()):
                f.write(f"    {repr(horse)}: {repr(tree)},\n")
            f.write("}\n")
    except Exception as e:
        print(f"❌ Error saving database: {e}")

def count_tree_depth(tree: dict) -> int:
    """Calculates the maximum generation depth of a given pedigree sub-tree node."""
    if not isinstance(tree, dict):
        return 0
    sire_depth = count_tree_depth(tree.get("Sire")) if "Sire" in tree else 0
    dam_depth = count_tree_depth(tree.get("Dam")) if "Dam" in tree else 0
    return 1 + max(sire_depth, dam_depth)

def find_all_horse_sub_trees(tree: dict, target_full_name: str, results: list):
    """Scans a pedigree dictionary tree and appends all matching nodes to a results list."""
    if not isinstance(tree, dict):
        return
    if tree.get("Horse") == target_full_name:
        results.append(tree)
    if "Sire" in tree:
        find_all_horse_sub_trees(tree["Sire"], target_full_name, results)
    if "Dam" in tree:
        find_all_horse_sub_trees(tree["Dam"], target_full_name, results)

def is_valid_tree(tree: dict) -> bool:
    """Helper to check if a pedigree node actually has valid printable lineages."""
    if not tree or not isinstance(tree, dict):
        return False
    sire = tree.get("Sire", {})
    dam = tree.get("Dam", {})
    sire_name = sire.get("Horse", "") if isinstance(sire, dict) else str(sire)
    dam_name = dam.get("Horse", "") if isinstance(dam, dict) else str(dam)
    
    # If both immediate parents are missing or marked unknown, it's not a useful template
    if "UNKNOWN" in sire_name.upper() and "UNKNOWN" in dam_name.upper():
        return False
    return True

def find_autofill_template(database: dict, target_name: str, target_year: str) -> dict:
    """
    Looks everywhere in the master database dictionary for a horse node match.
    Rejects templates where parents are merely 'Unknown'.
    """
    from main import clean_horse_name as main_clean
    from pq_scraper.ancestors import build_lookup_index, lookup_tree, useful_node

    hit = lookup_tree(build_lookup_index(database, main_clean), target_name, target_year, main_clean)
    if hit and useful_node(hit) and is_valid_tree(hit):
        return hit

    cleaned_key = clean_horse_name(target_name)
    year_key = f"{cleaned_key} ({target_year})" if target_year and str(target_year) not in ("", "None") else ""
    if year_key and year_key in database:
        top_tree = database[year_key]
        if is_valid_tree(top_tree):
            return top_tree
    if cleaned_key in database:
        top_tree = database[cleaned_key]
        expected_full_title = f"{target_name} ({target_year})" if target_year and target_year != "None" else target_name
        if top_tree.get("Horse") == expected_full_title and is_valid_tree(top_tree):
            return top_tree

    full_target_string = f"{target_name} ({target_year})" if target_year and target_year != "None" else target_name
    all_matches = []
    
    for key, top_tree in database.items():
        find_all_horse_sub_trees(top_tree, full_target_string, all_matches)
        
    # Filter out trees that only contain unknown branches
    valid_matches = [m for m in all_matches if is_valid_tree(m)]
        
    if not valid_matches:
        return None
        
    valid_matches.sort(key=count_tree_depth, reverse=True)
    return valid_matches[0]

def generate_linear_prompt_plan(current_depth: int, max_depth: int, node_id: str, relation_context: str) -> list:
    """Pre-calculates execution steps following the EXACT structure of pedigrees_cleaner.py."""
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
    """Runs a step-by-step state engine mimicking the pedigrees_cleaner layout with rollback options."""
    flat_steps = generate_linear_prompt_plan(0, 5, "Root", "")
    
    initial_name = initial_name.upper()
    collected_values = {
        "Root_NAME": initial_name,
        "Root_YEAR": initial_year if initial_year else "None",
        "Root_FULL": f"{initial_name} ({initial_year})" if initial_year else initial_name
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

        autofill_tree = find_autofill_template(database, parent_name, parent_year)
        if autofill_tree and isinstance(autofill_tree, dict):
            autofill_tree = autofill_tree.get(step["relation_label"])
        
        if autofill_tree and isinstance(autofill_tree, dict) and autofill_tree.get("Horse"):
            full_title = autofill_tree["Horse"]
            
            # Double check to prevent autofilling downstream nodes if they are unknown variables
            if "UNKNOWN" not in full_title.upper():
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

        # Active Manual Prompt Mode
        if step_type == "NAME":
            prompt_msg = f"Enter {parent_full}'s {step['relation_label']}: "
            ui = input(prompt_msg).strip().upper()
            
            if ui in ['B', 'BACK']:
                if step_idx > 0:
                    step_idx -= 1
                    while step_idx > 0:
                        prev_step = flat_steps[step_idx]
                        p_name = collected_values.get(f"{prev_step['parent_id']}_NAME", "")
                        p_year = collected_values.get(f"{prev_step['parent_id']}_YEAR", "")
                        
                        p_tree = find_autofill_template(database, p_name, p_year)
                        has_autofill = p_tree.get(prev_step['relation_label']) if isinstance(p_tree, dict) else None
                        
                        if "UNKNOWN" in p_name.upper() or has_autofill:
                            step_idx -= 1
                        else:
                            break
                    print("👈 Rolled back one step.")
                    continue
                else:
                    print("❌ Cannot roll back past the primary master horse details.")
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
                
            ui = input(f"Enter {current_name}'s foaling year: ").strip()
            
            if ui.lower() in ['b', 'back']:
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

def main():
    print("==========================================")
    print("   🐎 5-GENERATION PEDIGREE BUILDER 🐎   ")
    print("   (Type 'b' or 'back' to go back a line)  ")
    print("==========================================\n")
    
    database = load_database()
    
    root_name = input("Enter Horse Name: ").strip().upper()
    if not root_name:
        print("❌ Error: Master horse name cannot be empty.")
        return

    root_bare = re.sub(r"\s*\(\d{4}\)", "", root_name).strip().upper()
    existing_years = []
    for key, tree in database.items():
        key_bare = re.sub(r"\s*\(\d{4}\)", "", str(key)).strip().upper()
        if key_bare != root_bare:
            continue
        label = f"{key} {(tree or {}).get('Horse', '')}"
        found = re.search(r"\((\d{4})\)", label)
        if found and found.group(1) not in existing_years:
            existing_years.append(found.group(1))
    existing_years.sort()
    if len(existing_years) >= 2:
        print(f"\nMultiple horses named {root_bare} are in the pedigree database.")
        print("Which foaling year do you want?")
        for idx, year in enumerate(existing_years, 1):
            print(f"  [{idx}] {root_bare} ({year})")
        
    root_year = input(f"Enter {root_name}'s foaling year: ").strip()
    if root_year.isdigit() and len(existing_years) >= 2 and 1 <= int(root_year) <= len(existing_years) and root_year not in existing_years:
        root_year = existing_years[int(root_year) - 1]
    
    root_full_title = f"{root_name} ({root_year})" if root_year else root_name
    root_key = clean_horse_name(root_name)
    
    print(f"\nBuilding 5-generation tree for: {root_full_title}")
    print("-" * 50)
    
    final_tree = execute_interactive_pedigree_builder(database, root_name, root_year)
    
    database[root_key] = final_tree
    save_database(database)
    print("\n💾 Success! Pedigree database compiled and saved.")

if __name__ == "__main__":
    main()