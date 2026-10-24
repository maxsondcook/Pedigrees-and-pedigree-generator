-- Tables match the CSV headers in data/. Every column is text so blank
-- cells load as empty strings. Pedigrees, stallion cards, and
-- mares_bred_2025_by_stallion.py are not in this schema.

DROP TABLE IF EXISTS race_starts;
DROP TABLE IF EXISTS race_seasons;
DROP TABLE IF EXISTS race_horses;
DROP TABLE IF EXISTS breeding_seasons;
DROP TABLE IF EXISTS stallion_rankings;
DROP TABLE IF EXISTS graded_stakes;
DROP TABLE IF EXISTS sales_lots;
DROP TABLE IF EXISTS stud_fees;

CREATE TABLE stud_fees (
    "Year" text,
    "Stallion" text,
    "Stud Fee" text,
    "Farm" text,
    "Source List" text,
    "Notes" text
);

CREATE TABLE race_horses (
    id text PRIMARY KEY,
    pedigree_key text,
    name_key text,
    foal_year text,
    display_name text,
    foaled_in text,
    breed text,
    color text,
    sex text,
    foaled text,
    sire text,
    sire_refno text,
    dam text,
    dam_refno text,
    damsire text,
    damsire_refno text,
    jockey text,
    trainer text,
    owner text,
    breeder text,
    best_class text,
    equibase_refno text,
    registry text,
    profile_url text,
    status text,
    detail text,
    fetched_at text,
    queue_batch text
);

CREATE TABLE race_seasons (
    id text PRIMARY KEY,
    horse_id text,
    year text,
    starts text,
    firsts text,
    seconds text,
    thirds text,
    highest_esf text,
    earnings text,
    earnings_per_start text
);

CREATE TABLE race_starts (
    id text PRIMARY KEY,
    horse_id text,
    race_date text,
    track text,
    track_code text,
    country text,
    race_number text,
    race_name text,
    grade text,
    breed text,
    place text,
    esf text,
    stakes_id text,
    chart_url text,
    video_url text
);

CREATE TABLE breeding_seasons (
    breeding_year text,
    stallion text,
    mares_bred text,
    reports_received text,
    live_foals text,
    live_foal_pct text,
    state text,
    source text
);

CREATE TABLE stallion_rankings (
    year text,
    list text,
    table_name text,
    rank text,
    stallion text,
    sire text,
    foaling_year text,
    country text,
    stallion_raw text,
    source_file text,
    stud_fee text,
    stud_fee_season text,
    farm text,
    stud_fee_raw text,
    runners text,
    winners text,
    repeat_winners text,
    stakes_winners text,
    stakes_winners_percent text,
    stakes_winners_raw text,
    stakes_wins text,
    graded_stakes_winners text,
    graded_stakes_winners_percent text,
    graded_stakes_winners_raw text,
    grade1_stakes_winners text,
    grade1_stakes_winners_percent text,
    grade1_stakes_winners_raw text,
    stakes_horses text,
    current_2yos text,
    yearling_average text,
    chief_earner text,
    chief_earner_earnings text,
    chief_earner_raw text,
    year_earnings text,
    earnings_share text,
    dams text,
    cumulative_stakes_winners text,
    cumulative_foals text,
    aei text,
    comparable_index text,
    all_surfaces_runners text,
    all_surfaces_winners text,
    all_surfaces_stakes_winners text,
    turf_runners text,
    turf_winners text,
    turf_stakes_winners text,
    north_america_earnings text,
    europe_dubai_earnings text,
    japan_hong_kong_earnings text,
    region_earnings text,
    international_stakes_winners text,
    international_stakes_horses text,
    crops text,
    average_crop_size text,
    crops_raw text,
    foals text,
    foals_basis text,
    lifetime_yearlings_sold text,
    lifetime_yearling_average text,
    lifetime_yearlings_raw text,
    yearling_window text,
    window_yearlings_sold text,
    window_yearling_average text,
    window_yearlings_raw text
);

CREATE TABLE graded_stakes (
    "Race Name" text,
    "Horse Name" text,
    "Year Foaled" text,
    "Sex" text,
    "Place" text,
    "Country" text,
    "Track" text,
    "Date" text,
    "Distance" text,
    "Age" text,
    "Purse" text,
    "Group" text,
    "Race Conditions" text,
    "Date (ISO)" text,
    "Purse Source" text,
    "Purse (Local)" text,
    "Purse Currency" text,
    "Distance (Metres)" text,
    "Colour" text,
    "Jockey" text,
    "Horse Country Suffix" text,
    "Foaling Year" text,
    race_id text,
    "Race Year" text,
    "Grade" text
);

CREATE TABLE sales_lots (
    catalog_year text,
    catalog_title text,
    source_file text,
    hip text,
    name text,
    name_key text,
    sex text,
    sex_letter text,
    sire text,
    sire_key text,
    dam text,
    dam_key text,
    damsire text,
    damsire_key text,
    color text,
    consignor text,
    purchaser text,
    barn text,
    foaled_location text,
    birth_year text,
    price_raw text,
    price_num text,
    is_rna text,
    is_out text,
    is_fasig text
);
