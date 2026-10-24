"""
Stallion Analytics and Ranking Engine - Core Database Synced
"""
import re
import sys

# Explicitly import local database modules
import placeholder_store
import broodmare_sire_data
import main  # Assumes main.py handles the master layout printing and pedigree tools


def _stallion_profiles():
    """Stallion cards from placeholderdatabase/stallion_stats.csv only."""
    return placeholder_store.load_stallion_profiles()


# Prescribed 1-to-1 ordering of sire ranks matching the master spreadsheet exactly
RAW_RANKING_ORDER = [
    "Not This Time",       # 1
    "Into Mischief",       # 2
    "Gun Runner",          # 3
    "Nyquist",             # 4
    "Curlin",              # 5
    "Constitution",        # 6
    "Practical Joke",      # 7
    "Munnings",            # 8
    "Liam's Map",          # 9
    "Uncle Mo",            # 10
    "Vekoma",              # 11
    "American Pharoah",    # 12
    "Tiz the Law",         # 13
    "Omaha Beach",         # 14
    "Maclean's Music",     # 15
    "Twirling Candy",      # 16
    "Justify",             # 17
    "Quality Road",        # 18
    "Mendelssohn",         # 19
    "Candy Ride (ARG)",    # 20
    "Oscar Performance",   # 21
    "Connect",             # 22
    "Hard Spun",           # 23
    "Bolt d'Oro",          # 24
    "Vino Rosso",          # 25
    "Speightstown",        # 26
    "Medaglia d'Oro",      # 27
    "Goldencents",         # 28
    "City of Light",       # 29
    "Mitole",              # 30
    "Frosted",             # 31
    "Street Sense",        # 32
    "Audible",             # 33
    "Volatile",            # 34
    "Authentic",           # 35
    "Mo Town",             # 36
    "Cairo Prince",        # 37
    "Yaupon",              # 38
    "Flameaway",           # 39
    "Honor A. P.",         # 40
    "Violence",            # 41
    "Collected",           # 42
    "Midshipman",          # 43
    "Ghostzapper",         # 44
    "Kantharos",           # 45
    "Exaggerator",         # 46
    "Tapit",               # 47
    "McKinzie",            # 48
    "Dialed In",           # 49
    "Tapiture",            # 50
    "Upstart",             # 51
    "Good Magic",          # 52
    "Maximus Mischief",    # 53
    "Essential Quality",   # 54
    "Charlatan",           # 55
    "Girvin",              # 56
    "The Big Beast",       # 57
    "Solomini",            # 58
    "Union Rags",          # 59
    "Blame",               # 60
    "Instagrand",          # 61
    "Runhappy",            # 62
    "Army Mule",           # 63
    "Maxfield",            # 64
    "Cloud Computing",     # 65
    "Bucchero",            # 66
    "The Factor",          # 67
    "More Than Ready",     # 68
    "Stay Thirsty",        # 69
    "Complexity",          # 70
    "Jimmy Creed",         # 71
    "Tacitus",             # 72
    "Great Notion",        # 73
    "Grazen",              # 74
    "Cupid",               # 75
    "Star Guitar",         # 76
    "Khozan",              # 77
    "Clubhouse Ride",      # 78
    "Awesome Slew",        # 79
    "War of Will",         # 80
    "Tonalist",            # 81
    "War Front",           # 82
    "Kitten's Joy",        # 83
    "Neolithic",           # 84
    "Take Charge Indy",    # 85
    "Golden Lad",          # 86
    "Blofeld",             # 87
    "Karakontie (JPN)",    # 88
    "Rock Your World",     # 89
    "Central Banker",      # 90
    "Enticed",             # 91
    "Beau Liam",           # 92
    "Paynter",             # 93
    "Aurelius Maximus",    # 94
    "Sergei Prokofiev",    # 95
    "Spun to Run",         # 96
    "Sir Prancealot (IRE)",# 97
    "Unified",             # 98
    "Adios Charlie",       # 99
    "Maximum Security",    # 100
    "Summer Front",        # 101
    "Independence Hall",   # 102
    "West Coast",          # 103
    "Accelerate",          # 104
    "Preservationist",     # 105
    "Echo Town",           # 106
    "Warrior's Reward",    # 107
    "Speightster",         # 108
    "American Freedom",    # 109
    "Uncle Lino",          # 110
    "Smiling Tiger",       # 111
    "Thousand Words",      # 112
    "Game Winner",         # 113
    "Improbable",          # 114
    "Coal Front",          # 115
    "Distorted Humor",     # 116
    "Mastery",             # 117
    "Outwork",             # 118
    "Mucho Macho Man",     # 119
    "Cajun Breeze",        # 120
    "Modernist",           # 121
    "Tapwrit",             # 122
    "Gormley",             # 123
    "Always Dreaming",     # 124
    "Om",                  # 125
    "Honest Mischief",     # 126
    "Keen Ice",            # 127
    "Good Samaritan",      # 128
    "Marking",             # 129
    "Stanford",            # 130
    "Pavel",               # 131
    "Flat Out",            # 132
    "Cinco Charlie",       # 133
    "Valiant Minister",    # 134
    "Souper Speedy",       # 135
    "Win Win Win",         # 136
    "Hoppertunity",        # 137
    "El Deal",             # 138
    "Divining Rod",        # 139
    "Cross Traffic",       # 140
    "Street Strategy",     # 141
    "Caracaro",            # 142
    "Weigelia",            # 143
    "Tom's d'Etat",        # 144
    "Catholic Boy",        # 145
    "Temple City",         # 146
    "Competitive Edge",    # 147
    "I'll Have Another",   # 148
    "Midnight Lute",       # 149
    "Lexitonian"           # 150
]

def view_stallion_profile_by_rank(rank_num):
    """Looks up a stallion's name by rank and displays its detailed profile layout card."""
    idx = rank_num - 1
    if idx < 0 or idx >= len(RAW_RANKING_ORDER):
        print("\n❌ Invalid rank number selected.")
        return

    sire_name = RAW_RANKING_ORDER[idx]
    all_profiles = _stallion_profiles()
    main.display_stallion_profile(sire_name, all_profiles)
    input("\nPress Enter to return to rankings...")

def print_stallions_range(start, end):
    """Prints stallion rankings grid columns cleanly."""
    print(f"\n{'Rank':<6} {'Sire Name':<30} | {'Rank':<6} {'Sire Name':<30}")
    print("-" * 75)
    for i in range(start, end + 1, 2):
        idx1 = i - 1
        idx2 = i
        name1 = RAW_RANKING_ORDER[idx1] if idx1 < len(RAW_RANKING_ORDER) else ""
        name2 = RAW_RANKING_ORDER[idx2] if idx2 < len(RAW_RANKING_ORDER) else ""
        
        col1 = f"[{i}] {name1}"
        col2 = f"[{i+1}] {name2}" if name2 else ""
        print(f"{col1:<36} | {col2:<35}")

def execute_stallion_rankings_flow():
    """Handles Option 1 Tiered Navigation Flow."""
    tiers = [30, 50, 100, 150]
    tier_idx = 0
    
    while True:
        limit = tiers[tier_idx]
        print(f"\n--- DISPLAYING TOP {limit} STALLIONS ---")
        print_stallions_range(1, limit)
        
        print("\nNavigation Options:")
        if limit < 150:
            print("  [M] See More Stallions (Next Tier)")
            print("  [A] See All 150 Stallions Immediately")
        print("  [Number] Enter any rank number to see complete Stallion Profile")
        print("  [B] Back to Statistics Menu")
        
        choice = input("\nEnter choice: ").strip().upper()
        if choice == 'M' and limit < 150:
            tier_idx += 1
        elif choice == 'A':
            tier_idx = 3
        elif choice == 'B' or choice == '':
            break
        elif choice.isdigit():
            view_stallion_profile_by_rank(int(choice))
        else:
            print("❌ Invalid entry. Please enter M, A, B, or a valid rank number.")

def execute_broodmare_sire_flow():
    """Handles Option 2 Tiered Navigation Flow for Broodmare Sire Data."""
    raw_data = getattr(broodmare_sire_data, "broodmare_sire_raw", [])
    if not raw_data:
        print("\n⚠️ No broodmare records located inside broodmare_sire_data.py.")
        return

    tiers = [30, 50, 100, 150]
    tier_idx = 0

    while True:
        limit = min(tiers[tier_idx], len(raw_data))
        print(f"\n--- DISPLAYING TOP {limit} BROODMARE SIRES ---")
        print(f"{'Rank':<8} {'Stallion Name':<28} {'Lineage':<23} {'2026 Earnings':<15}")
        print("-" * 75)
        
        for entry in raw_data[:limit]:
            rank = entry.get("rank", "N/A")
            name = entry.get("stallion", "Unknown")
            lineage = entry.get("lineage", "N/A")
            earnings = entry.get("earnings_2026", 0)
            earn_str = f"${earnings:,}" if isinstance(earnings, (int, float)) else str(earnings)
            print(f"[{rank:<3}] {name:<28} {lineage:<23} {earn_str:<15}")

        print("\nNavigation Options:")
        if limit < len(raw_data):
            print("  [M] See More Broodmare Sires (Next Tier)")
            print("  [A] See All 150 Broodmare Sires Immediately")
        print("  [Number] Enter rank number to view deep data dictionary metrics")
        print("  [B] Back to Statistics Menu")

        choice = input("\nEnter choice: ").strip().upper()
        if choice == 'M' and limit < len(raw_data):
            tier_idx += 1
        elif choice == 'A':
            tier_idx = 3
        elif choice == 'B' or choice == '':
            break
        elif choice.isdigit():
            rank_num = int(choice)
            matched_entry = next((e for e in raw_data if e.get("rank") == rank_num), None)
            if matched_entry:
                s_name = matched_entry.get('stallion', '')
                print("=========================================================================")
                print(f" BROODMARE SIRE PROFILE DATA: {s_name.upper()}")
                print("=========================================================================")
                print(f" Rank                       : {matched_entry.get('rank', 'N/A')}")
                print(f" Sire/Lineage               : {matched_entry.get('lineage', 'N/A')}")
                print(f" Dams                       : {matched_entry.get('dams', 'N/A')}")
                print(f" Runners                    : {matched_entry.get('rnrs', 'N/A')}")
                print(f" Winners                    : {matched_entry.get('wnrs', 'N/A')}")
                print(f" Chief Earner in 2026       : {matched_entry.get('chief_earner', 'N/A')}")
                print(f" Chief Earner's Earnings    : ${matched_entry.get('chief_earners_earnings', 0):,}")
                print(f" Total Earnings in 2026     : ${matched_entry.get('earnings_2026', 0):,}")
                print(f" Total Stakes Winners       : {matched_entry.get('cum_swrs', 'N/A')}")
                print(f" Average Earnings Index(AEI): {matched_entry.get('aei', 'N/A')}")
                print(f" Comparative Index          : {matched_entry.get('comp_index', 'N/A')}")
                print(f" Total Foals                : {matched_entry.get('cum_foals', 'N/A')}")
                
                hit = main.resolve_pedigree(s_name, main.PEDIGREE_DATABASE, prompt=True)
                pedigree_data = hit["tree"] if hit["tree"] and not hit.get("cancelled") else None
                print("=========================================================")
                print(f"Pedigree Tree for: {s_name.upper()}")
                print("=========================================================")
                if pedigree_data and isinstance(pedigree_data, dict):
                    main.print_pedigree(pedigree_data)
                    main.analyze_inbreeding(pedigree_data)
                else:
                    print(f"There is no pedigree loaded for {s_name}")
                input("\nPress Enter to return to rankings...")
            else:
                print("\n❌ Invalid rank number selected.")
        else:
            print("❌ Invalid entry.")


# ==============================================================================
# BEST VALUE SIRES (OPTION 3 - PARSING LEGACY PROGENY STATS)
# ==============================================================================
def safe_display_profile(stallion_name):
    """Safely triggers profile rendering with proper capitalization matching."""
    try:
        profiles = _stallion_profiles()
        # Try exact match first
        if stallion_name in profiles:
            main.display_stallion_profile(stallion_name, profiles)
            return
        
        # Fallback to case-insensitive lookup
        for real_name in profiles.keys():
            if real_name.lower().strip() == stallion_name.lower().strip():
                main.display_stallion_profile(real_name, profiles)
                return
        print(f"❌ Could not find a profile layout for '{stallion_name}' in database.")
    except Exception as e:
        print(f"❌ Error displaying profile: {e}")


def display_best_value_sires():
    """Ranks stallions by Difference (Earnings Per Runner - Stud Fee). 
    Skips if Stud Fee is 0 OR if Earnings Per Runner is 0. Displays paginated results.
    """
    profiles = _stallion_profiles()
    value_list = []

    for name, data in profiles.items():
        fee_raw = data.get("Stud Fee", 0)
        
        # Parse stud fee strings safely
        if isinstance(fee_raw, str):
            fee_str = fee_raw.strip().lower()
            if "private" in fee_str or not fee_str or fee_str == "0":
                continue
            fee_digits = re.sub(r'[^\d]', '', fee_str)
            fee = float(fee_digits) if fee_digits else 0.0
        else:
            fee = float(fee_raw) if fee_raw else 0.0

        if fee == 0.0:
            continue

        earn_per_runner = 0.0
        
        # 1. Primary Strategy: Check modern Progeny Earnings Statistics block
        progeny_earnings = data.get("Progeny Earnings Statistics", {})
        if isinstance(progeny_earnings, dict) and "Avg Earnings/starter" in progeny_earnings:
            avg_earn_raw = progeny_earnings["Avg Earnings/starter"]
            if isinstance(avg_earn_raw, (int, float)):
                earn_per_runner = float(avg_earn_raw)
            else:
                # Strip out currency symbols and commas
                avg_earn_digits = re.sub(r'[^\d.]', '', str(avg_earn_raw))
                earn_per_runner = float(avg_earn_digits) if avg_earn_digits else 0.0

        # 2. Fallback Strategy: Check Legacy Progeny Stats block if primary failed
        if earn_per_runner == 0.0:
            legacy_block = data.get("Legacy Progeny Stats", {})
            if isinstance(legacy_block, dict) and "Total Earnings" in legacy_block:
                total_earnings_str = str(legacy_block["Total Earnings"])
                
                # Extract target pricing group value out from inside ()
                match = re.search(r'\(\$(\d{1,3}(?:,\d{3})*)\)', total_earnings_str)
                if match:
                    clean_runner_money = match.group(1).replace(',', '')
                    earn_per_runner = float(clean_runner_money)

        # Skip stallions with no runners/earnings yet
        if earn_per_runner == 0.0:
            continue

        difference = earn_per_runner - fee
        value_list.append({
            'name': name,
            'fee': fee,
            'earn_per_runner': earn_per_runner,
            'difference': difference
        })

    # Sort so the highest value difference is at the top
    value_list = sorted(value_list, key=lambda x: x['difference'], reverse=True)

    if not value_list:
        print("\n⚠️ No valid public stud fee or progeny runner values located.")
        input("\nPress Enter to return to menu...")
        return

    # Create a clean master registry map 
    global_registry = {idx: item['name'] for idx, item in enumerate(value_list, start=1)}

    # Pagination configuration state
    page_size = 25
    current_page = 0
    total_items = len(value_list)
    total_pages = (total_items + page_size - 1) // page_size

    while True:
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, total_items)
        page_items = value_list[start_idx:end_idx]

        print("\n========================================================================================")
        print(f"               TOP BEST VALUE SIRES (EARNINGS - FEE) - Page {current_page + 1} of {total_pages}               ")
        print("========================================================================================")
        print(f"{'No.':<6} {'Stallion Name':<25} {'Difference':<14} {'Earnings / Runner':<22} {'Stud Fee':<10}")
        print("-" * 88)
        
        for display_idx, item in enumerate(page_items, start=start_idx + 1):
            diff_fmt = f"${item['difference']:,.0f}" if item['difference'] >= 0 else f"-${abs(item['difference']):,.0f}"
            earn_fmt = f"${item['earn_per_runner']:,.0f}"
            fee_fmt = f"${item['fee']:,.0f}"
            print(f"[{display_idx:<3}]  {item['name']:<25} {diff_fmt:<14} {earn_fmt:<22} {fee_fmt:<10}")
        
        print("========================================================================================")
        print("Navigation Options:")
        
        nav_prompt = "  "
        if current_page < total_pages - 1:
            nav_prompt += "[N] Next Page  "
        if current_page > 0:
            nav_prompt += "[P] Previous Page  "
        print(nav_prompt)
        print("  [Number] Enter global number to view complete Stallion Profile")
        print("  [B] Back to Statistics Menu")
        
        choice = input("\nEnter choice: ").strip().upper()
        
        if choice == 'B' or choice == '':
            break
        elif choice == 'N' and current_page < total_pages - 1:
            current_page += 1
        elif choice == 'P' and current_page > 0:
            current_page -= 1
        elif choice.isdigit():
            selected = int(choice)
            if selected in global_registry:
                target_horse = global_registry[selected]
                safe_display_profile(target_horse)
                input("\nPress Enter to return to Value Sires list...")
            else:
                print(f"❌ Invalid choice. Select a number between 1 and {total_items}.")
        else:
            print("❌ Invalid entry.")
                        
# ==============================================================================
# CROP STATUS GROUPS SORT (OPTION 4 - SUB-MENU SYSTEM WITH FRESH [1] INDEXES)
# ==============================================================================

def display_by_crop_years():
    """Presents a custom sub-selection menu for crop categories, resetting numbering schemes to [1]."""
    profiles = _stallion_profiles()

    # Map keys directly matching your desired title configuration layout
    menu_map = {
        "1": ("No Foals Born Yet (first foals in 2027)", 2026),
        "2": ("First Foals Born in 2026", 2025),
        "3": ("Oldest Progeny Are Yearlings", 2024),
        "4": ("First-Crop Sires (oldest foals are 2 year olds)", 2023),
        "5": ("Second-Crop Sires (oldest foals are 3 year olds)", 2022)
    }

    while True:
        print("\n=========================================================================")
        print("                        SELECT CROP STATUS GROUP                         ")
        print("=========================================================================")
        print("1. 🔹 SEE NEW SIRES (FIRST FOALS IN 2027)")
        print("2. 🔹 SEE SIRES WITH FIRST WEANLINGS")
        print("3. 🔹 SEE SIRES WITH FIRST YEARLINGS")
        print("4. 🔹 SEE SIRES WITH FIRST 2 YEAR OLDS (FIRST-CROP SIRES)")
        print("5. 🔹 SEE SECOND-CROP SIRES (OLDEST FOALS ARE 3 YEAR OLDS)")
        print("6. ↩️ Return to Statistics Menu")
        print("=========================================================================")
        
        sub_choice = input("Enter choice (1-6): ").strip()
        if sub_choice == "6" or sub_choice == "":
            break
        
        if sub_choice not in menu_map:
            print("❌ Invalid entry. Select a choice between 1 and 6.")
            continue
            
        label_title, target_year = menu_map[sub_choice]
        
        # Pull matching horses from profiles database dictionary dynamically
        group_stallions = []
        for name, data in profiles.items():
            try:
                if int(data.get("Stud Duty Year", 0)) == target_year:
                    group_stallions.append(name)
            except (ValueError, TypeError):
                continue
                
        group_stallions = sorted(list(set(group_stallions)))
        
        if not group_stallions:
            print(f"\n⚠️ No stallions found in database matching: {label_title}")
            input("\nPress Enter to continue...")
            continue

        # Printout panel loop for the chosen category
        while True:
            print(f"\n🔹 SEE SIRES WITH {label_title.upper()}")
            print("-" * 75)
            
            indexed_registry = {}
            current_index = 1
            
            # Form clean two-column grid arrays resetting tracking item counters cleanly to 1
            for i in range(0, len(group_stallions), 2):
                h1 = group_stallions[i]
                idx1 = current_index
                indexed_registry[idx1] = h1
                current_index += 1
                col1 = f"[{idx1}] {h1}"
                
                col2 = ""
                if (i + 1) < len(group_stallions):
                    h2 = group_stallions[i+1]
                    idx2 = current_index
                    indexed_registry[idx2] = h2
                    current_index += 1
                    col2 = f"[{idx2}] {h2}"
                
                print(f"  {col1:<35} {col2:<35}")
                
            print("\nNavigation Options:")
            print("  [Number] Enter number to view complete Stallion Profile")
            print("  [B] Back to Crop Status Menu")
            
            grid_choice = input("\nEnter choice: ").strip().upper()
            if grid_choice == 'B' or grid_choice == '':
                break
            elif grid_choice.isdigit():
                selected_num = int(grid_choice)
                target_horse = indexed_registry.get(selected_num)
                if target_horse:
                    main.display_stallion_profile(target_horse, profiles)
                    input("\nPress Enter to return to specific crop selection screen...")
                else:
                    print(f"❌ Invalid selection. Choose a number between 1 and {current_index - 1}.")
            else:
                print("❌ Invalid entry.")


def run_stats_menu():
    """Sub-Menu Interface controller executing your custom options cleanly."""
    while True:
        print("\n=========================================")
        print("        STALLION STATISTICS ENGINE       ")
        print("=========================================")
        print("1. See 2026 Stallion Rankings (As of 6/15/2026)")
        print("2. See Broodmare Sire Stats")
        print("3. See Best Value Sires")
        print("4. Sort by Crop Status Groups")
        print("5. Return to Master Menu")
        print("=========================================")
        
        choice = input("Enter your option (1-5): ").strip()
        if choice == '1':
            execute_stallion_rankings_flow()
        elif choice == '2':
            execute_broodmare_sire_flow()
        elif choice == '3':
            display_best_value_sires()
        elif choice == '4':
            display_by_crop_years()
        elif choice == '5':
            break
        else:
            print("❌ Invalid choice. Select an option between 1 and 5.")