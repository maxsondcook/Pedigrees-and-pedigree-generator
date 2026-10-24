from pathlib import Path
import csv
import re

# Fallback directories to search for CSV files
SEARCH_DIRS = [Path("sales_data"), Path(".")]

# Month sorting weights to guarantee strict January to December chronological order
MONTH_ORDER = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12
}

def safe_str(val):
    """Safely converts any row object value to a string to prevent NoneType attribute crashes."""
    if val is None:
        return ""
    return str(val).strip()

def clean_title(filename):
    """Converts file names to clean titles."""
    name = filename.replace(".csv", "").replace("_", " ")
    name = re.sub(r'\d{4}', '', name)
    name = name.replace("()", "").replace("[]", "").replace("-", " ")
    return " ".join(name.split()).title()

def get_sale_month_index(sale_title):
    """Inspects a sale catalog title and maps its approximate month weight."""
    title_lower = sale_title.lower()
    for month_name, index in MONTH_ORDER.items():
        if month_name in title_lower:
            return index
    return 13 

def scan_sales_files():
    """Scans folders for valid CSV catalogs."""
    database = {}
    for target_dir in SEARCH_DIRS:
        if not target_dir.exists() or not target_dir.is_dir():
            continue
        for file_path in target_dir.glob("*.csv"):
            filename = file_path.name
            if filename.startswith("catalog-") and "_" in filename:
                continue
            year_match = re.search(r'\d{4}', filename)
            if year_match:
                year = year_match.group(0)
                title = clean_title(filename)
                if not title:
                    title = "Unknown Catalog Sale"
                if year not in database:
                    database[year] = {}
                if title not in database[year]:
                    database[year][title] = file_path
    return database

def parse_price(val):
    """Cleans up raw prices into floats for accurate sorting."""
    val_str = safe_str(val).upper()
    if not val_str or "OUT" in val_str or val_str == "-2.00":
        return 0.0
    
    cleaned = "".join(c for c in val_str if c.isdigit() or c == '.')
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0

def clean_search_string(text):
    """Normalizes names and entries cleanly for precise lookup matching."""
    cleaned = re.sub(r'\(.*?\)', '', safe_str(text))
    return " ".join(cleaned.lower().split()).strip()

def load_and_process_csv(file_path: Path, gender_filter=None, sort_choice="3", horse_search=None, sire_search=None, dam_search=None, birth_year_search=None):
    """Reads CSV, parses dynamic headers, and applies filters safely across Keeneland and Fasig-Tipton structures."""
    results = []
    
    catalog_year_match = re.search(r'\d{4}', file_path.name)
    catalog_year = int(catalog_year_match.group(0)) if catalog_year_match else None
    file_name_lower = file_path.name.lower()

    try:
        with open(file_path, mode="r", encoding="utf-8-sig", errors="ignore") as f:
            sample = f.read(2048)
            dialect = csv.excel
            try:
                if csv.Sniffer().has_header(sample):
                    dialect = csv.excel
            except Exception:
                pass
            if '\t' in sample: 
                dialect = csv.excel_tab
                
            f.seek(0)
            
            reader = csv.DictReader(f, dialect=dialect)
            headers = {k.lower().strip(): k for k in reader.fieldnames} if reader.fieldnames else {}
            
            hip_key = next((headers[k] for k in ['hip number', 'hip', 'hip_no'] if k in headers), None)
            name_key = next((headers[k] for k in ['horse', 'horse name', 'name', 'description'] if k in headers), None)
            sex_key = next((headers[k] for k in ['sex', 'gender'] if k in headers), None)
            price_key = next((headers[k] for k in ['sale price', 'price', 'final bid', 'price_raw'] if k in headers), None)
            purchaser_key = next((headers[k] for k in ['purchaser', 'buyer', 'buyer name'] if k in headers), None)
            sire_key = next((headers[k] for k in ['sire'] if k in headers), None)
            dam_key = next((headers[k] for k in ['dam'] if k in headers), None)
            dob_key = next((headers[k] for k in ['year of birth', 'birth year', 'dob', 'date of birth'] if k in headers), None)
            color_key = next((headers[k] for k in ['color', 'colour'] if k in headers), None)
            consign_key = next((headers[k] for k in ['property line', 'consignor', 'consigned by', 'seller'] if k in headers), None)
            damsire_key = next((headers[k] for k in ['sire of dam', 'damsire', 'broodmare sire'] if k in headers), None)
            barn_key = next((headers[k] for k in ['barn'] if k in headers), None)
            foaled_loc_key = next((headers[k] for k in ['foaled'] if k in headers), None)

            is_fasig = "fasig" in file_name_lower or "sale title" in headers

            for row in reader:
                if not any(row.values()):
                    continue
                
                raw_sire = safe_str(row.get(sire_key, "")).strip() if sire_key else ""
                raw_dam = safe_str(row.get(dam_key, "")).strip() if dam_key else ""
                raw_sex = safe_str(row.get(sex_key, "")).strip().upper() if sex_key else ""
                hip_val = safe_str(row.get(hip_key, "N/A")).strip() if hip_key else "N/A"
                if hip_val.isdigit():
                    hip_val = hip_val.zfill(4)
                
                raw_dob = safe_str(row.get(dob_key, "")).strip() if dob_key else ""
                extracted_birth_year = ""
                if raw_dob and any(c.isdigit() for c in raw_dob):
                    year_match = re.search(r'\d{4}', raw_dob)
                    if year_match:
                        extracted_birth_year = year_match.group(0)
                
                if not extracted_birth_year and catalog_year:
                    if "yearling" in file_name_lower:
                        extracted_birth_year = str(catalog_year - 1)
                    elif "2yo" in file_name_lower or "2 year" in file_name_lower or "two-year" in file_name_lower:
                        extracted_birth_year = str(catalog_year - 2)
                    elif "weanling" in file_name_lower:
                        extracted_birth_year = str(catalog_year)
                    else:
                        sex_upper = raw_sex.upper()
                        if "WEANLING" in sex_upper:
                            extracted_birth_year = str(catalog_year)
                        elif "YEARLING" in sex_upper:
                            extracted_birth_year = str(catalog_year - 1)
                        elif "2YO" in sex_upper or "TWO-YEAR-OLD" in sex_upper:
                            extracted_birth_year = str(catalog_year - 2)
                        else:
                            extracted_birth_year = str(catalog_year - 1)

                raw_name = safe_str(row.get(name_key, "")).strip() if name_key else ""
                
                if not raw_name or is_fasig or re.match(r'^hip\s*\d+', raw_name.lower()):
                    short_yr = extracted_birth_year[-2:] if extracted_birth_year else ""
                    raw_name = f"{raw_sire} x {raw_dam} '{short_yr}".strip()

                if "-" in raw_name and (not raw_sire or raw_sire == "Unknown"):
                    parts = raw_name.split("-", 1)
                    raw_sire = parts[0].strip()
                    remainder = parts[1].strip()
                    if "," in remainder:
                        dam_part, sex_part = remainder.split(",", 1)
                        remainder = dam_part.strip()
                    raw_dam = remainder

                if not raw_sire: raw_sire = "Unknown"
                if not raw_dam: raw_dam = "Unknown"
                if not raw_sex: raw_sex = "Unknown"
                
                match_found = False
                clean_name_field = clean_search_string(raw_name)
                clean_sire_field = clean_search_string(raw_sire)
                clean_dam_field = clean_search_string(raw_dam)

                if horse_search and horse_search == clean_name_field:
                    match_found = True
                
                if sire_search and dam_search:
                    if sire_search == clean_sire_field and dam_search == clean_dam_field:
                        match_found = True
                elif sire_search and not dam_search:
                    if sire_search in clean_sire_field: 
                        match_found = True
                elif dam_search and not sire_search:
                    if dam_search in clean_dam_field:
                        match_found = True

                if (horse_search or sire_search or dam_search) and not match_found:
                    continue

                if birth_year_search and extracted_birth_year and birth_year_search != extracted_birth_year:
                    continue
                    
                sex_letter = raw_sex[0] if raw_sex else "U"
                if "GELDING" in raw_sex: sex_letter = "G"
                elif "MARE" in raw_sex: sex_letter = "M"
                elif "HORSE" in raw_sex: sex_letter = "H"
                elif "COLT" in raw_sex: sex_letter = "C"
                elif "FILLY" in raw_sex: sex_letter = "F"
                elif "RIDGLING" in raw_sex: sex_letter = "R"
                elif "WEANLING" in raw_sex: sex_letter = "W"
                
                raw_price = safe_str(row.get(price_key, "0")) if price_key else "0"
                raw_purchaser = safe_str(row.get(purchaser_key, "")).strip().upper() if purchaser_key else ""
                raw_price_upper = raw_price.upper()

                # Determine status flags
                is_out = "OUT" in raw_purchaser or "OUT" in raw_price_upper
                is_rna = ("NOT SOLD" in raw_purchaser or "RNA" in raw_purchaser or 
                          "R.N.A." in raw_purchaser or "RNA" in raw_price_upper or 
                          "R.N.A." in raw_price_upper or raw_price.strip() == "-2.00")
                
                numeric_price = parse_price(raw_price)
                
                if is_out:
                    clean_disp_price = "WITHDRAWN"
                    numeric_price = 0.0
                elif is_rna:
                    clean_disp_price = f"RNA (${int(numeric_price):,})" if numeric_price > 0 else "RNA"
                elif numeric_price == 0:
                    clean_disp_price = "N/A"
                else:
                    clean_disp_price = f"${int(numeric_price):,}"

                results.append({
                    'hip': hip_val,
                    'name': raw_name,
                    'sex': raw_sex,
                    'sex_letter': sex_letter,
                    'sire': raw_sire,
                    'dam': raw_dam,
                    'damsire': safe_str(row.get(damsire_key, "")).strip() if damsire_key else "",
                    'color': safe_str(row.get(color_key, "")).strip().upper() if color_key else "",
                    'consignor': safe_str(row.get(consign_key, "")).strip() if consign_key else "",
                    'purchaser': raw_purchaser,
                    'barn': safe_str(row.get(barn_key, "")).strip() if barn_key else "",
                    'foaled_location': safe_str(row.get(foaled_loc_key, "")).strip() if foaled_loc_key else "",
                    'birth_year': extracted_birth_year,
                    'price_raw': clean_disp_price,
                    'price_num': numeric_price,
                    'is_rna': is_rna,
                    'is_out': is_out,
                    'is_fasig': is_fasig
                })
    except FileNotFoundError:
        return []
        
    return results

def compute_sales_metrics(dataset):
    """JSON-serializable sales metrics for a list of lot records."""
    offered = [r for r in dataset if not r.get('is_out', False)]
    sold_records = [r for r in offered if not r.get('is_rna', False) and r.get('price_num', 0) > 0]
    rna_records = [r for r in offered if r.get('is_rna', False)]
    valid_sales = [r['price_num'] for r in sold_records]
    total_offered = len(offered)
    total_sold = len(valid_sales)
    rna_count = len(rna_records)
    gross = sum(valid_sales)
    avg = gross / total_sold if total_sold > 0 else 0
    sorted_sales = sorted(valid_sales)
    n = len(sorted_sales)
    if n == 0:
        median = 0
    elif n % 2 == 1:
        median = sorted_sales[n // 2]
    else:
        median = (sorted_sales[(n // 2) - 1] + sorted_sales[n // 2]) / 2.0
    sold_pct = (total_sold / total_offered * 100) if total_offered > 0 else 0
    million_plus = sum(1 for p in valid_sales if p >= 1000000)
    return {
        'horses': str(total_offered),
        'gross': f"${int(gross):,}",
        'avg': f"${int(avg):,}",
        'median': f"${int(median):,}",
        'sold_pct': f"{sold_pct:.1f}%",
        'rna': str(rna_count),
        'mil': str(million_plus),
        'horses_num': total_offered,
        'gross_num': gross,
        'avg_num': avg,
        'median_num': median,
        'sold_pct_num': sold_pct,
        'rna_num': rna_count,
        'mil_num': million_plus,
    }


def calculate_sales_stats(records, target_stallion=None):
    """Returns lifetime (and last-5-year when applicable) stats without printing."""
    if not records:
        return None
    sale_years = sorted(list(set(int(r['year']) for r in records if r.get('year') and str(r['year']).isdigit())))
    split_view = target_stallion is not None and len(sale_years) > 5
    last_5_years_cutoff = max(sale_years) - 4 if sale_years else 0
    if split_view:
        recent_dataset = [
            r for r in records
            if r.get('year') and str(r['year']).isdigit() and int(r['year']) >= last_5_years_cutoff
        ]
        return {
            "split": True,
            "lifetime": compute_sales_metrics(records),
            "last_5_years": compute_sales_metrics(recent_dataset),
            "last_5_cutoff": last_5_years_cutoff,
        }
    return {"split": False, "lifetime": compute_sales_metrics(records)}


def calculate_and_print_stats(records, target_stallion=None):
    """Calculates sales summary statistics and displays them cleanly above results."""
    if not records:
        return

    sale_years = sorted(list(set(int(r['year']) for r in records if r.get('year') and str(r['year']).isdigit())))
    split_view = target_stallion is not None and len(sale_years) > 5
    last_5_years_cutoff = max(sale_years) - 4 if sale_years else 0

    def compute_metrics(dataset):
        return compute_sales_metrics(dataset)

    print("\n=======================================================")
    print("                  SALES PERFORMANCE SUMMARY            ")
    print("=======================================================")

    if split_view:
        lifetime_dataset = records
        recent_dataset = [r for r in records if r.get('year') and str(r['year']).isdigit() and int(r['year']) >= last_5_years_cutoff]
        
        lt = compute_metrics(lifetime_dataset)
        rc = compute_metrics(recent_dataset)
        
        print(f"{'Metric':<25} | {'Lifetime':<14} | {f'Last 5 Yrs':<14}")
        print("-" * 60)
        print(f"{'Total Horses:':<25} | {lt['horses']:<14} | {rc['horses']:<14}")
        print(f"{'Gross:':<25} | {lt['gross']:<14} | {rc['gross']:<14}")
        print(f"{'Average:':<25} | {lt['avg']:<14} | {rc['avg']:<14}")
        print(f"{'Median:':<25} | {lt['median']:<14} | {rc['median']:<14}")
        print(f"{'Sold %:':<25} | {lt['sold_pct']:<14} | {rc['sold_pct']:<14}")
        print(f"{'# of RNA/Not Sold:':<25} | {lt['rna']:<14} | {rc['rna']:<14}")
        print(f"{'>= $1,000,000:':<25} | {lt['mil']:<14} | {rc['mil']:<14}")
    else:
        stats = compute_metrics(records)
        print(f"{'Total Horses:':<25} {stats['horses']}")
        print(f"{'Gross:':<25} {stats['gross']}")
        print(f"{'Average:':<25} {stats['avg']}")
        print(f"{'Median:':<25} {stats['median']}")
        print(f"{'Sold %:':<25} {stats['sold_pct']}")
        print(f"{'# of RNA/Not Sold:':<25} {stats['rna']}")
        print(f"{'>= $1,000,000:':<25} {stats['mil']}")
        
    print("=======================================================\n")

def display_paginated_records(records, show_sale_name=False, is_catalog_view=False):
    """Prints records cleanly with padded alignment and tabular headers."""
    chunk_size = 40
    i = 0
    current_records = list(records)

    while i < len(current_records):
        chunk = current_records[i:i+chunk_size]
        print(f"\n--- Results {i+1} to {min(i+chunk_size, len(current_records))} of {len(current_records)} ---")
        
        if show_sale_name:
            print(f"{'Year':<5} | {'Sale Catalog Title':<45} | {'Hip':<8} | {'Horse Name':<38} | {'Sex':<4} | {'Price':>16}")
            print("-" * 127)
        else:
            if chunk and chunk[0].get('is_fasig'):
                print(f"{'Hip':<8} | {'Horse Name':<45} | {'Sex':<4} | {'Price':>16}")
                print("-" * 79)
            else:
                print(f"{'Hip':<8} | {'Horse Name':<38} | {'Sex':<4} | {'Sire':<20} | {'Price':>16}")
                print("-" * 95)
        
        for r in chunk:
            price_display = r['price_raw']
            
            yr = str(r.get('year', 'N/A'))[:4]
            sale_title = str(r.get('sale', 'Sale'))
            if len(sale_title) > 45:
                sale_title = sale_title[:42] + "..."
            
            hip_str = f"Hip {r['hip']}" if not str(r['hip']).startswith("Hip") else str(r['hip'])
            horse_name = str(r['name'])
            if len(horse_name) > 38:
                horse_name = horse_name[:35] + "..."
                
            sire_name = str(r.get('sire', ''))
            if len(sire_name) > 20:
                sire_name = sire_name[:17] + "..."

            if show_sale_name:
                print(f"{yr:<5} | {sale_title:<45} | {hip_str:<8} | {horse_name:<38} | {r['sex_letter']:<4} | {price_display:>16}")
            else:
                if r.get('is_fasig'):
                    print(f"{hip_str:<8} | {horse_name:<45} | {r['sex_letter']:<4} | {price_display:>16}")
                else:
                    print(f"{hip_str:<8} | {horse_name:<38} | {r['sex_letter']:<4} | {sire_name:<20} | {price_display:>16}")
        
        prompt_menu = "\n[N] Next page | [b] Back page | [s] Sort/Filter options | [q] Stop: "
        cont = input(prompt_menu).strip().lower()
        
        if cont == 'q':
            break
        elif cont == 'b':
            if i >= chunk_size: 
                i -= chunk_size
        elif cont == 's':
            print("\n--- Sort & Filter Options ---")
            print("[1] Sort by Price: Highest to Lowest")
            print("[2] Sort by Price: Lowest to Highest")
            print("[3] Sort by Date/Year: Most Recent to Oldest")
            print("[4] Sort by Date/Year: Oldest to Most Recent")
            print("[5] Filter by Sex")
            print("[6] Filter by Stallion Name")
            choice = input("Select Action: ").strip()
            
            if choice == "1":
                current_records.sort(key=lambda x: x['price_num'], reverse=True)
                i = 0
            elif choice == "2":
                current_records.sort(key=lambda x: x['price_num'])
                i = 0
            elif choice == "3":
                if show_sale_name:
                    current_records.sort(key=lambda x: (int(x.get('year', 0)), x.get('month_index', 0)), reverse=True)
                else:
                    current_records.sort(key=lambda x: x['hip'], reverse=True)
                i = 0
            elif choice == "4":
                if show_sale_name:
                    current_records.sort(key=lambda x: (int(x.get('year', 0)), x.get('month_index', 0)))
                else:
                    current_records.sort(key=lambda x: x['hip'])
                i = 0
            elif choice == "5":
                s_filter = input("Enter sex letter filter (F=Filly, M=Mare, H=Horse, C=Colt, R=Ridgling, W=Weanling, G=Gelding): ").strip().upper()
                if s_filter:
                    current_records = [r for r in records if r['sex_letter'] == s_filter]
                    i = 0
            elif choice == "6":
                sire_input = input("Enter Stallion Name: ").strip()
                clean_sire = clean_search_string(sire_input)
                if clean_sire:
                    current_records = [r for r in current_records if clean_sire in clean_search_string(r.get('sire', ''))]
                    i = 0
                    if not current_records:
                        print(f"⚠️ No matches found for stallion '{sire_input}'. Resetting view.")
                        current_records = list(records)
        elif cont == 'n' or cont == '':  # Accepts 'n' or pressing Enter
            if i + chunk_size < len(current_records): 
                i += chunk_size
            else: 
                break

def execute_global_search(db, query=None, search_type="horse", profile_dict=None, sort_descending=True):
    """Scans all database files and runs comparative matches safely."""
    print(f"\n🔍 Searching sales archives... Please wait...")
    all_matches = []
    
    h_q = clean_search_string(profile_dict.get('name')) if profile_dict and profile_dict.get('name') else (clean_search_string(query) if search_type == "horse" else None)
    s_q = clean_search_string(profile_dict.get('sire')) if profile_dict and profile_dict.get('sire') else (clean_search_string(query) if search_type == "sire" else None)
    d_q = clean_search_string(profile_dict.get('dam')) if profile_dict and profile_dict.get('dam') else None
    b_q = safe_str(profile_dict.get('year')).strip() if profile_dict and profile_dict.get('year') else None

    for year, sales_map in db.items():
        for sale_title, file_path in sales_map.items():
            found = load_and_process_csv(
                file_path, 
                horse_search=h_q, 
                sire_search=s_q, 
                dam_search=d_q, 
                birth_year_search=b_q
            )
            for record in found:
                record['year'] = year
                record['sale'] = sale_title
                record['month_index'] = get_sale_month_index(sale_title)
                all_matches.append(record)
                
    if not all_matches:
        print(f"\n⚠️ No matching public records found across database criteria.")
        return
        
    all_matches.sort(key=lambda x: (int(x.get('year', 0)), x.get('month_index', 0)), reverse=sort_descending)
    
    stallion_key = query if search_type == "sire" else None
    calculate_and_print_stats(all_matches, target_stallion=stallion_key)
    
    display_paginated_records(all_matches, show_sale_name=True, is_catalog_view=False)

def run_sales_menu(pedigrees_database=None):
    """Main menu loop with smart autofill integration from pedigree structures."""
    while True:
        db = scan_sales_files()
        if not db:
            print("\n❌ No sales data files found.")
            return

        print("\n==================================")
        print("          Sales History           ")
        print("==================================")
        print("[1] Search by Year Catalog")
        print("[2] Search Stallion Progeny Entries")
        print("[3] Search Horse Sale History (Profile)")
        print("[4] Launch Pre-Sale Catalog Analyzer")
        print("[5] Market Health Dashboard (SQL Graphs)")
        print("[6] Price Projection (Yearlings / Weanlings vs Stud Fee)")
        print("----------------------------------")
        print("[X] Return to Main Menu")
        
        main_choice = input("\nSelect Option: ").strip()
        if main_choice.upper() == "X" or not main_choice:
            break
            
        if main_choice == "1":
            sorted_years = sorted(list(db.keys()), reverse=True)
            print("\n==================================")
            print("          Select Sale Year        ")
            print("==================================")
            shorthand_map = {y[2:]: y for y in sorted_years}
            for code, yr in shorthand_map.items():
                print(f"[{code}] {yr}")
            year_choice = input("\nSelect Year Shortcode: ").strip()
            if year_choice in shorthand_map:
                selected_year = shorthand_map[year_choice]
                sales_map = db[selected_year]
                sorted_sales_titles = sorted(list(sales_map.keys()), key=lambda t: get_sale_month_index(t))
                print(f"\nSales in {selected_year}:")
                for idx, title in enumerate(sorted_sales_titles, 1):
                    print(f"[{idx}] {title}")
                sale_choice = input("\nSelect Catalog Index: ").strip()
                if sale_choice.isdigit() and int(sale_choice) <= len(sorted_sales_titles):
                    selected_title = sorted_sales_titles[int(sale_choice)-1]
                    
                    records = load_and_process_csv(sales_map[selected_title])
                    for r in records:
                        r['year'] = selected_year
                    
                    calculate_and_print_stats(records)
                    display_paginated_records(records, show_sale_name=False, is_catalog_view=True)

        elif main_choice == "2":
            q = input("\nEnter Stallion Name: ").strip()
            if q:
                execute_global_search(db, query=q, search_type="sire", sort_descending=True)

        elif main_choice == "3":
            print("\n--- Targeted Horse Search Setup ---")
            p_name = input("Horse Name       : ").strip()
            p_year = input("Foaling Year     : ").strip()
            
            p_sire = ""
            p_dam = ""
            has_autofill = False
            
            if p_name and pedigrees_database:
                lookup_label = f"{p_name} ({p_year})" if p_year else p_name
                hit = None
                try:
                    import main as _main
                    hit = _main.resolve_pedigree(lookup_label, pedigrees_database, prompt=not bool(p_year))
                except Exception:
                    hit = None
                match_data = hit["tree"] if hit and hit.get("tree") and not hit.get("cancelled") else None
                if not match_data:
                    base_key = p_name.upper()
                    year_suffix = f"({p_year})" if p_year else ""
                    if base_key in pedigrees_database:
                        match_data = pedigrees_database[base_key]
                    elif year_suffix:
                        combined_key = f"{base_key} {year_suffix}".strip()
                        if combined_key in pedigrees_database:
                            match_data = pedigrees_database[combined_key]
                
                if match_data:
                    if isinstance(match_data, dict):
                        sire_node = match_data.get('Sire', match_data.get('sire', ''))
                        p_sire = sire_node.get('Horse', '') if isinstance(sire_node, dict) else str(sire_node)
                        p_sire = re.sub(r'\s*\(\d{4}\)', '', p_sire).strip()
                        
                        dam_node = match_data.get('Dam', match_data.get('dam', ''))
                        p_dam = dam_node.get('Horse', '') if isinstance(dam_node, dict) else str(dam_node)
                        p_dam = re.sub(r'\s*\(\d{4}\)', '', p_dam).strip()
                    
                    if p_sire or p_dam:
                        print(f"Sire Name        : {p_sire} (Autofilled)")
                        print(f"Dam Name         : {p_dam} (Autofilled)")
                        has_autofill = True
            
            if not has_autofill:
                p_sire = input("Sire Name        : ").strip()
                p_dam = input("Dam Name         : ").strip()
            
            profile = {'name': p_name, 'year': p_year, 'sire': p_sire, 'dam': p_dam}
            if any(profile.values()):
                execute_global_search(db, search_type="profile", profile_dict=profile)
            else:
                print("⚠️ Search cancelled. All fields empty.")
        elif main_choice == '4':
            try:
                import sale_analyzer
                import importlib
                importlib.reload(sale_analyzer)
                sale_analyzer.main_entry()
            except Exception as e:
                print(f"❌ Error running Sale Analyzer: {e}")
                input("\nPress Enter to return...")
        elif main_choice == "5":
            try:
                import sales_health
                import importlib
                importlib.reload(sales_health)
                sales_health.display_sales_health_dashboard()
            except Exception as e:
                print(f"❌ Error rendering sales health dashboard: {e}")
                input("\nPress Enter to return...")
        elif main_choice == "6":
            try:
                import PriceProjection
                import importlib
                importlib.reload(PriceProjection)
                PriceProjection.run_price_projection_menu()
            except Exception as e:
                print(f"❌ Error running Price Projection: {e}")
                input("\nPress Enter to return...")

if __name__ == "__main__":
    run_sales_menu()
