import os
import re
import pandas as pd
import sys
import copy

# Import core tools and databases from your system files
import main
import hypomating_engine

INPUT_DIR = "Upcoming Sales"
OUTPUT_DIR = "Analyzed Sales"

STATE_MAP = {
    "KENTUCKY": "KY", "NEW YORK": "NY", "NEW JERSEY": "NJ", "FLORIDA": "FL",
    "CALIFORNIA": "CA", "MARYLAND": "MD", "PENNSYLVANIA": "PA", "TEXAS": "TX",
    "VIRGINIA": "VA", "LOUISIANA": "LA", "OKLAHOMA": "OK", "ONTARIO": "ON"
}

def clean_filename_title(filename):
    name = re.sub(r'\.csv$', '', filename, flags=re.IGNORECASE).lower()
    if name.startswith("analyzed_"):
        name = name.replace("analyzed_", "")
    name = re.sub(r'\s+', '_', name)
    return f"analyzed_{name}.csv"

def extract_sale_year(filename):
    """Finds a 4-digit year in the file name string. Defaults to 2026 if missing."""
    match = re.search(r'\b(20\d{2})\b', filename)
    if match:
        return int(match.group(1))
    return 2026

def uppercase_country_suffix(text):
    """Finds horse country suffixes like (gb), (ire), (aus) and converts them to uppercase (GB), (IRE).
       Also ensures there is a space right before the opening parenthesis if missing.
    """
    if not text or pd.isna(text):
        return ""
    text_str = str(text)
    def repl(match):
        prefix = match.group(1)
        suffix = match.group(2).upper()
        space = " " if prefix and not prefix.endswith(" ") else ""
        return f"{prefix}{space}({suffix})"
    
    return re.sub(r'(.*?)\(([a-zA-Z]{2,3})\)', repl, text_str)

def determine_sold_as(birth_year_str, sex_str, sale_year, filename="", covering_sire_str=""):
    """Calculates age relative to the sale year and classifies the horse type."""
    if covering_sire_str and str(covering_sire_str).strip().lower() not in ['nan', 'none', '']:
        return "Broodmare"

    # If Yearling appears in file name and no birth year is provided, default to Yearling
    if "yearling" in filename.lower() and (not birth_year_str or str(birth_year_str).lower() in ['nan', 'none', '']):
        return "Yearling"

    sex = str(sex_str).strip().upper()
    birth_year = None
    if birth_year_str and str(birth_year_str).lower() not in ['nan', 'none', '']:
        year_match = re.search(r'\b(\d{4})\b', str(birth_year_str))
        if year_match:
            birth_year = int(year_match.group(1))
            
    if birth_year is None:
        return "Yearling" if "yearling" in filename.lower() else "Unknown"
        
    age = sale_year - birth_year
    
    if age == 0:
        return "Weanling"
    elif age == 1:
        return "Yearling"
    elif age in [2, 3]:
        if sex == 'F': return "Filly"
        if sex == 'C': return "Colt"
        if sex == 'G': return "Gelding"
        return "Two-Year-Old" if age == 2 else "Three-Year-Old"
    elif age >= 4:
        if age >= 7 and sex in ['M', 'F']:
            return "Broodmare"
            
        if sex == 'G': 
            return "Racing Prospect"
        if sex in ['F', 'M']: 
            return "Broodmare/Racing Prospect"
        if sex in ['C', 'H', 'S']: 
            return "Stallion/Racing Prospect"
        return "Racing/Broodmare Prospect"
        
    return "Unknown"

def convert_distance_to_furlongs(dist_str):
    dist_str = str(dist_str).lower().strip()
    clean_d = re.sub(r'\s*\([^)]*\)', '', dist_str).strip()
    num_match = re.search(r'[\d\.]+', clean_d)
    if not num_match:
        return "0 furlongs"
    val = float(num_match.group(0))
    if "meter" in clean_d or val > 100:
        furlongs = round(val / 201.168, 1)
        if furlongs.is_integer(): furlongs = int(furlongs)
        return f"{furlongs} furlongs"
    elif "mile" in clean_d:
        furlongs = round(val * 8, 1)
        if furlongs.is_integer(): furlongs = int(furlongs)
        return f"{furlongs} furlongs"
    else:
        if val.is_integer(): val = int(val)
        return f"{val} furlongs"

def wrap_text_to_lines(text, max_width):
    tokens = re.split(r'(\s+|/)', text)
    lines = []
    current_line = ""
    
    for token in tokens:
        if not token:
            continue
        if re.match(r'^\s+$', token):
            continue
            
        test_line = current_line + token if current_line.endswith('/') or token == '/' else (current_line + " " + token if current_line else token)
        
        if len(test_line) <= max_width or token == '/':
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = token
            
    if current_line:
        lines.append(current_line)
    return lines

def format_race_list_grammatically(races):
    if not races:
        return ""
    if len(races) == 1:
        return races[0]
    if len(races) == 2:
        return f"{races[0]} and {races[1]}"
    return ", ".join(races[:-1]) + f", and {races[-1]}"

def analyze_dataframe(df):
    """Core analysis engine that calculates cross successes and producer stats."""
    for col in ["CROSS SUCCESS", "DAM SUCCESS (RACER)", "DAM SUCCESS (PRODUCER)", "RACING SUCCESS", "STARRED", "COVERING SIRE", "NOTES"]:
        if col not in df.columns:
            df[col] = ""
        else:
            df[col] = df[col].fillna("")

    # Place==1 winners from the IFHA worldwide file (Grade is aliased from Group).
    raw_stakes = hypomating_engine.load_stakes_data()
    horse_summaries = hypomating_engine.build_horse_summaries(raw_stakes)
    pedigree_db = main.PEDIGREE_DATABASE

    for idx, row in df.iterrows():
        h_name_raw = str(row.get('HORSE NAME', '')).strip()
        sire = str(row.get('SIRE', '')).strip()
        dam = str(row.get('DAM', '')).strip()
        bms = str(row.get('SIRE OF DAM', '')).strip()
        
        clean_sire = main.clean_horse_name(sire)
        clean_dam = main.clean_horse_name(dam)
        clean_bms = main.clean_horse_name(bms)
        
        cross_winners = []
        sire_relatives = [clean_sire]
        if hasattr(hypomating_engine, 'find_lineage_relatives'):
            sire_relatives.extend([main.clean_horse_name(r) for r in hypomating_engine.find_lineage_relatives(clean_sire)])
        
        for h_name, h in horse_summaries.items():
            clean_h = main.clean_horse_name(h_name)
            if clean_h in pedigree_db:
                h_ped = pedigree_db[clean_h]
                
                raw_sire_node = h_ped.get("Sire", "")
                if isinstance(raw_sire_node, dict):
                    raw_sire_original = raw_sire_node.get("Horse", "")
                else:
                    raw_sire_original = str(raw_sire_node)
                    
                raw_sire_clean_name = re.sub(r'\s*\(\d{4}\)', '', raw_sire_original).strip()
                h_sire = main.clean_horse_name(raw_sire_clean_name)
                h_bms = main.clean_horse_name(hypomating_engine.get_mare_sire_from_pedigree(h_ped.get("Dam", {})))
                
                if h_sire in sire_relatives and h_bms == clean_bms:
                    status_display = h['status']
                    if "Graded Stakes Winner" in status_display:
                        status_display = "GSW"
                    elif "Stakes Winner" in status_display:
                        status_display = "SW"
                        
                    if h_sire != clean_sire:
                        cross_winners.append(f"{h_name}[{raw_sire_clean_name}] ({status_display})")
                    else:
                        cross_winners.append(f"{h_name} ({status_display})")
        
        if cross_winners:
            formatted_cross_winners = [uppercase_country_suffix(w) for w in cross_winners]
            df.at[idx, "CROSS SUCCESS"] = ", ".join(list(set(formatted_cross_winners)))

        # DAM SUCCESS (RACER)
        dam_match = horse_summaries.get(dam) or next((h for name, h in horse_summaries.items() if main.clean_horse_name(name) == clean_dam), None)
        if dam_match:
            races_text = " | ".join(dam_match['races'])
            df.at[idx, "DAM SUCCESS (RACER)"] = uppercase_country_suffix(f"{dam_match['name']} ({dam_match['status']}) won: {races_text}")

        # DAM SUCCESS (PRODUCER) & RACING SUCCESS
        progeny_strings = []
        racing_success_strings = []
        
        for h_name, h in horse_summaries.items():
            clean_h = main.clean_horse_name(h_name)
            if clean_h in pedigree_db:
                h_ped = pedigree_db[clean_h]
                h_dam = main.clean_horse_name(h_ped.get("Dam", {}).get("Horse", "") if isinstance(h_ped.get("Dam"), dict) else str(h_ped.get("Dam", "")))
                
                if h_dam == clean_dam:
                    h_sire_name = h_ped.get("Sire", {}).get("Horse", "") if isinstance(h_ped.get("Sire"), dict) else str(h_ped.get("Sire", ""))
                    h_sire_desc = re.sub(r'\s*\(\d{4}\)', '', h_sire_name).strip()
                    
                    races_found = []
                    for rec in raw_stakes:
                        if main.clean_horse_name(rec.get('Horse Name', '')) == clean_h:
                            raw_dist = str(rec.get('Distance', ''))
                            clean_dist_text = convert_distance_to_furlongs(raw_dist)
                            surf = "dirt" if "(D)" in raw_dist.upper() else "turf" if "(T)" in raw_dist.upper() else "track"
                            sex_val = str(rec.get('Sex', ''))[:1].lower()
                            
                            grade = rec.get('Grade') or rec.get('Group') or ''
                            race_desc = f"the {rec.get('Purse', '')} {grade} {rec.get('Race Name', '')} at {clean_dist_text} over the {surf}"
                            races_found.append(race_desc)
                    
                    if races_found:
                        unique_races = list(dict.fromkeys(races_found))
                        grammatical_races = format_race_list_grammatically(unique_races)
                        sentence = f"{h_name} ({sex_val}. by {h_sire_desc}) won {grammatical_races}."
                        sentence = uppercase_country_suffix(sentence)
                        
                        if clean_h == main.clean_horse_name(h_name_raw):
                            racing_success_strings.append(sentence)
                            progeny_strings.append(sentence)
                        else:
                            progeny_strings.append(sentence)
            
        if progeny_strings:
            df.at[idx, "DAM SUCCESS (PRODUCER)"] = " ".join(progeny_strings)
        if racing_success_strings:
            df.at[idx, "RACING SUCCESS"] = " ".join(racing_success_strings)
            
    df['HIP'] = pd.to_numeric(df['HIP'], errors='coerce').fillna(0).astype(int)
    return df

def get_horse_races_description(clean_h_name, raw_stakes):
    """Helper to extract race winning descriptions for a given horse."""
    races_found = []
    for rec in raw_stakes:
        if main.clean_horse_name(rec.get('Horse Name', '')) == clean_h_name:
            raw_dist = str(rec.get('Distance', ''))
            clean_dist_text = convert_distance_to_furlongs(raw_dist)
            surf = "dirt" if "(D)" in raw_dist.upper() else "turf" if "(T)" in raw_dist.upper() else "track"
            grade = rec.get('Grade') or rec.get('Group') or ''
            race_desc = f"the {rec.get('Purse', '')} {grade} {rec.get('Race Name', '')} at {clean_dist_text} over the {surf}"
            races_found.append(race_desc)
            
    if races_found:
        unique_races = list(dict.fromkeys(races_found))
        return format_race_list_grammatically(unique_races)
    return ""

def print_female_family_section(ped_data, raw_stakes, horse_summaries, total_width):
    """Builds and prints the female family block (1st dam through 4th dam),
       including grandkids (grand-offspring) indented under direct offspring.
    """
    pedigree_db = main.PEDIGREE_DATABASE
    
    ordinals = ["1st dam", "2nd dam", "3rd dam", "4th dam"]
    dams_info = []
    
    curr_node = ped_data.get("Dam") if isinstance(ped_data, dict) else None
    
    for i in range(4):
        if not curr_node or not isinstance(curr_node, dict):
            break
            
        dam_raw_name = curr_node.get("Horse", "")
        dam_clean_name = main.clean_horse_name(dam_raw_name)
        dam_display_name = re.sub(r'\s*\(\d{4}\)', '', dam_raw_name).strip()
        
        sire_node = curr_node.get("Sire", {})
        sire_raw = sire_node.get("Horse", "") if isinstance(sire_node, dict) else str(sire_node)
        sire_display = re.sub(r'\s*\(\d{4}\)', '', sire_raw).strip()
        
        dams_info.append({
            'ordinal': ordinals[i],
            'clean_name': dam_clean_name,
            'display_name': dam_display_name,
            'sire': sire_display,
            'node': curr_node
        })
        curr_node = curr_node.get("Dam")

    print("-" * total_width)
    
    header_text = "| FEMALE FAMILY:"
    print(header_text.ljust(total_width - 1) + "|")

    for d in dams_info:
        print(f"| {d['ordinal']}".ljust(total_width - 1) + "|")
        
        dam_clean = d['clean_name']
        dam_disp = d['display_name']
        dam_sire = d['sire']
        
        dam_races_desc = get_horse_races_description(dam_clean, raw_stakes)
        
        if dam_races_desc:
            dam_title = dam_disp.upper()
            dam_header_str = f"{dam_title}, by {dam_sire} won {dam_races_desc}."
        else:
            dam_header_str = f"{dam_disp.title()}, by {dam_sire}"
            
        dam_header_str = uppercase_country_suffix(dam_header_str)
        
        wrapped_dam_lines = wrap_text_to_lines(dam_header_str, total_width - 4)
        for dline in wrapped_dam_lines:
            print(f"| {dline}".ljust(total_width - 1) + "|")
            
        # Find progeny (direct offspring)
        for h_name, h in horse_summaries.items():
            clean_h = main.clean_horse_name(h_name)
            if clean_h in pedigree_db:
                h_ped = pedigree_db[clean_h]
                p_dam_raw = h_ped.get("Dam", {}).get("Horse", "") if isinstance(h_ped.get("Dam"), dict) else str(h_ped.get("Dam", ""))
                
                if main.clean_horse_name(p_dam_raw) == dam_clean:
                    p_sire_raw = h_ped.get("Sire", {}).get("Horse", "") if isinstance(h_ped.get("Sire"), dict) else str(h_ped.get("Sire", ""))
                    p_sire_desc = re.sub(r'\s*\(\d{4}\)', '', p_sire_raw).strip()
                    
                    p_races = get_horse_races_description(clean_h, raw_stakes)
                    if p_races:
                        sex_char = "c" if h.get('sex', '').upper().startswith('C') else "f" if h.get('sex', '').upper().startswith('F') else "g" if h.get('sex', '').upper().startswith('G') else "c"
                        p_display_name = h_name.upper() if "Winner" in h.get('status', '') else h_name
                        p_str = f"{p_display_name} ({sex_char}. by {p_sire_desc}) won {p_races}."
                        p_str = uppercase_country_suffix(p_str)
                        
                        # Print 1st-level offspring
                        wrapped_p = wrap_text_to_lines(p_str, total_width - 8)
                        for idx_p, pline in enumerate(wrapped_p):
                            indent = "   " if idx_p == 0 else "     "
                            print(f"|{indent}{pline}".ljust(total_width - 1) + "|")
                            
                        # Find grand-offspring (grandkids) under this progeny
                        for gk_name, gk in horse_summaries.items():
                            clean_gk = main.clean_horse_name(gk_name)
                            if clean_gk in pedigree_db:
                                gk_ped = pedigree_db[clean_gk]
                                gk_dam_raw = gk_ped.get("Dam", {}).get("Horse", "") if isinstance(gk_ped.get("Dam"), dict) else str(gk_ped.get("Dam", ""))
                                
                                if main.clean_horse_name(gk_dam_raw) == clean_h:
                                    gk_sire_raw = gk_ped.get("Sire", {}).get("Horse", "") if isinstance(gk_ped.get("Sire"), dict) else str(gk_ped.get("Sire", ""))
                                    gk_sire_desc = re.sub(r'\s*\(\d{4}\)', '', gk_sire_raw).strip()
                                    
                                    gk_races = get_horse_races_description(clean_gk, raw_stakes)
                                    if gk_races:
                                        gk_sex_char = "c" if gk.get('sex', '').upper().startswith('C') else "f" if gk.get('sex', '').upper().startswith('F') else "g" if gk.get('sex', '').upper().startswith('G') else "c"
                                        gk_display_name = gk_name.upper() if "Winner" in gk.get('status', '') else gk_name
                                        gk_str = f"{gk_display_name} ({gk_sex_char}. by {gk_sire_desc}) won {gk_races}."
                                        gk_str = uppercase_country_suffix(gk_str)
                                        
                                        # Print 2nd-level grand-offspring
                                        wrapped_gk = wrap_text_to_lines(gk_str, total_width - 12)
                                        for idx_gk, gkline in enumerate(wrapped_gk):
                                            gk_indent = "      " if idx_gk == 0 else "        "
                                            print(f"|{gk_indent}{gkline}".ljust(total_width - 1) + "|")

    print("-" * total_width)

def print_notes_section(notes_text, total_width):
    """Prints a notes section formatted to match the table width."""
    print("| NOTES:")
    if notes_text and str(notes_text).strip() not in ["", "nan", "NaN", "None"]:
        wrapped_notes = wrap_text_to_lines(str(notes_text).strip(), total_width - 4)
        for line in wrapped_notes:
            print(f"| {line}".ljust(total_width - 1) + "|")
    else:
        print("| [No notes entered for this horse]".ljust(total_width - 1) + "|")
    print("-" * total_width)

def process_new_sales():
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    csv_files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith('.csv')]
    if not csv_files:
        return

    for target_filename in csv_files:
        input_csv_path = os.path.join(INPUT_DIR, target_filename)
        print(f"\nProcessing upcoming sale file: '{target_filename}'...")
        
        try:
            # Use utf-8-sig to automatically strip BOM bytes (\ufeff)
            try:
                raw_df = pd.read_csv(input_csv_path, encoding='utf-8-sig', index_col=False)
            except Exception:
                raw_df = pd.read_csv(input_csv_path, encoding='utf-8-sig', index_col=False, sep=None, engine='python')
                
            raw_df.columns = [str(c).upper().strip().lstrip('\ufeff') for c in raw_df.columns]
            sale_year = extract_sale_year(target_filename)
            
            # Smart discovery for HIP column
            hip_col = None
            for c in raw_df.columns:
                if re.search(r'\b(HIP|LOT|HIP NUMBER|HIP NO)\b', c):
                    hip_col = c
                    break
            if not hip_col and len(raw_df.columns) > 0:
                hip_col = raw_df.columns[0]

            corrected_rows = []
            for _, row in raw_df.iterrows():
                hip_val = str(row.get(hip_col, '')).strip()

                # Clean numeric hip values (e.g., '0001' -> '1')
                if hip_val and hip_val.lower() not in ['nan', 'none', '']:
                    hip_val = str(int(re.sub(r'\D', '', hip_val))) if re.sub(r'\D', '', hip_val) else hip_val
                    
                    birth_year_val = str(row.get('YEAR OF BIRTH', row.get('YOB', row.get('DOB', '')))).strip()
                    if birth_year_val.lower() in ['nan', 'none', ''] and "yearling" in target_filename.lower():
                        birth_year_val = str(sale_year - 1)

                    sex_val = str(row.get('SEX', '')).strip().upper()
                    sire_val = uppercase_country_suffix(str(row.get('SIRE', '')).strip().title())
                    dam_val = uppercase_country_suffix(str(row.get('DAM', '')).strip().title())
                    bms_val = uppercase_country_suffix(str(row.get('SIRE OF DAM', row.get('BMS', ''))).strip().title())
                    cov_sire_val = uppercase_country_suffix(str(row.get('COVERING SIRE', '')).strip().title())
                    
                    h_name = ""
                    for name_variant in ['HORSE NAME', 'NAME', 'HORSE']:
                        val = str(row.get(name_variant, '')).strip()
                        # Reject placeholder names like 'Hip 0001'
                        if val and val.lower() not in ['nan', 'none', ''] and not re.match(r'^hip\s*\d+$', val.lower()):
                            h_name = val
                            break
                    
                    if not h_name:
                        yr_digits = "00"
                        if birth_year_val and birth_year_val.lower() != 'nan':
                            year_match = re.search(r'\b\d{2}(\d{2})\b', birth_year_val)
                            if year_match:
                                yr_digits = year_match.group(1)
                        h_name = f"{sire_val} x {dam_val} '{yr_digits}"
                    else:
                        h_name = uppercase_country_suffix(h_name.title())
                    
                    sold_as_class = determine_sold_as(birth_year_val, sex_val, sale_year, target_filename, cov_sire_val)
                    
                    corrected_rows.append({
                        'HIP': hip_val,
                        'HORSE NAME': h_name,
                        'SEX': sex_val if sex_val != 'NAN' else "",
                        'SIRE': sire_val,
                        'DAM': dam_val,
                        'SIRE OF DAM': bms_val,
                        'YEAR OF BIRTH': birth_year_val, 
                        'FOALED': str(row.get('FOALED', row.get('STATE', ''))).strip().upper(),        
                        'SOLD AS': sold_as_class,
                        'COVERING SIRE': cov_sire_val if cov_sire_val not in ['Nan', 'None', ''] else "",
                        'NOTES': str(row.get('NOTES', '')).strip()
                    })
            
            if not corrected_rows:
                print(f"Warning: Could not parse any valid rows from '{target_filename}'. Check headers.")
                input("Press Enter to continue...")
                continue
                
            df = pd.DataFrame(corrected_rows)
            df = analyze_dataframe(df)
            
            output_filename = clean_filename_title(target_filename)
            output_csv_path = os.path.join(OUTPUT_DIR, output_filename)
            df.to_csv(output_csv_path, index=False)
            
            try:
                os.remove(input_csv_path)
            except Exception as e:
                print(f"Note: Unable to delete original source CSV: {e}")

            print(f"Successfully processed: '{target_filename}' -> '{output_filename}'")
            input("Press Enter to refresh catalog menu...")
        except Exception as err:
            print(f"Error processing file '{target_filename}': {err}")
            input("Press Enter to continue...")

def run_interactive_viewer(csv_path):
    base_df = pd.read_csv(csv_path)
    
    sale_year = extract_sale_year(os.path.basename(csv_path))
    if 'YEAR OF BIRTH' in base_df.columns and 'SEX' in base_df.columns:
        base_df['SOLD AS'] = base_df.apply(
            lambda r: determine_sold_as(r['YEAR OF BIRTH'], r['SEX'], sale_year, os.path.basename(csv_path), r.get('COVERING SIRE', '')), axis=1
        )
        
    df = analyze_dataframe(base_df)
    
    raw_stakes = hypomating_engine.load_stakes_data()
    horse_summaries = hypomating_engine.build_horse_summaries(raw_stakes)
    
    if 'HORSE NAME' not in df.columns:
        df['HORSE NAME'] = ""
        
    for idx, row in df.iterrows():
        for col_to_norm in ['HORSE NAME', 'SIRE', 'DAM', 'SIRE OF DAM', 'COVERING SIRE']:
            if col_to_norm in df.columns:
                df.at[idx, col_to_norm] = uppercase_country_suffix(df.at[idx, col_to_norm])
                
        name_val = str(row.get('HORSE NAME', '')).strip()
        if not name_val or name_val.lower() in ['nan', 'none', '']:
            by_val = str(row.get('YEAR OF BIRTH', ''))
            yr_match = re.search(r'\b\d{2}(\d{2})\b', by_val)
            yr_digits = yr_match.group(1) if yr_match else "00"
            df.at[idx, 'HORSE NAME'] = uppercase_country_suffix(f"{str(row.get('SIRE','')).title()} x {str(row.get('DAM','')).title()} '{yr_digits}")
            
    for col in df.columns:
        if col != 'HIP':
            df[col] = df[col].astype(str).replace(['nan', 'NaN', 'None'], '')
    df.fillna("", inplace=True)
    
    df['HIP'] = pd.to_numeric(df['HIP'], errors='coerce').fillna(0).astype(int)
    df.sort_values(by='HIP', inplace=True)
    df.reset_index(drop=True, inplace=True)
    df['ORIG_INDEX'] = df.index

    has_racer = 'DAM SUCCESS (RACER)' in df.columns and df['DAM SUCCESS (RACER)'].astype(str).str.strip().any()
    has_producer = 'DAM SUCCESS (PRODUCER)' in df.columns and df['DAM SUCCESS (PRODUCER)'].astype(str).str.strip().any()

    filtered_df = df.copy()
    current_idx = 0

    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        
        if len(filtered_df) == 0:
            print("\n   [No entries match the active search criteria]   \n")
        else:
            row = filtered_df.iloc[current_idx]
            
            # -------------------------------------------------------------
            # DYNAMIC PEDIGREE DISPLAY ENGINE
            # -------------------------------------------------------------
            horse_name_for_ped = str(row.get('HORSE NAME', '')).strip()
            yob = str(row.get('YEAR OF BIRTH', row.get('YOB', ''))).strip()
            year_match = re.search(r'\b(\d{4})\b', yob)
            lookup_label = f"{horse_name_for_ped} ({year_match.group(1)})" if year_match else horse_name_for_ped
            
            print("=========================================================")
            print(f"PEDIGREE FOR: {horse_name_for_ped.upper()}")
            print("=========================================================")
            
            # 1. Attempt exact match in database (prompt only when 2+ years and catalog has no YOB)
            hit = main.resolve_pedigree(lookup_label, main.PEDIGREE_DATABASE, prompt=not bool(year_match))
            ped_data = copy.deepcopy(hit["tree"]) if hit["tree"] and not hit.get("cancelled") else None
            
            # 2. Dynamic fallback for unnamed foals (e.g., SIRE x DAM 'YY)
            if not ped_data:
                sire_name = str(row.get('SIRE', '')).strip()
                dam_name = str(row.get('DAM', '')).strip()
                
                sire_node = main.pedigree_tree(sire_name, main.PEDIGREE_DATABASE) or None
                dam_node = main.pedigree_tree(dam_name, main.PEDIGREE_DATABASE) or None
                
                if sire_node or dam_node:
                    ped_data = {
                        "Horse": horse_name_for_ped.upper(),
                        "Sire": sire_node if sire_node else {"Horse": sire_name.upper()},
                        "Dam": dam_node if dam_node else {"Horse": dam_name.upper()}
                    }

            if ped_data:
                main.print_pedigree(ped_data)
                main.analyze_inbreeding(ped_data)
            else:
                print(f"There is no pedigree loaded for {horse_name_for_ped.upper()}")
            print("=========================================================\n")
            
            # -------------------------------------------------------------
            # MAIN CATALOG ENTRY TABLE DISPLAY
            # -------------------------------------------------------------
            base_cols = ["HIP", "HORSE NAME"]
            
            has_current_racing_success = 'RACING SUCCESS' in row and str(row['RACING SUCCESS']).strip() != ""
            if has_current_racing_success:
                base_cols.append("RACING SUCCESS")
                
            base_cols.extend(["SEX", "CROSS SUCCESS"])
            
            if has_racer:
                base_cols.append("DAM SUCCESS (RACER)")
            if has_producer:
                base_cols.append("DAM SUCCESS (PRODUCER)")
                
            base_cols.append("SOLD AS")
            
            row_covering_sire = str(row.get('COVERING SIRE', '')).strip()
            show_covering_sire_for_row = row_covering_sire not in ["", "nan", "NaN", "None"]
            
            if show_covering_sire_for_row:
                base_cols.append("COVERING SIRE")
                
            base_cols.extend(["YEAR OF BIRTH", "FOALED"])
            
            row_display_vals = {}
            for col in base_cols:
                val = str(row.get(col, "")).strip()
                if col == "HIP" and str(df.loc[row['ORIG_INDEX'], 'STARRED']) == "*":
                    val = f"★ {val}"
                row_display_vals[col] = val

            col_cells = {}
            for col in base_cols:
                val = row_display_vals[col]
                if col == "HORSE NAME" and len(val) > 15:
                    col_cells[col] = wrap_text_to_lines(val, 15)
                elif col == "SOLD AS" and len(val) > 10:
                    col_cells[col] = wrap_text_to_lines(val, 10)
                elif col == "COVERING SIRE" and len(val) > 15:
                    col_cells[col] = wrap_text_to_lines(val, 15)
                elif col == "CROSS SUCCESS" and len(val) > 45:
                    col_cells[col] = wrap_text_to_lines(val, 45)
                elif (col == "DAM SUCCESS (PRODUCER)" or col == "RACING SUCCESS") and len(val) > 24:
                    col_cells[col] = wrap_text_to_lines(val, 24)
                elif "SUCCESS" in col and len(val) > 28:
                    col_cells[col] = wrap_text_to_lines(val, 28)
                else:
                    col_cells[col] = [val]

            col_widths = {}
            for col in base_cols:
                max_cell_line = max(len(line) for line in col_cells[col]) if col_cells[col] else 0
                col_widths[col] = max(len(col), max_cell_line)

            total_width = sum(col_widths.values()) + (len(base_cols) * 3) + 1
            print("=" * total_width)
            print(f"VIEWING PROFILED CATALOG: {os.path.basename(csv_path).upper()}".center(total_width))
            print("=" * total_width)

            header_segments = [f" {col.strip().ljust(col_widths[col])} " for col in base_cols]
            print("|" + "|".join(header_segments) + "|")
            print("-" * total_width)
            
            max_lines = max(len(lines) for lines in col_cells.values())
            for line_i in range(max_lines):
                row_segments = []
                for col in base_cols:
                    lines = col_cells[col]
                    cell_text = lines[line_i].strip() if line_i < len(lines) else ""
                    row_segments.append(f" {cell_text.ljust(col_widths[col])} ")
                print("|" + "|".join(row_segments) + "|")
                
            # -------------------------------------------------------------
            # FEMALE FAMILY SECTION DISPLAY
            # -------------------------------------------------------------
            if ped_data:
                print_female_family_section(ped_data, raw_stakes, horse_summaries, total_width)
            else:
                print("-" * total_width)

            # -------------------------------------------------------------
            # NOTES SECTION DISPLAY
            # -------------------------------------------------------------
            current_orig_idx = row['ORIG_INDEX']
            current_notes = df.loc[current_orig_idx, 'NOTES']
            print_notes_section(current_notes, total_width)

            print(f"Viewing Entry {current_idx + 1} of {len(filtered_df)} items (Total Count: {len(df)})".center(total_width))

        print("\n[N]ext | [P]revious | [J]ump to | [*] Star/Unstar | [E]dit Notes | [F]ilter | [R]eset Filters | [Q]uit to Catalog Menu")
        choice = input("Select an option: ").strip().lower()

        if choice == 'q':
            df.drop(columns=['ORIG_INDEX'], errors='ignore').to_csv(csv_path, index=False)
            break
        elif choice == 'n' and current_idx < len(filtered_df) - 1:
            current_idx += 1
        elif choice == 'p' and current_idx > 0:
            current_idx -= 1
        elif choice == 'j':
            jump_input = input("Jump to Hip: ").strip()
            if jump_input:
                if re.match(r'^[+-]\d+$', jump_input):
                    offset = int(jump_input)
                    current_idx = max(0, min(len(filtered_df) - 1, current_idx + offset))
                else:
                    clean_hip = re.sub(r'\D', '', jump_input)
                    if clean_hip:
                        found = filtered_df[filtered_df['HIP'].astype(str) == clean_hip]
                        if not found.empty:
                            current_idx = filtered_df.index.get_loc(found.index[0])
        elif choice == '*':
            if len(filtered_df) > 0:
                orig_idx = filtered_df.iloc[current_idx]['ORIG_INDEX']
                df.loc[orig_idx, 'STARRED'] = "" if str(df.loc[orig_idx, 'STARRED']) == "*" else "*"
                df.drop(columns=['ORIG_INDEX'], errors='ignore').to_csv(csv_path, index=False)
        elif choice == 'e':
            if len(filtered_df) > 0:
                orig_idx = filtered_df.iloc[current_idx]['ORIG_INDEX']
                existing_notes = str(df.loc[orig_idx, 'NOTES'])
                print(f"\nCurrent Notes: {existing_notes if existing_notes else '[None]'}")
                new_note = input("Enter new notes (or press Enter to keep current): ").strip()
                if new_note:
                    df.loc[orig_idx, 'NOTES'] = new_note
                    filtered_df.loc[current_idx, 'NOTES'] = new_note
                    df.drop(columns=['ORIG_INDEX'], errors='ignore').to_csv(csv_path, index=False)
        elif choice == 'r':
            filtered_df = df.copy()
            current_idx = 0
        elif choice == 'f':
            print("\n[1] Sex | [2] Sale Type | [3] Stallion Name | [4] State Bred (Foaled) | [5] Stars Only")
            f_choice = input("Select filter method: ").strip()
            if f_choice == "1":
                sex_in = input("Enter Sex (C/F): ").strip().upper()
                if sex_in and 'SEX' in filtered_df.columns:
                    filtered_df = filtered_df[filtered_df['SEX'].astype(str).str.upper().str.startswith(sex_in[0])]
                    current_idx = 0
            elif f_choice == "2":
                t_in = input("Enter keywords (e.g., Broodmare, Prospect, Colt): ").strip().upper()
                if t_in:
                    filtered_df = filtered_df[filtered_df['SOLD AS'].astype(str).str.upper().str.contains(t_in, na=False)]
                    current_idx = 0
            elif f_choice == "3":
                st_name = input("Enter Stallion Name: ").strip().upper()
                if st_name:
                    filtered_df = filtered_df[filtered_df['SIRE'].astype(str).str.upper() == st_name]
                    current_idx = 0
            elif f_choice == "4":
                state_in = input("Enter State Code (e.g. KY, NY) or Name (e.g. Kentucky): ").strip().upper()
                target_state = STATE_MAP.get(state_in, state_in)
                if target_state:
                    filtered_df = filtered_df[filtered_df['FOALED'].astype(str).str.upper() == target_state]
                    current_idx = 0
            elif f_choice == "5":
                filtered_df = filtered_df[filtered_df['STARRED'].astype(str) == "*"]
                current_idx = 0

def run_sales_menu():
    main_entry()

def main_entry():
    while True:
        process_new_sales()
        
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        analyzed_files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.csv')]
        
        os.system('cls' if os.name == 'nt' else 'clear')
        print("=========================================")
        print("         AVAILABLE ANALYZED SALES        ")
        print("=========================================")
        
        if not analyzed_files:
            print(" [No records found inside Analyzed Sales] ")
            print("=========================================")
            input("\nPress Enter to return to main menu...")
            break
            
        for idx, filename in enumerate(analyzed_files, 1):
            clean_name = filename.replace("analyzed_", "").replace(".csv", "").replace("_", " ").upper()
            print(f" [{idx}] {clean_name}")
            
        print(" [X] Return to Menu")
        print("=========================================")
        
        sel = input("Select an analyzed catalog to open: ").strip().lower()
        if sel == 'x':
            break
            
        try:
            choice_idx = int(sel) - 1
            if 0 <= choice_idx < len(analyzed_files):
                run_interactive_viewer(os.path.join(OUTPUT_DIR, analyzed_files[choice_idx]))
        except ValueError:
            pass

if __name__ == "__main__":
    main_entry()