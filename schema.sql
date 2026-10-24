-- Postgres schema for the breeding and sales program.
-- Column names match the CSVs in placeholderdatabase/.
-- Apply with scripts/load_railway.py once Railway is back.
-- Do not run that script against a live Railway database until the project is up.

CREATE TABLE IF NOT EXISTS industry_roles (
    role_name TEXT PRIMARY KEY,
    description TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id BIGINT PRIMARY KEY,
    display_name TEXT NOT NULL,
    email TEXT,
    industry_role TEXT REFERENCES industry_roles (role_name),
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS clients (
    client_id BIGINT PRIMARY KEY,
    account_id BIGINT REFERENCES accounts (account_id),
    client_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS client_preferences (
    preference_id BIGINT PRIMARY KEY,
    client_id BIGINT REFERENCES clients (client_id),
    sex TEXT,
    foaled TEXT,
    surface TEXT,
    min_stud_fee INTEGER,
    max_stud_fee INTEGER,
    sire_name TEXT,
    requires_producer_note INTEGER
);

CREATE TABLE IF NOT EXISTS horses (
    horse_id BIGINT PRIMARY KEY,
    name TEXT,
    name_key TEXT,
    display_name TEXT,
    foaling_year INTEGER,
    sex TEXT,
    color TEXT,
    country TEXT,
    sire_name TEXT,
    dam_name TEXT,
    class_label TEXT,
    height TEXT,
    conformation TEXT
);

CREATE INDEX IF NOT EXISTS horses_name_key_idx ON horses (name_key);

-- Sire line and dam line for a subject horse. generation 1 is the parent.
-- relation is sire, first_dam, second_dam, third_dam, fourth_dam, damsire, and so on.
CREATE TABLE IF NOT EXISTS pedigree_lines (
    line_id BIGINT PRIMARY KEY,
    subject_name TEXT,
    subject_key TEXT,
    line_side TEXT,
    generation INTEGER,
    relation TEXT,
    ancestor_name TEXT,
    ancestor_year INTEGER,
    class_label TEXT
);

CREATE INDEX IF NOT EXISTS pedigree_lines_subject_idx ON pedigree_lines (subject_key);

CREATE TABLE IF NOT EXISTS sales (
    sale_id BIGINT PRIMARY KEY,
    sale_company TEXT,
    sale_title TEXT,
    sale_year INTEGER,
    sale_kind TEXT,
    month_index INTEGER,
    source_file TEXT
);

-- Flat sale result. Mirrors sales_database.db sale_records
-- (sale_title, sale_year, hip, price_num, is_rna, is_out)
-- plus the Keeneland / Fasig-Tipton CSV columns the sales engine reads.
CREATE TABLE IF NOT EXISTS sale_results (
    result_id BIGINT PRIMARY KEY,
    sale_title TEXT,
    sale_year INTEGER,
    hip TEXT,
    horse_name TEXT,
    sex TEXT,
    sire TEXT,
    dam TEXT,
    sire_of_dam TEXT,
    birth_year TEXT,
    price_num DOUBLE PRECISION,
    price_raw TEXT,
    is_rna INTEGER,
    is_out INTEGER,
    purchaser TEXT,
    consignor TEXT,
    color TEXT,
    foaled TEXT,
    sold_as TEXT,
    source_file TEXT
);

CREATE INDEX IF NOT EXISTS sale_results_title_year_idx ON sale_results (sale_title, sale_year);

-- Upcoming catalog hip. Columns follow Analyzed Sales
-- (HIP, HORSE NAME, SEX, SIRE, DAM, SIRE OF DAM, YEAR OF BIRTH, FOALED,
--  SOLD AS, COVERING SIRE, NOTES, CROSS SUCCESS, DAM SUCCESS, RACING SUCCESS, STARRED)
-- plus color and consignor from the Fasig / Keeneland catalog shape.
CREATE TABLE IF NOT EXISTS catalog_hips (
    hip_id BIGINT PRIMARY KEY,
    sale_title TEXT,
    sale_year INTEGER,
    hip TEXT,
    horse_name TEXT,
    sex TEXT,
    color TEXT,
    sire TEXT,
    dam TEXT,
    sire_of_dam TEXT,
    year_of_birth TEXT,
    foaled TEXT,
    sold_as TEXT,
    covering_sire TEXT,
    consignor TEXT,
    notes TEXT,
    cross_success TEXT,
    dam_success_racer TEXT,
    dam_success_producer TEXT,
    racing_success TEXT,
    starred TEXT,
    source_file TEXT
);

-- Stallion profile card. Nested race-record and progeny blocks are JSON text,
-- matching the dictionaries in the former stallion_profiles module.
CREATE TABLE IF NOT EXISTS stallion_stats (
    stallion_name TEXT PRIMARY KEY,
    farm TEXT,
    year_born INTEGER,
    stud_duty_year INTEGER,
    stud_fee INTEGER,
    status TEXT,
    surface TEXT,
    height TEXT,
    conformation TEXT,
    major_wins TEXT,
    career_highlight TEXT,
    race_record TEXT,
    progeny_racing_statistics TEXT,
    progeny_earnings_statistics TEXT,
    legacy_progeny_stats TEXT,
    sire_rank INTEGER,
    mares_bred_2025 INTEGER
);

-- Broodmare-sire ranking rows from broodmare_sire_data.broodmare_sire_raw.
CREATE TABLE IF NOT EXISTS broodmare_sire_stats (
    rank INTEGER PRIMARY KEY,
    stallion TEXT,
    lineage TEXT,
    dams INTEGER,
    rnrs INTEGER,
    wnrs INTEGER,
    chief_earner TEXT,
    chief_earners_earnings INTEGER,
    earnings_2026 INTEGER,
    cum_swrs INTEGER,
    aei DOUBLE PRECISION,
    comp_index DOUBLE PRECISION,
    cum_foals INTEGER
);

-- Mares-bred report. region is the grouping key from mares_bred_2025_by_stallion.py.
CREATE TABLE IF NOT EXISTS mares_bred (
    stallion TEXT,
    mares_bred_2025 INTEGER,
    state_prov TEXT,
    live_foal_percentage_for_2025_foals TEXT,
    live_foal_percentage_for_2024_foals TEXT,
    region TEXT
);

-- graded_stakes_winners.csv
CREATE TABLE IF NOT EXISTS graded_stakes_winners (
    race_name TEXT,
    race_year INTEGER,
    horse_name TEXT,
    foaling_year INTEGER,
    sex TEXT,
    country TEXT,
    track TEXT,
    race_date TEXT,
    distance TEXT,
    age TEXT,
    purse TEXT,
    grade TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    note_id BIGINT PRIMARY KEY,
    account_id BIGINT REFERENCES accounts (account_id),
    sale_title TEXT,
    hip TEXT,
    body TEXT,
    source TEXT,
    updated_at TEXT
);

-- Hypothetical mating index. pedigree_json is the nested pedigree the hypomating engine stores.
CREATE TABLE IF NOT EXISTS hypothetical_matings (
    mating_key TEXT PRIMARY KEY,
    horse_name TEXT,
    sire_name TEXT,
    dam_name TEXT,
    pedigree_json TEXT
);
