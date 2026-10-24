import datetime
import sys
import os
import copy
import re
import main
import hypofoals_manager
import placeholder_store
from graded_stakes import load_stakes_data

# Broodmare sire ranks from data/stallion_rankings.csv (Broodmare list).
BROODMARE_DATABASE = placeholder_store.load_broodmare_database()
clean_horse_name = placeholder_store.broodmare_clean_horse_name

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

SIRE_PARENTS = {
    "storm bird": "northern dancer",
    "storm cat": "storm bird",
    "harlan": "storm cat",
    "harlan's holiday": "harlan",
    "into mischief": "harlan's holiday",
    "barnes": "into mischief",
    "instagrand": "into mischief",
    "newgate": "into mischief",
    "audible": "into mischief",
    "life is good": "into mischief",
    "authentic": "into mischief",
    "highly motivated": "into mischief",
    "timberlake": "into mischief",
    "patch adams": "into mischief",
    "citizen bull": "into mischief",
    "goldencents": "into mischief",
    "by my standards": "goldencents",
    "mystik dan": "goldencents",
    "maximus mischief": "into mischief",
    "raging torrent": "maximus mischief",
    "practical joke": "into mischief",
    "domestic product": "practical joke",
    "tale of the cat" : "storm cat",
    "lion heart": "tale of the cat",
    "kantharos": "lion heart",
    "tale of ekati": "tale of the cat",
    "girvin": "tale of ekati",
    "hennessy": "storm cat",
    "johannesburg": "hennessy",
    "scat daddy": "johannesburg",
    "justify": "scat daddy",
    "arabian lion": "justify",
    "heartland": "justify",
    "giant's causeway": "storm cat",
    "eskendereya" : "giant's causeway",
    "mitole": "eskendereya",
    "shmardal" : "giant's causeway",
    "lope de vega": "shmardal",
    "carl spackler": "lope de vega",    
    "not this time" : "giant's causeway",
    "epicenter" : "not this time",
    "up to the mark" : "not this time",
    "cogburn" : "not this time",
    "bernstein": "storm cat",
    "karakontie": "bernstein",
    "forestry": "storm cat",
    "shackleford": "forestry",
    "promises fulfilled": "shackleford",
    "dixieland band": "northern dancer",
    "union rags": "dixieland band",
    "sadler's wells": "northern dancer",
    "el prado": "sadler's wells",
    "kitten's joy": "el prado",
    "divisidero": "kitten's joy",
    "bolt d'oro": "medaglia d'oro",
    "violence": "medaglia d'oro",
    "forte": "violence",
    "volatile": "violence",
    "dr. schivel": "violence",
    "mullikin": "violence",
    "danzig": "northern dancer",
    "war front": "danzig",
    "war command": "war front", 
    "omaha beach": "war front",
    "annapolis": "war front",
    "hard spun": "danzig",
    "silver state": "hard spun",
    "two phil's": "hard spun",
    "vice regent": "northern dancer",
    "deputy minister": "vice regent",
    "ghostzapper": "deputy minister",
    "mystic guide": "ghostzapper",
    "loggins": "ghostzapper",
    "a.p. indy": "seattle slew",
    "pulpit": "a.p. indy",
    "tapit": "pulpit",
    "essential quality": "tapit",
    "tacitus": "tapit",
    "arthur's ride": "tapit",
    "greatest honor": "tapit",
    "tapit trice": "tapit",
    "charge it": "tapit",
    "proxy": "tapit",
    "flightline": "tapit",
    "tonalist": "tapit",
    "country grammer": "tonalist",
    "constitution": "tapit",
    "tiz the law": "constitution",
    "mindframe": "constitution",
    "independence hall": "constitution",
    "take charge indy": "a.p. indy",
    "flatter": "a.p. indy",
    "upstart": "flatter",
    "zandon": "upstart",
    "honor code": "a.p. indy",
    "goal oriented": "honor code",
    "honor a.p.": "honor code",
    "friesan fire": "a.p. indy",
    "army mule": "friesan fire",
    "mineshaft": "a.p. indy",
    "senor buscador": "mineshaft",
    "fappiano": "mr prospector",
    "cryptoclearance": "fappiano",
    "ride the rails": "cryptoclearance",
    "candy ride": "ride the rails",
    "twirling candy": "candy ride",
    "rocky your world": "candy ride",
    "vekoma": "candy ride",
    "jonathan's way": "vekoma",
    "gun runner": "candy ride",
    "taiba": "gun runner",
    "gunite": "gun runner",
    "sierra leone": "gun runner",
    "cyberknife": "gun runner",
    "early voting": "gun runner",
    "gun pilot": "gun runner",
    "locked": "gun runner",
    "unbridled": "fappiano",
    "empire maker": "unbridled",
    "pioneerof the nile": "empire maker",
    "classic empire": "pioneerof the nile",
    "angel of empire": "classic empire",
    "cairo prince": "pioneerof the nile",
    "thousand words": "pioneerof the nile",
    "American Pharoah": "pioneerof the nile",
    "unbridled's song": "unbridled",
    "midshipman": "unbridled's song",
    "arrogate": "unbridled's song",
    "seize the grey": "arrogate",
    "arcangelo": "arrogate",
    "liam's map": "unbridled's song",
    "beau liam": "liam's map",
    "basin": "liam's map",
    "smart strike": "mr prospector",
    "curlin": "smart strike",
    "idol": "curlin",
    "highland falls": "curlin",
    "bright future": "curlin",
    "cody's wish": "curlin",
    "connect": "curlin",
    "known agenda": "curlin",
    "vino rosso": "curlin",
    "good magic": "curlin",
    "mage": "good magic",
    "dornoch": "good magic",
    "muth": "good magic",
    "forty niner": "mr prospector",
    "gone west": "forty niner",
    "speightstown": "gone west",
    "charlatan": "speightstown",
    "prince of monaco": "speightstown",
    "nashville": "speightstown",
    "olympiad": "speightstown",
    "munnings": "speightstown",
    "jack christopher": "munnings",
    "speightster": "speightstown",
    "straight no chaser": "speightster",
    "elusive quality": "gone west",
    "quality road": "elusive quality",
    "corniche": "quality road",
    "national treasure": "quality road",
    "city of light": "quality road",
    "fierceness": "city of light",
    "distorted humor": "forty niner",
    "jimmy creed": "distorted humor",
    "maclean's music": "distorted humor",
    "complexity": "maclean's music",
    "drain the clock": "maclean's music",
    "jackie's warrior": "maclean's music",
    "machiavellian": "mr prospector",
    "street cry": "machiavellian",
    "street sense": "street cry",
    "maxfield": "street sense",
    "speaker's corner": "street sense",
    "first mission": "street sense",
    "mckinzie": "street sense",
    "chancer mcpatrick": "mckinzie"   
}

SEX_MAP = {
    'c': 'colt', 'f': 'filly', 'r': 'ridgling', 
    'g': 'gelding', 'm': 'mare', 'h': 'horse'
}

def get_sire_line_ancestry(horse_name):
    clean_name = main.clean_horse_name(horse_name)
    ancestry = [clean_name]
    current = clean_name
    while current in SIRE_PARENTS:
        current = SIRE_PARENTS[current]
        ancestry.append(current)
    return ancestry

def find_lineage_relatives(stallion_clean):
    """
    Finds the stallion's immediate sire, paternal half-brothers,
    and all generations of deep sons/descendants.
    """
    target = stallion_clean.strip().lower()
    relatives = set()
    
    # 1. Find the immediate Sire
    immediate_sire = SIRE_PARENTS.get(target, "").strip().lower()
    if immediate_sire:
        relatives.add(immediate_sire)
        
        # 2. Find Paternal Half-Brothers (Sires sharing the same father)
        for son, parent in SIRE_PARENTS.items():
            if parent.strip().lower() == immediate_sire and son.strip().lower() != target:
                relatives.add(son.strip().lower())
                
    # 3. Find Sons and Deep Descendants (Recursive helper)
    def get_all_sons(parent_name):
        sons = []
        for son, parent in SIRE_PARENTS.items():
            if parent.strip().lower() == parent_name:
                sons.append(son.strip().lower())
                sons.extend(get_all_sons(son.strip().lower()))
        return sons

    descendants = get_all_sons(target)
    for desc in descendants:
        relatives.add(desc)

    return list(relatives)

def get_mare_sire_from_pedigree(pedigree_dict):
    if not pedigree_dict or not isinstance(pedigree_dict, dict):
        return ""
    sire_node = pedigree_dict.get("Sire")
    if sire_node and isinstance(sire_node, dict):
        return sire_node.get("Horse", "")
    elif isinstance(sire_node, str):
        return sire_node
    return ""

def _is_winning_place(record):
    """Treat missing Place as a winner (old winner-only files). Otherwise require 1."""
    place = record.get("Place", 1)
    if place in ("", None):
        return True
    try:
        return int(float(place)) == 1
    except (TypeError, ValueError):
        return False


def _surface_from_distance(dist_str):
    upper = str(dist_str or "").upper()
    if "(D)" in upper:
        return "dirt"
    if "(T)" in upper:
        return "turf"
    if "(AW)" in upper:
        return "all-weather"
    return "track"


def build_horse_summaries(records):
    """Build per-horse win summaries. Only Place==1 rows are counted as wins."""
    horses = {}
    for r in records:
        h_name = str(r.get("Horse Name") or "").strip()
        if not h_name or h_name.upper() in {"N/A", "NAN", "NONE"}:
            continue
        if not _is_winning_place(r):
            continue

        if h_name not in horses:
            sex_val = str(r.get("Sex") or "").strip().lower()
            horses[h_name] = {
                'name': h_name,
                'foaling_year': r.get('Foaling Year') or "",
                'sex': sex_val,
                'races': [],
                'wins': [],
                'g1_count': 0, 'g2_count': 0, 'g3_count': 0, 'ungraded_count': 0
            }
        
        dist_str = str(r.get('Distance') or "")
        surface = _surface_from_distance(dist_str)
        clean_dist = re.sub(r'\s*\([^)]*\)', '', dist_str).strip()
        grade = str(r.get('Grade') or r.get('Group') or "").strip()
        purse = str(r.get('Purse') or "").strip()
        race_name = str(r.get('Race Name') or "").strip()
        race_year = r.get('Race Year') or ""
        
        race_line = f"{h_name} won the {race_year} edition of the {purse} {grade} {race_name} over {clean_dist} on the {surface}"
        horses[h_name]['races'].append(race_line)
        horses[h_name]['wins'].append({"year": str(race_year), "grade": grade, "race": race_name})
        
        grade_upper = grade.upper()
        if 'G1' in grade_upper: horses[h_name]['g1_count'] += 1
        elif 'G2' in grade_upper: horses[h_name]['g2_count'] += 1
        elif 'G3' in grade_upper: horses[h_name]['g3_count'] += 1
        else: horses[h_name]['ungraded_count'] += 1

    for h_name, h in horses.items():
        if h['g1_count'] > 1: h['status'] = 'MG1W'
        elif h['g1_count'] == 1: h['status'] = 'G1W'
        elif (h['g2_count'] + h['g3_count']) > 1: h['status'] = 'MGSW'
        elif h['g2_count'] == 1: h['status'] = 'G2W'
        elif h['g3_count'] == 1: h['status'] = 'G3W'
        elif h['ungraded_count'] > 1: h['status'] = 'MSW'
        else: h['status'] = 'SW'
        
    return horses

def check_inbreeding_failsafe(stallion_ped, mare_ped, max_generation=3):
    def collect_ancestors(node, depth, gathered):
        if not node or not isinstance(node, dict) or depth > max_generation:
            return
        name = main.clean_horse_name(node.get("Horse", ""))
        if name and "unknown" not in name:
            gathered.add(name)
        collect_ancestors(node.get("Sire"), depth + 1, gathered)
        collect_ancestors(node.get("Dam"), depth + 1, gathered)

    stallion_anc = set()
    mare_anc = set()
    collect_ancestors(stallion_ped, 1, stallion_anc)
    collect_ancestors(mare_ped, 1, mare_anc)
    return len(stallion_anc.intersection(mare_anc)) > 0

def view_hypofoals_db(all_profiles):
    """Integrated: Displays saved matings directly out of hypofoals.py flat-file."""
    hypo_db = hypofoals_manager.load_hypo_database()
    if not hypo_db:
        print("\n📭 The hypothetical foal database is currently empty.")
        return
        
    print(f"\n📁 --- RECORDED HYPOTHETICAL MATINGS CRADLE ({len(hypo_db)} entries) ---")
    keys = sorted(hypo_db.keys())
    for idx, key in enumerate(keys, 1):
        print(f"  [{idx}] {key.upper()}")
    
    sel = input("\nEnter entry number to print complete pedigree profile (or hit Enter to go back): ").strip()
    if sel.isdigit():
        idx = int(sel) - 1
        if 0 <= idx < len(keys):
            target_tree = hypo_db[keys[idx]]
            print("\n" + "="*80)
            print(f" Displaying Tree Architecture for: {keys[idx].upper()}")
            print("="*80)
            main.print_pedigree(target_tree)
            main.analyze_inbreeding(target_tree)

def run_hypomating_menu(pedigree_db, all_profiles):
    print("\n=========================================")
    print("         HYPOMATING ENGINE [CSV v2.1]    ")
    print("=========================================")
    print(" [1] Input New Broodmare & Run Suggestions")
    print(" [2] Search Top Crosses for Stallion")
    print(" [3] View Saved Hypomatings Database")
    print(" [B] Back to Main Menu")
    print("=========================================")
    choice = input("Select option: ").strip()
    if choice == "1":
        execute_suggestion_wizard(pedigree_db, all_profiles)
    elif choice == "2":
        execute_top_crosses_search(pedigree_db)
    elif choice == "3":
        view_hypofoals_db(all_profiles)

def get_profile_meta(name, all_profiles):
    clean_name = main.clean_horse_name(name)
    rank_val = "N/A"
    for idx, r_name in enumerate(RAW_RANKING_ORDER, 1):
        if main.clean_horse_name(r_name) == clean_name:
            rank_val = str(idx)
            break

    profile = {}
    for k, v in all_profiles.items():
        if main.clean_horse_name(k) == clean_name:
            profile = v
            break

    raw_fee = profile.get("Stud Fee", 0)
    try:
        fee_num = int(str(raw_fee).replace(",", "").replace("$", ""))
        fee_str = f"${fee_num:,.0f}"
    except ValueError:
        fee_num = 0
        fee_str = "$0" if not raw_fee else str(raw_fee)
        
    has_progeny = profile.get("HasProgeny", profile.get("Has Progeny", True))
    
    # SIMPLIFICATION RULE: Check if horse is in profiles AND status is not pensioned
    is_pensioned = str(profile.get("Status", "")).strip().lower() == "pensioned"
    # Only suggest stallions standing now: a published fee and a recent stud season.
    # Dead or retired sires keep "active" status but lose their fee / duty year.
    try:
        duty_year = int(str(profile.get("Stud Duty Year") or "").strip()[:4])
    except ValueError:
        duty_year = None
    is_standing = fee_num > 0 and (duty_year is None or duty_year >= datetime.date.today().year - 1)
    is_active = (len(profile) > 0) and not is_pensioned and is_standing

    return {"rank": rank_val, "fee_str": fee_str, "fee_num": fee_num, "has_progeny": has_progeny, "is_active": is_active}

def sort_ancestor_list(ancestor_names, all_profiles, budget_filter=None):
    meta_list = []
    for name in ancestor_names:
        meta = get_profile_meta(name, all_profiles)
        if meta["is_active"]:
            if budget_filter is not None and meta["fee_num"] > budget_filter:
                continue
            meta_list.append((name, meta))
        
    def sorting_key(item):
        name, m = item
        try:
            r_val = float(m["rank"])
        except (ValueError, TypeError):
            r_val = float('inf')
        f_val = m["fee_num"]
        return (r_val, -f_val, name)
        
    meta_list.sort(key=sorting_key)
    return [item[0] for item in meta_list]

def has_lineage_options(stallion_name, all_profiles, budget_filter=None):
    """Checks if a stallion actually has ancestors, sibling sires, or descendants available."""
    st_clean = main.clean_horse_name(stallion_name)
    lineage_options = find_lineage_relatives(st_clean)
    
    if sort_ancestor_list(lineage_options, all_profiles, budget_filter):
        return True
        
    return False

def show_lineage_branch_flow(stallion_name, all_profiles, pedigree_db, budget_filter=None):
    st_clean = main.clean_horse_name(stallion_name)
    print(f"\n--- ANCESTRY & ALTERNATIVE VARIANT OPTIONS FOR {stallion_name.upper()} ---")
    
    available_options = []
    
    # Pull the Sire, half-brothers, and descendants together
    all_relatives = find_lineage_relatives(st_clean)
    sorted_relatives = sort_ancestor_list(all_relatives, all_profiles, budget_filter)
    
    if sorted_relatives:
        print(" ⭐ AVAILABLE LINEAGE OPTIONS (SIRE, PATERNAL HALF-BROS, & SONS):")
        for relative in sorted_relatives:
            meta = get_profile_meta(relative, all_profiles)
            if meta['is_active']:
                print(f"   [{len(available_options) + 1}] {relative.title()} | Stud Rank: #{meta['rank']} | Stud Fee: {meta['fee_str']} |")
                available_options.append(relative)

    if not available_options:
        print(" (No active variants or lineages available for this stallion profile within budget bounds.)")
        input("\nPress Enter to go back...")
        return None

    sub_sel = input("\nSelect an alternative variant option number to mate, or 'B' to go back: ").strip()
    if sub_sel.lower() == 'b' or not sub_sel.isdigit():
        return None
        
    idx = int(sub_sel) - 1
    if 0 <= idx < len(available_options):
        return available_options[idx]
    return None

def execute_top_crosses_search(pedigree_db):
    print("\n--- STALLION TOP CROSSES SEARCH ---")
    target_stallion = input("Enter Stallion Name (e.g., Into Mischief): ").strip()
    if not target_stallion: return

    hit = main.resolve_pedigree(target_stallion, pedigree_db, prompt=True)
    if hit.get("cancelled"):
        return
    if hit["tree"] and hit["tree"].get("Horse"):
        target_stallion = hit["tree"].get("Horse")
    chosen_year = hit.get("query_year") or ""
    
    clean_target = main.clean_horse_name(target_stallion)
    raw_records = load_stakes_data()
    horse_summaries = build_horse_summaries(raw_records)
    
    crosses = {}
    status_weights = {"MG1W": 500, "G1W": 400, "MGSW": 300, "G2W": 250, "G3W": 200, "MSW": 150, "SW": 100}
    tier_order = ["MG1W", "G1W", "MGSW", "G2W", "G3W", "MSW", "SW"]

    for h_name, h in horse_summaries.items():
        clean_h = main.clean_horse_name(h_name) 
        if clean_h in pedigree_db:
            h_ped = pedigree_db[clean_h]
            sire_node = h_ped.get("Sire", {})
            h_sire = sire_node.get("Horse", "") if isinstance(sire_node, dict) else str(sire_node)
            
            if main.clean_horse_name(h_sire) == clean_target:
                sire_year = main.foaling_year(h_sire)
                if chosen_year and sire_year and sire_year != chosen_year:
                    continue
                dam_node = h_ped.get("Dam", {})
                h_damsire = get_mare_sire_from_pedigree(dam_node)
                if h_damsire:
                    clean_ds = re.sub(r'\s*\(\d{4}\)', '', h_damsire).strip().title()
                    if clean_ds not in crosses:
                        crosses[clean_ds] = {"score": 0, "winners_data": []}
                    
                    points = status_weights.get(h['status'], 100)
                    crosses[clean_ds]["score"] += points
                    crosses[clean_ds]["winners_data"].append({
                        "name": h_name,
                        "status": h['status']
                    })

    if not crosses:
        print(f"\n❌ No stakes cross records found for stallion '{target_stallion}'.")
        input("\nPress Enter to return...")
        return

    sorted_crosses = sorted(crosses.items(), key=lambda x: -x[1]["score"])
    
    print("\n" + "="*80)
    print(f" 📈 TOP RANKED BROODMARE SIRE CROSSES FOR {target_stallion.upper()}")
    print("="*80)
    for idx, (ds_name, data) in enumerate(sorted_crosses, 1):
        sorted_progeny = sorted(
            data['winners_data'], 
            key=lambda x: tier_order.index(x['status']) if x['status'] in tier_order else 99
        )
        winners_strings = [f"{w['name']} ({w['status']})" for w in sorted_progeny]
        winners_list = ", ".join(winners_strings)
        
        lookup_key = clean_horse_name(ds_name) 
        bms_rank_info = BROODMARE_DATABASE.get(lookup_key)
        
        if bms_rank_info and "Rank" in bms_rank_info:
            rank_display = f"Rank: #{bms_rank_info['Rank']}"
        else:
            rank_display = "Rank: Unranked"
            
        print(f"  {idx}) {ds_name} | {rank_display} | Progeny: {winners_list}")
        
    print("="*80)
    input("\nPress Enter to return to menu...")
        
def execute_suggestion_wizard(pedigree_db, all_profiles):
    print("\n--- STEP 1: Broodmare Profile Input ---")
    mare_name = input("Enter Broodmare Name: ").strip()
    if not mare_name: return
    
    hit = main.resolve_pedigree(mare_name, pedigree_db, prompt=True)
    if hit.get("cancelled"):
        return
    if hit["tree"]:
        print(f"🌟 Complete tree found for '{mare_name}' in database! Autofilling pedigree tree.")
        mare_pedigree = copy.deepcopy(hit["tree"])
        mare_name = mare_pedigree.get("Horse", mare_name)
    else:
        print("\n==================================================")
        print("   🐎 Launching Standalone Pedigree Builder 🐎   ")
        print("==================================================\n")
        try:
            import importlib
            import add_pedigrees
            
            importlib.reload(add_pedigrees)
            add_pedigrees.main()
            
            if hasattr(main, 'load_and_sync_all_data'):
                main.PEDIGREE_DATABASE = main.load_and_sync_all_data()
            if hasattr(main, 'PEDIGREE_DATABASE'):
                pedigree_db.update(main.PEDIGREE_DATABASE)
                
            try:
                from crossr_core import pedigree_store
                pedigree_db.update(pedigree_store.get_pedigree_map(refresh=True))
            except Exception:
                pass
                
        except ImportError:
            print("❌ Error: Could not locate 'add_pedigrees.py' in the current working directory.")
        except Exception as e:
            print(f"⚠️ An error occurred while running the pedigree builder: {e}")

        hit = main.resolve_pedigree(mare_name, pedigree_db, prompt=True)
        if hit.get("cancelled"):
            return
        if hit["tree"]:
            mare_pedigree = copy.deepcopy(hit["tree"])
            mare_name = mare_pedigree.get("Horse", mare_name)
        else:
            print(f"❌ Broodmare '{mare_name}' not found in registry cache post builder run.")
            return

    clean_mare = main.clean_horse_name(mare_name)
    mating_damsire = get_mare_sire_from_pedigree(mare_pedigree)
    clean_display_damsire = re.sub(r'\s*\(\d{4}\)', '', mating_damsire).strip()
    clean_display_mare = re.sub(r'\s*\(\d{4}\)', '', mare_name).strip()
    print(f"🧬 Identified Sire / Damsire Line: {clean_display_damsire if clean_display_damsire else 'Unknown'}")

    print("\n--- STEP 2: Target Preferences ---")
    surface_pref = input("Future foal surface preference (Dirt/Turf/Neither): ").strip().lower()
    
    try:
        max_fee_input = input("Maximum target Stud Fee budget ($ or 'none'): ").strip().replace(",", "").replace("$", "")
        max_fee = sys.maxsize if (max_fee_input.lower() == 'none' or not max_fee_input) else int(max_fee_input)
    except ValueError:
        max_fee = sys.maxsize

    raw_records = load_stakes_data()
    
    if surface_pref in ["dirt", "turf"]:
        filtered_records = []
        for r in raw_records:
            dist_str = str(r.get('Distance', ''))
            r_surf = "dirt" if "(D)" in dist_str.upper() else "turf" if "(T)" in dist_str.upper() else "track"
            if r_surf == surface_pref:
                filtered_records.append(r)
    else:
        filtered_records = raw_records

    horse_summaries = build_horse_summaries(filtered_records)
    
    proven_cross_sires = {}
    direct_progeny_clean_names = set()
    mare_sire_ancestry = get_sire_line_ancestry(mating_damsire)

    for h_name, h in horse_summaries.items():
        clean_h = main.clean_horse_name(h_name)
        if clean_h in pedigree_db:
            h_ped = pedigree_db[clean_h]
            dam_node = h_ped.get("Dam", {})
            dam_name = dam_node.get("Horse", "") if isinstance(dam_node, dict) else str(dam_node)
            
            if main.clean_horse_name(dam_name) == clean_mare:
                direct_progeny_clean_names.add(clean_h)
                sire_node = h_ped.get("Sire", {})
                sire_name = sire_node.get("Horse", "Unknown Stallion") if isinstance(sire_node, dict) else str(sire_node)
                clean_sire = main.clean_horse_name(sire_name)
                
                clean_display_sire = re.sub(r'\s*\(\d{4}\)', '', sire_name).strip()
                races_sentence = " ".join(h['races'])
                sex_word = SEX_MAP.get(h['sex'], h['sex'])
                bio_sentence = f"{h_name} was foaled in {h['foaling_year']} and is a {sex_word} by {clean_display_sire} out of the {clean_display_damsire} mare {clean_display_mare}."
                
                proven_cross_sires[clean_sire] = {
                    "foal_name": h_name, "status": h['status'],
                    "races_sentence": races_sentence, "bio_sentence": bio_sentence,
                    "actual_sire_name": clean_display_sire
                }
                print(f"🔥 Auto-Recognized Success Match: Dam of Stakes Winner {h_name} ({h['status']}) by {clean_display_sire}!")

    candidates = {}
    for st_name, p_data in all_profiles.items():
        clean_st = main.clean_horse_name(st_name)
        if str(p_data.get("Status", "")).strip().lower() == "pensioned": continue
        
        meta_check = get_profile_meta(st_name, all_profiles)
        if not meta_check["is_active"]: continue

        st_fee = p_data.get("Stud Fee", 0)
        try:
            fee_val = int(str(st_fee).replace(",", "").replace("$", ""))
        except ValueError:
            fee_val = 0
        if max_fee != sys.maxsize and fee_val > max_fee: continue

        st_pedigree = pedigree_db.get(clean_st, {"Horse": st_name})
        if check_inbreeding_failsafe(st_pedigree, mare_pedigree, max_generation=3): continue

        candidates[clean_st] = {
            "name": st_name, "score": 0.0, "reasons_by_tier": {t: [] for t in ["MG1W", "G1W", "MGSW", "G2W", "G3W", "MSW", "SW"]}, "direct_hit": False, "cross_meta": []
        }

    for h_name, h in horse_summaries.items():
        clean_h = main.clean_horse_name(h_name)
        if clean_h in direct_progeny_clean_names: continue 

        h_damsire, h_sire = "", ""
        if clean_h in pedigree_db:
            h_ped = pedigree_db[clean_h]
            sire_node = h_ped.get("Sire", {})
            h_sire = sire_node.get("Horse", "") if isinstance(sire_node, dict) else str(sire_node)
            dam_node = h_ped.get("Dam", {})
            if isinstance(dam_node, dict): h_damsire = get_mare_sire_from_pedigree(dam_node)

        if h_damsire and main.clean_horse_name(h_damsire) in mare_sire_ancestry:
            clean_hsire = main.clean_horse_name(h_sire)
            status_weights = {"MG1W": 500, "G1W": 400, "MGSW": 300, "G2W": 250, "G3W": 200, "MSW": 150, "SW": 100}
            base_points = status_weights.get(h['status'], 100)
            
            clean_display_hsire = re.sub(r'\s*\(\d{4}\)', '', h_sire).strip()
            clean_display_h_ds = re.sub(r'\s*\(\d{4}\)', '', h_damsire).strip()
            races_sentence = " ".join(h['races'])

            for clean_st, cand_dict in candidates.items():
                if clean_st == clean_hsire:
                    cand_dict["score"] += base_points
                    cand_dict["direct_hit"] = True
                    msg = f"Cross Success ({h['status']}): {clean_display_hsire} over a {clean_display_h_ds} mare produced {h_name}. {races_sentence}"
                    if msg not in cand_dict["reasons_by_tier"][h['status']]: 
                        cand_dict["reasons_by_tier"][h['status']].append(msg)

    for clean_st, cand_dict in candidates.items():
        for clean_cross_sire, meta in proven_cross_sires.items():
            if clean_st == clean_cross_sire:
                cand_dict["score"] += 10000
                cand_dict["direct_hit"] = True
                if meta not in cand_dict["cross_meta"]: cand_dict["cross_meta"].append(meta)

    active_pool = [c for c in candidates.values() if c["score"] > 0 and c["direct_hit"]]
    sorted_pool = sorted(active_pool, key=lambda x: -x["score"])

    unfiltered_structural_hits = []
    for st_name, p_data in all_profiles.items():
        clean_st = main.clean_horse_name(st_name)
        st_pedigree = pedigree_db.get(clean_st, {"Horse": st_name})
        if check_inbreeding_failsafe(st_pedigree, mare_pedigree, max_generation=3): continue
        
        has_cross_hit = False
        for h_name, h in horse_summaries.items():
            h_damsire, h_sire = "", ""
            if main.clean_horse_name(h_name) in pedigree_db:
                hp = pedigree_db[main.clean_horse_name(h_name)]
                s_node = hp.get("Sire", {})
                h_sire = s_node.get("Horse", "") if isinstance(s_node, dict) else str(s_node)
                d_node = hp.get("Dam", {})
                if isinstance(d_node, dict): h_damsire = get_mare_sire_from_pedigree(d_node)
            if h_damsire and main.clean_horse_name(h_damsire) in mare_sire_ancestry:
                if main.clean_horse_name(h_sire) == clean_st:
                    has_cross_hit = True
                    break
        if has_cross_hit and clean_st not in [main.clean_horse_name(c["name"]) for c in active_pool]:
            unfiltered_structural_hits.append(st_name)

    chosen_stallion = None
    show_all = False

    while True:
        print("\n==========================================================================================")
        print(f"🏆 STALLION SUGGESTIONS FOR {mare_name.upper()}:")
        print("==========================================================================================")
        
        current_idx = 1
        displayed_items_map = {}
        
        proven_limit = len(sorted_pool) if show_all else min(10, len(sorted_pool))
        for i in range(proven_limit):
            cand = sorted_pool[i]
            meta = get_profile_meta(cand['name'], all_profiles)
            print(f"  {current_idx}) {cand['name']} | Stud Rank: #{meta['rank']} | Stud Fee: {meta['fee_str']} |")
            displayed_items_map[current_idx] = ("PROVEN", cand['name'])
            current_idx += 1

        for cand in sorted_pool:
            if has_lineage_options(cand['name'], all_profiles, budget_filter=max_fee):
                print(f"  {current_idx}) [Lineage Group] Alternatives / Ancestors of {cand['name']}")
                displayed_items_map[current_idx] = ("ANCESTRY_FOR", cand['name'])
                current_idx += 1
            
        for unfil_name in unfiltered_structural_hits:
            if has_lineage_options(unfil_name, all_profiles, budget_filter=max_fee):
                print(f"  {current_idx}) [Lineage Group] Alternatives / Ancestors of {unfil_name} (Cross Variant)")
                displayed_items_map[current_idx] = ("ANCESTRY_FOR", unfil_name)
                current_idx += 1

        print("==========================================================================================")
        if not show_all and len(sorted_pool) > 10:
            more = input(f"Plus reference entries available. See full list? (y/n): ").strip().lower()
            if more == 'y':
                show_all = True
                continue

        sel = input("Select an option number to inspect (or 'B' to exit): ").strip()
        if sel.lower() == 'b': return
        if not sel.isdigit() or int(sel) < 1 or int(sel) >= current_idx:
            print("❌ Invalid selection.")
            continue
            
        item_type, target_name = displayed_items_map[int(sel)]
        
        if item_type == "ANCESTRY_FOR":
            selected_alternative = show_lineage_branch_flow(target_name, all_profiles, pedigree_db, budget_filter=max_fee)
            if selected_alternative:
                chosen_stallion = selected_alternative
                break
            else:
                continue
                
        chosen_cand = None
        for c in sorted_pool:
            if c['name'] == target_name:
                chosen_cand = c
                break
                
        st_clean = main.clean_horse_name(chosen_cand['name'])
        print(f"\n--- OPTIONS FOR {chosen_cand['name'].upper()} ---")
        print(" [L] See Logic (Race breakdown history)")
        print(" [S] Select this Stallion for Mating Report")
        print(" [B] Go back to list")
        cmd = input("Choose action (L/S/B): ").strip().upper()
        
        if cmd == 'L':
            print(f"\n--- CROSS LOGIC BREAKDOWN FOR {chosen_cand['name'].upper()} ---")
            if chosen_cand['cross_meta']:
                print("\n⭐ Proven Cross:")
                for meta in chosen_cand['cross_meta']:
                    print(f"  ↳ {meta['races_sentence']}")
                    print(f"  ↳ {meta['bio_sentence']}\n")
            
            print("📈 LINEAGE CROSS SUCCESS ENTRIES:")
            for tier in ["MG1W", "G1W", "MGSW", "G2W", "G3W", "MSW", "SW"]:
                for reason_msg in sorted(chosen_cand["reasons_by_tier"][tier]):
                    print(f" ↳ {reason_msg}")
            input("\nPress Enter to return to options...")
            
        elif cmd == 'S':
            chosen_stallion = chosen_cand['name']
            break
        else:
            continue

    if not chosen_stallion:
        return

    hypo_foal_name = f"{chosen_stallion.title()} x {mare_name}"
    combined_pedigree = {
        "Horse": hypo_foal_name,
        "Sire": copy.deepcopy(main.pedigree_tree(chosen_stallion, pedigree_db) or {"Horse": chosen_stallion}),
        "Dam": copy.deepcopy(mare_pedigree)
    }

    if hasattr(main, 'save_hypofoal_to_file'):
        main.save_hypofoal_to_file(mare_name, hypo_foal_name, chosen_stallion, combined_pedigree)
        
    print("\n" + "="*80)
    print("      HYPOTHETICAL FOAL REPORT GENERATED SUCCESSFULLY")
    print("="*80)
    main.display_stallion_profile(chosen_stallion, all_profiles)
    print("\n🧬 COMBINED GENERATION PEDIGREE:")
    main.print_pedigree(combined_pedigree)
    main.analyze_inbreeding(combined_pedigree)

    print("\n✍️ Recording cross architecture context...")
    hypofoals_manager.register_new_hypo_foal(
        sire_name=chosen_stallion,
        dam_name=mare_name,
        combined_tree=combined_pedigree
    )


def lookup_mare_pedigree(pedigree_db, mare_name):
    """Find a broodmare pedigree by cleaned or uppercase name. Returns (tree, matched_key) or (None, None)."""
    hit = main.lookup_pedigree(mare_name, pedigree_db)
    if hit["ambiguous"] or not hit["tree"]:
        return None, None
    return copy.deepcopy(hit["tree"]), hit["key"]


def suggest_matings(pedigree_db, all_profiles, mare_name, surface_pref="neither", min_fee=None, max_fee=None):
    """Non-interactive stallion suggestions for a broodmare already in the pedigree database."""
    hit = main.lookup_pedigree(mare_name, pedigree_db)
    if hit["ambiguous"]:
        return {"error": "ambiguous_year", "mare": hit["clean_name"], "years": hit["years"]}
    mare_pedigree, matched_key = lookup_mare_pedigree(pedigree_db, mare_name)
    if not mare_pedigree:
        return {"error": "not_found", "mare": mare_name}

    mare_display = mare_pedigree.get("Horse", mare_name)
    clean_mare = main.clean_horse_name(matched_key or mare_name)
    mating_damsire = get_mare_sire_from_pedigree(mare_pedigree)
    clean_display_damsire = re.sub(r'\s*\(\d{4}\)', '', mating_damsire).strip()
    clean_display_mare = re.sub(r'\s*\(\d{4}\)', '', mare_display).strip()

    surface = (surface_pref or "neither").strip().lower()
    fee_cap = sys.maxsize if max_fee is None else int(max_fee)

    raw_records = load_stakes_data()
    if surface in ["dirt", "turf"]:
        filtered_records = []
        for r in raw_records:
            dist_str = str(r.get("Distance", ""))
            r_surf = "dirt" if "(D)" in dist_str.upper() else "turf" if "(T)" in dist_str.upper() else "track"
            if r_surf == surface:
                filtered_records.append(r)
    else:
        filtered_records = raw_records

    horse_summaries = build_horse_summaries(filtered_records)
    proven_cross_sires = {}
    direct_progeny_clean_names = set()
    mare_sire_ancestry = get_sire_line_ancestry(mating_damsire)

    for h_name, h in horse_summaries.items():
        clean_h = main.clean_horse_name(h_name)
        if clean_h in pedigree_db:
            h_ped = pedigree_db[clean_h]
            dam_node = h_ped.get("Dam", {})
            dam_name = dam_node.get("Horse", "") if isinstance(dam_node, dict) else str(dam_node)
            if main.clean_horse_name(dam_name) == clean_mare:
                direct_progeny_clean_names.add(clean_h)
                sire_node = h_ped.get("Sire", {})
                sire_name = sire_node.get("Horse", "Unknown Stallion") if isinstance(sire_node, dict) else str(sire_node)
                clean_sire = main.clean_horse_name(sire_name)
                clean_display_sire = re.sub(r'\s*\(\d{4}\)', '', sire_name).strip()
                proven_cross_sires[clean_sire] = {
                    "foal_name": h_name,
                    "status": h["status"],
                    "sex": h["sex"],
                    "sire": clean_display_sire,
                    "dam": clean_display_mare,
                    "damsire": clean_display_damsire,
                    "wins": h["wins"],
                    "races_sentence": " ".join(h["races"]),
                    "bio_sentence": (
                        f"{h_name} was foaled in {h['foaling_year']} and is a "
                        f"{SEX_MAP.get(h['sex'], h['sex'])} by {clean_display_sire} "
                        f"out of the {clean_display_damsire} mare {clean_display_mare}."
                    ),
                    "actual_sire_name": clean_display_sire,
                }

    candidates = {}
    for st_name, p_data in all_profiles.items():
        if str(p_data.get("Status", "")).strip().lower() == "pensioned":
            continue
        meta_check = get_profile_meta(st_name, all_profiles)
        if not meta_check["is_active"]:
            continue
        st_fee = p_data.get("Stud Fee", 0)
        try:
            fee_val = int(str(st_fee).replace(",", "").replace("$", ""))
        except ValueError:
            fee_val = 0
        if min_fee is not None and fee_val < int(min_fee):
            continue
        if fee_cap != sys.maxsize and fee_val > fee_cap:
            continue
        clean_st = main.clean_horse_name(st_name)
        st_pedigree = pedigree_db.get(clean_st, {"Horse": st_name})
        if check_inbreeding_failsafe(st_pedigree, mare_pedigree, max_generation=3):
            continue
        candidates[clean_st] = {
            "name": st_name,
            "score": 0.0,
            "reasons_by_tier": {t: [] for t in ["MG1W", "G1W", "MGSW", "G2W", "G3W", "MSW", "SW"]},
            "direct_hit": False,
            "cross_meta": [],
            "crosses": [],
        }

    status_weights = {"MG1W": 500, "G1W": 400, "MGSW": 300, "G2W": 250, "G3W": 200, "MSW": 150, "SW": 100}
    for h_name, h in horse_summaries.items():
        clean_h = main.clean_horse_name(h_name)
        if clean_h in direct_progeny_clean_names:
            continue
        h_damsire, h_sire, h_dam = "", "", ""
        if clean_h in pedigree_db:
            h_ped = pedigree_db[clean_h]
            sire_node = h_ped.get("Sire", {})
            h_sire = sire_node.get("Horse", "") if isinstance(sire_node, dict) else str(sire_node)
            dam_node = h_ped.get("Dam", {})
            if isinstance(dam_node, dict):
                h_damsire = get_mare_sire_from_pedigree(dam_node)
                h_dam = dam_node.get("Horse", "")
        if h_damsire and main.clean_horse_name(h_damsire) in mare_sire_ancestry:
            clean_hsire = main.clean_horse_name(h_sire)
            base_points = status_weights.get(h["status"], 100)
            clean_display_hsire = re.sub(r'\s*\(\d{4}\)', '', h_sire).strip()
            clean_display_h_ds = re.sub(r'\s*\(\d{4}\)', '', h_damsire).strip()
            races_sentence = " ".join(h["races"])
            for clean_st, cand_dict in candidates.items():
                if clean_st == clean_hsire:
                    cand_dict["score"] += base_points
                    cand_dict["direct_hit"] = True
                    msg = (
                        f"Cross Success ({h['status']}): {clean_display_hsire} over a "
                        f"{clean_display_h_ds} mare produced {h_name}. {races_sentence}"
                    )
                    if msg not in cand_dict["reasons_by_tier"][h["status"]]:
                        cand_dict["reasons_by_tier"][h["status"]].append(msg)
                        cand_dict["crosses"].append({
                            "name": h_name,
                            "status": h["status"],
                            "sex": h["sex"],
                            "sire": clean_display_hsire,
                            "dam": re.sub(r'\s*\(\d{4}\)', '', h_dam).strip(),
                            "damsire": clean_display_h_ds,
                            "wins": h["wins"],
                        })

    for clean_st, cand_dict in candidates.items():
        for clean_cross_sire, meta in proven_cross_sires.items():
            if clean_st == clean_cross_sire:
                cand_dict["score"] += 10000
                cand_dict["direct_hit"] = True
                if meta not in cand_dict["cross_meta"]:
                    cand_dict["cross_meta"].append(meta)

    active_pool = [c for c in candidates.values() if c["score"] > 0 and c["direct_hit"]]
    sorted_pool = sorted(active_pool, key=lambda x: -x["score"])

    # Sires of graded winners whose damsire is in the mare's sire line. Computed
    # once instead of re-reading every winner's pedigree for each stallion.
    cross_hit_sires = set()
    for h_name in horse_summaries:
        clean_h = main.clean_horse_name(h_name)
        if clean_h not in pedigree_db:
            continue
        hp = pedigree_db[clean_h]
        s_node = hp.get("Sire", {})
        h_sire = s_node.get("Horse", "") if isinstance(s_node, dict) else str(s_node)
        d_node = hp.get("Dam", {})
        h_damsire = get_mare_sire_from_pedigree(d_node) if isinstance(d_node, dict) else ""
        if h_damsire and main.clean_horse_name(h_damsire) in mare_sire_ancestry:
            cross_hit_sires.add(main.clean_horse_name(h_sire))

    unfiltered_structural_hits = []
    for st_name, p_data in all_profiles.items():
        clean_st = main.clean_horse_name(st_name)
        st_pedigree = pedigree_db.get(clean_st, {"Horse": st_name})
        if check_inbreeding_failsafe(st_pedigree, mare_pedigree, max_generation=3):
            continue
        has_cross_hit = clean_st in cross_hit_sires
        if has_cross_hit and clean_st not in [main.clean_horse_name(c["name"]) for c in active_pool]:
            unfiltered_structural_hits.append(st_name)

    suggestions = []
    for cand in sorted_pool:
        meta = get_profile_meta(cand["name"], all_profiles)
        suggestions.append({
            "name": cand["name"],
            "score": cand["score"],
            "rank": meta["rank"],
            "stud_fee": meta["fee_str"],
            "fee_num": meta["fee_num"],
            "has_lineage": has_lineage_options(cand["name"], all_profiles, budget_filter=fee_cap if fee_cap != sys.maxsize else None),
            "cross_meta": cand["cross_meta"],
            "crosses": cand.get("crosses", []),
            "reasons_by_tier": cand["reasons_by_tier"],
        })

    lineage_groups = []
    seen = set()
    budget = fee_cap if fee_cap != sys.maxsize else None
    for cand in sorted_pool:
        key = main.clean_horse_name(cand["name"])
        if key in seen:
            continue
        if has_lineage_options(cand["name"], all_profiles, budget_filter=budget):
            lineage_groups.append({"anchor": cand["name"], "variant": False})
            seen.add(key)
    for unfil_name in unfiltered_structural_hits:
        key = main.clean_horse_name(unfil_name)
        if key in seen:
            continue
        if has_lineage_options(unfil_name, all_profiles, budget_filter=budget):
            lineage_groups.append({"anchor": unfil_name, "variant": True})
            seen.add(key)

    return {
        "error": None,
        "mare": mare_display,
        "mare_key": matched_key,
        "damsire": clean_display_damsire or None,
        "surface": surface,
        "max_fee": None if fee_cap == sys.maxsize else fee_cap,
        "min_fee": min_fee,
        "suggestions": suggestions,
        "lineage_groups": lineage_groups,
        "broodmare": broodmare_context(pedigree_db, mare_name),
    }


def lineage_options_payload(stallion_name, all_profiles, budget_filter=None):
    st_clean = main.clean_horse_name(stallion_name)
    all_relatives = find_lineage_relatives(st_clean)
    sorted_relatives = sort_ancestor_list(all_relatives, all_profiles, budget_filter)
    options = []
    for relative in sorted_relatives:
        meta = get_profile_meta(relative, all_profiles)
        if meta["is_active"]:
            options.append({
                "name": relative,
                "rank": meta["rank"],
                "stud_fee": meta["fee_str"],
                "fee_num": meta["fee_num"],
            })
    return {"stallion": stallion_name, "options": options}


def build_hypo_report(pedigree_db, all_profiles, sire_name, dam_name, persist=False):
    dam_hit = main.lookup_pedigree(dam_name, pedigree_db)
    if dam_hit["ambiguous"]:
        return {"error": "ambiguous_year", "mare": dam_hit["clean_name"], "years": dam_hit["years"]}
    mare_pedigree, _ = lookup_mare_pedigree(pedigree_db, dam_name)
    if not mare_pedigree:
        return {"error": "not_found", "mare": dam_name}
    dam_display = re.sub(r'\s*\(\d{4}\)', '', mare_pedigree.get('Horse', dam_name)).strip()
    hypo_foal_name = f"{sire_name.title()} x {dam_display}"
    combined_pedigree = {
        "Horse": hypo_foal_name,
        "Sire": copy.deepcopy(main.pedigree_tree(sire_name, pedigree_db) or {"Horse": sire_name}),
        "Dam": copy.deepcopy(mare_pedigree),
    }
    if persist:
        hypofoals_manager.register_new_hypo_foal(
            sire_name=sire_name,
            dam_name=dam_name,
            combined_tree=combined_pedigree,
        )
    return {
        "error": None,
        "foal_name": hypo_foal_name,
        "sire": sire_name,
        "dam": mare_pedigree.get("Horse", dam_name),
        "pedigree": combined_pedigree,
        "inbreeding": main.compute_inbreeding(combined_pedigree),
    }


def top_crosses_payload(pedigree_db, stallion_name, limit=20):
    clean_target = main.clean_horse_name(stallion_name)
    horse_summaries = build_horse_summaries(load_stakes_data())
    crosses = {}
    status_weights = {"MG1W": 500, "G1W": 400, "MGSW": 300, "G2W": 250, "G3W": 200, "MSW": 150, "SW": 100}
    tier_order = ["MG1W", "G1W", "MGSW", "G2W", "G3W", "MSW", "SW"]
    for h_name, h in horse_summaries.items():
        clean_h = main.clean_horse_name(h_name)
        if clean_h not in pedigree_db:
            continue
        h_ped = pedigree_db[clean_h]
        sire_node = h_ped.get("Sire", {})
        h_sire = sire_node.get("Horse", "") if isinstance(sire_node, dict) else str(sire_node)
        if main.clean_horse_name(h_sire) != clean_target:
            continue
        dam_node = h_ped.get("Dam", {})
        h_damsire = get_mare_sire_from_pedigree(dam_node)
        if not h_damsire:
            continue
        clean_ds = re.sub(r"\s*\(\d{4}\)", "", h_damsire).strip().title()
        if clean_ds not in crosses:
            crosses[clean_ds] = {"score": 0, "winners": []}
        crosses[clean_ds]["score"] += status_weights.get(h["status"], 100)
        dam_name = dam_node.get("Horse", "") if isinstance(dam_node, dict) else str(dam_node)
        crosses[clean_ds]["winners"].append({
            "name": h_name,
            "status": h["status"],
            "dam": re.sub(r"\s*\(\d{4}\)", "", dam_name).strip(),
        })
    ranked = []
    for ds_name, data in sorted(crosses.items(), key=lambda x: -x[1]["score"]):
        lookup_key = main.clean_horse_name(ds_name)
        bms = BROODMARE_DATABASE.get(lookup_key) or {}
        ranked.append({
            "broodmare_sire": ds_name,
            "rank": bms.get("Rank"),
            "score": data["score"],
            "winners": sorted(data["winners"], key=lambda w: tier_order.index(w["status"]) if w["status"] in tier_order else 99),
        })
    return {"stallion": stallion_name, "crosses": ranked[:limit]}


def broodmare_context(pedigree_db, mare_name):
    mare_pedigree, matched = lookup_mare_pedigree(pedigree_db, mare_name)
    if not mare_pedigree:
        return None
    clean_mare = main.clean_horse_name(matched or mare_name)
    summaries = build_horse_summaries(load_stakes_data())
    own = None
    for h_name, h in summaries.items():
        if main.clean_horse_name(h_name) == clean_mare:
            own = h
            break
    progeny = []
    for h_name, h in summaries.items():
        clean_h = main.clean_horse_name(h_name)
        if clean_h not in pedigree_db:
            continue
        dam_node = pedigree_db[clean_h].get("Dam", {})
        dam_name = dam_node.get("Horse", "") if isinstance(dam_node, dict) else str(dam_node)
        if main.clean_horse_name(dam_name) != clean_mare:
            continue
        sire_node = pedigree_db[clean_h].get("Sire", {})
        sire_name = sire_node.get("Horse", "") if isinstance(sire_node, dict) else str(sire_node)
        progeny.append({
            "name": h_name,
            "status": h["status"],
            "sire": re.sub(r"\s*\(\d{4}\)", "", sire_name).strip(),
            "races": h["races"],
        })
    return {
        "mare": mare_pedigree.get("Horse", mare_name),
        "own": own,
        "progeny": progeny,
        "pedigree": None,
    }