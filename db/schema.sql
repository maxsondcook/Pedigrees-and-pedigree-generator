-- Crossr Railway Postgres schema (generated from crossr_core/railway_db.py).
-- The app and scripts/load_railway.py create these automatically.

CREATE TABLE IF NOT EXISTS crossr_table_versions (
    table_name TEXT PRIMARY KEY,
    version DOUBLE PRECISION NOT NULL,
    row_count BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS "stud_fees" (
    "Year" TEXT,
    "Stallion" TEXT,
    "Stud Fee" TEXT,
    "Farm" TEXT,
    "Source List" TEXT,
    "Notes" TEXT
);

CREATE INDEX IF NOT EXISTS "idx_stud_fees_key" ON "stud_fees" ("Year", "Stallion", "Source List");

CREATE TABLE IF NOT EXISTS "race_horses" (
    "id" TEXT,
    "pedigree_key" TEXT,
    "name_key" TEXT,
    "foal_year" TEXT,
    "display_name" TEXT,
    "foaled_in" TEXT,
    "breed" TEXT,
    "color" TEXT,
    "sex" TEXT,
    "foaled" TEXT,
    "sire" TEXT,
    "sire_refno" TEXT,
    "dam" TEXT,
    "dam_refno" TEXT,
    "damsire" TEXT,
    "damsire_refno" TEXT,
    "jockey" TEXT,
    "trainer" TEXT,
    "owner" TEXT,
    "breeder" TEXT,
    "best_class" TEXT,
    "equibase_refno" TEXT,
    "registry" TEXT,
    "profile_url" TEXT,
    "status" TEXT,
    "detail" TEXT,
    "fetched_at" TEXT,
    "queue_batch" TEXT
);

CREATE INDEX IF NOT EXISTS "idx_race_horses_key" ON "race_horses" ("id");

CREATE TABLE IF NOT EXISTS "race_seasons" (
    "id" TEXT,
    "horse_id" TEXT,
    "year" TEXT,
    "starts" TEXT,
    "firsts" TEXT,
    "seconds" TEXT,
    "thirds" TEXT,
    "highest_esf" TEXT,
    "earnings" TEXT,
    "earnings_per_start" TEXT
);

CREATE INDEX IF NOT EXISTS "idx_race_seasons_key" ON "race_seasons" ("id");

CREATE TABLE IF NOT EXISTS "race_starts" (
    "id" TEXT,
    "horse_id" TEXT,
    "race_date" TEXT,
    "track" TEXT,
    "track_code" TEXT,
    "country" TEXT,
    "race_number" TEXT,
    "race_name" TEXT,
    "grade" TEXT,
    "breed" TEXT,
    "place" TEXT,
    "esf" TEXT,
    "stakes_id" TEXT,
    "chart_url" TEXT,
    "video_url" TEXT
);

CREATE INDEX IF NOT EXISTS "idx_race_starts_key" ON "race_starts" ("id");

CREATE TABLE IF NOT EXISTS "breeding_seasons" (
    "breeding_year" TEXT,
    "stallion" TEXT,
    "mares_bred" TEXT,
    "reports_received" TEXT,
    "live_foals" TEXT,
    "live_foal_pct" TEXT,
    "state" TEXT,
    "source" TEXT
);

CREATE INDEX IF NOT EXISTS "idx_breeding_seasons_key" ON "breeding_seasons" ("breeding_year", "stallion");

CREATE TABLE IF NOT EXISTS "stallion_rankings" (
    "year" TEXT,
    "list" TEXT,
    "table_name" TEXT,
    "rank" TEXT,
    "stallion" TEXT,
    "sire" TEXT,
    "foaling_year" TEXT,
    "country" TEXT,
    "stallion_raw" TEXT,
    "source_file" TEXT,
    "stud_fee" TEXT,
    "stud_fee_season" TEXT,
    "farm" TEXT,
    "stud_fee_raw" TEXT,
    "runners" TEXT,
    "winners" TEXT,
    "repeat_winners" TEXT,
    "stakes_winners" TEXT,
    "stakes_winners_percent" TEXT,
    "stakes_winners_raw" TEXT,
    "stakes_wins" TEXT,
    "graded_stakes_winners" TEXT,
    "graded_stakes_winners_percent" TEXT,
    "graded_stakes_winners_raw" TEXT,
    "grade1_stakes_winners" TEXT,
    "grade1_stakes_winners_percent" TEXT,
    "grade1_stakes_winners_raw" TEXT,
    "stakes_horses" TEXT,
    "current_2yos" TEXT,
    "yearling_average" TEXT,
    "chief_earner" TEXT,
    "chief_earner_earnings" TEXT,
    "chief_earner_raw" TEXT,
    "year_earnings" TEXT,
    "earnings_share" TEXT,
    "dams" TEXT,
    "cumulative_stakes_winners" TEXT,
    "cumulative_foals" TEXT,
    "aei" TEXT,
    "comparable_index" TEXT,
    "all_surfaces_runners" TEXT,
    "all_surfaces_winners" TEXT,
    "all_surfaces_stakes_winners" TEXT,
    "turf_runners" TEXT,
    "turf_winners" TEXT,
    "turf_stakes_winners" TEXT,
    "north_america_earnings" TEXT,
    "europe_dubai_earnings" TEXT,
    "japan_hong_kong_earnings" TEXT,
    "region_earnings" TEXT,
    "international_stakes_winners" TEXT,
    "international_stakes_horses" TEXT,
    "crops" TEXT,
    "average_crop_size" TEXT,
    "crops_raw" TEXT,
    "foals" TEXT,
    "foals_basis" TEXT,
    "lifetime_yearlings_sold" TEXT,
    "lifetime_yearling_average" TEXT,
    "lifetime_yearlings_raw" TEXT,
    "yearling_window" TEXT,
    "window_yearlings_sold" TEXT,
    "window_yearling_average" TEXT,
    "window_yearlings_raw" TEXT
);

CREATE INDEX IF NOT EXISTS "idx_stallion_rankings_key" ON "stallion_rankings" ("year", "list", "table_name", "rank", "stallion", "source_file");

CREATE TABLE IF NOT EXISTS "graded_stakes" (
    "Race Name" TEXT,
    "Horse Name" TEXT,
    "Year Foaled" TEXT,
    "Sex" TEXT,
    "Place" TEXT,
    "Country" TEXT,
    "Track" TEXT,
    "Date" TEXT,
    "Distance" TEXT,
    "Age" TEXT,
    "Purse" TEXT,
    "Group" TEXT,
    "Race Conditions" TEXT,
    "Date (ISO)" TEXT,
    "Purse Source" TEXT,
    "Purse (Local)" TEXT,
    "Purse Currency" TEXT,
    "Distance (Metres)" TEXT,
    "Colour" TEXT,
    "Jockey" TEXT,
    "Horse Country Suffix" TEXT,
    "Foaling Year" TEXT,
    "race_id" TEXT,
    "Race Year" TEXT,
    "Grade" TEXT
);

CREATE INDEX IF NOT EXISTS "idx_graded_stakes_key" ON "graded_stakes" ("race_id", "Horse Name", "Place", "Date (ISO)");

CREATE TABLE IF NOT EXISTS "sales_lots" (
    "catalog_year" TEXT,
    "catalog_title" TEXT,
    "source_file" TEXT,
    "hip" TEXT,
    "name" TEXT,
    "name_key" TEXT,
    "sex" TEXT,
    "sex_letter" TEXT,
    "sire" TEXT,
    "sire_key" TEXT,
    "dam" TEXT,
    "dam_key" TEXT,
    "damsire" TEXT,
    "damsire_key" TEXT,
    "color" TEXT,
    "consignor" TEXT,
    "purchaser" TEXT,
    "barn" TEXT,
    "foaled_location" TEXT,
    "birth_year" TEXT,
    "price_raw" TEXT,
    "price_num" TEXT,
    "is_rna" TEXT,
    "is_out" TEXT,
    "is_fasig" TEXT
);

CREATE INDEX IF NOT EXISTS "idx_sales_lots_key" ON "sales_lots" ("source_file", "hip", "name_key");

CREATE TABLE IF NOT EXISTS pedigrees (
    key TEXT PRIMARY KEY,
    tree JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    payload TEXT NOT NULL,
    updated_at BIGINT NOT NULL
);

