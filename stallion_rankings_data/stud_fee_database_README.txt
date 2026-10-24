Stud Fee Database
=================
Built from BloodHorse year-ranking CSVs under:
  /Users/maxsoncook/Desktop/stallion_rankings_data

Output
------
  /Users/maxsoncook/Desktop/stallion_rankings_data/stud_fee_database.csv

Counts
------
  Output rows:              15,368
  Unique stallion-years:    15,368
  Years covered:            2001–2026 (26 years)
  N/A stud fees:            5,629
  Private stud fees:        426
  Conflict groups:          0  (same stallion+year, different fees)
  Conflict rows:            0
  Conflicts resolved (RP):  213
  Unresolved (no RP fee):   0
  RP year-not-matched:      0

How columns were parsed
-----------------------
Year is the ranking-folder / filename prefix (2001–2026), not the year printed
inside a fee header. Some first-crop lists label an earlier inaugural fee
(e.g. 2001 list column "1998 Stud Fee / Farm"); AEI lists often label the
next covering season (e.g. 2001 AEI column "2002 Stud Fee"). Those header
years are not copied into Year.

Combined "Stud Fee / Farm" cells (newline- or space-separated) were split:
  $60,000 + WinStar Farm, KY  ->  Stud Fee=$60,000, Farm=WinStar Farm, KY
  N/A + KY                    ->  Stud Fee=N/A, Farm=KY
  N/A                         ->  Stud Fee=N/A, Farm=N/A
  Died 2002 + Claiborne Farm  ->  Stud Fee=N/A, Farm=Claiborne Farm, Notes=Died 2002
  Private / private fee       ->  Stud Fee=Private, farm kept when present
  Pensioned / Retired / To Be Announced  ->  fee N/A, status in Notes,
  farm kept when a farm/state remained.

Split AEI 2001–2008 columns:
  "YYYY Stud Fee" + farm embedded in
  "Stallion (Foreign foaled), Year, Sire, Where Stands"
  e.g. DANZIG (77, Northern Dancer), Claiborne Farm, KY

Combined-style source rows extracted: 21,441
Split-style source rows extracted:    509

Deduping
--------
Same stallion+year with the same fee is collapsed to one row. Source List
names are joined with "; ". The longest / most complete farm string is kept;
other distinct farms are recorded as "Also listed at: ..." in Notes.
Different fees for the same stallion+year are all kept and tagged
"Conflict: different stud fees for same stallion-year".

Missing values are N/A. Encoding is UTF-8 with BOM.

Fee conflicts were checked against Racing Post stallion fee-history pages.
A year-specific RP fee collapses the two conflict rows into one. Private on
Racing Post is stored as Stud Fee=Private. If RP has a page but no fee for
that covering year, both rows stay and Notes say year-not-matched. If RP has
no page or no fee at all, both rows stay tagged Unresolved: no RP fee.
Misses: stud_fee_rp_misses.csv. HTML cache: rp_cache/html/.
Remaining conflicts after the first RP pass were resolved from Racing Post fee-history tables (Google-indexed historical years) plus BloodHorse, TDN, DRF, Lane's End roster, and farm-ad sources. User-supplied 2001 ground truth was applied for Avenue of Flags ($10,000, Golden Eagle Farm, Ramona, CA), Bertrando ($30,000), Danzig (Private), General Meeting ($50,000), and Cee's Tizzy via the RP fee-history URL pattern.

Fee / name columns used
-----------------------
Fee:
  - '10 Stud Fee / Farm
  - '11 Stud Fee / Farm
  - '12 Stud Fee / Farm
  - '13 Stud Fee / Farm
  - '14 Stud Fee / Farm
  - '15 Stud Fee / Farm
  - '16 Stud Fee / Farm
  - '17 Stud Fee / Farm
  - '18 Stud Fee / Farm
  - '19 Stud Fee / Farm
  - '20 Stud Fee / Farm
  - '21 Stud Fee / Farm
  - '22 Stud Fee / Farm
  - '23 Stud Fee / Farm
  - '25 Stud Fee / Farm
  - '26 Stud Fee / Farm
  - 1998 Stud Fee / Farm
  - 1999 Stud Fee / Farm
  - 2000 Stud Fee / Farm
  - 2002 Stud Fee
  - 2003 Stud Fee
  - 2003 Stud Fee / Farm
  - 2004 Stud Fee
  - 2005 Stud Fee
  - 2006 Stud Fee
  - 2007 Stud Fee
  - 2007 Stud Fee / Farm
  - 2008 Stud Fee
  - 2009 Stud Fee
  - 2009 Stud Fee / Farm
  - Stud Fee / Farm

Stallion:
  - Stallion
  - Stallion (Foreign foaled), Year, Sire, Where Stands

Lists used (156 files)
--------------------------------------------
  Leading First Crop Sires (26 files), Leading Second-Crop Sires (26 files), Leading Sire Rankings (26 files), Leading Sires by AEI (26 files), Leading Third-Crop Sires (26 files), Leading Two-Year-Old Sires (26 files)

Lists skipped — no fee/farm column (572 files)
-------------------------------------------------------------------------
  Leading Broodmare Sires (26 files), Leading International 2ndCrop Sires (26 files), Leading International 2ndCrop Sires-Europe&Dubai (26 files), Leading International 2ndCrop Sires-Japan&HongKong (26 files), Leading International 2ndCrop Sires-NorthAmerica (26 files), Leading International 3rdCrop Sires (26 files), Leading International 3rdCrop Sires-Europe&Dubai (26 files), Leading International 3rdCrop Sires-Japan&HongKong (26 files), Leading International 3rdCrop Sires-NorthAmerica (26 files), Leading International First-Crop Sires (26 files), Leading International First-CropSires-Europe&Dubai (26 files), Leading International First-CropSires-NorthAmerica (26 files), Leading International Sires (26 files), Leading International Sires-Europe&Dubai (26 files), Leading International Sires-Japan&Hong Kong (26 files), Leading International Sires-North America (26 files), Leading International Two-Year-Old Sires (26 files), Leading Turf Sires (26 files), LeadingInternational FirstCropSires-Japan&HongKong (26 files), LeadingInternational TwoYearOldSires-Europe&Dubai (25 files), LeadingInternational TwoYearOldSires-NorthAmerica (25 files), LeadingInternationalTwoYearOldSires-Europe&Dubai (1 files), LeadingInternationalTwoYearOldSires-Japan&HongKong (26 files), LeadingInternationalTwoYearOldSires-NorthAmerica (1 files)

Leftover columns ignored
------------------------
  - #
  - (%)
  - 01 Earnings
  - 02 Earnings
  - 03 Earnings
  - 04 Earnings
  - 05 Earnings
  - 06 Earnings
  - 07 Earnings
  - 08 Earnings
  - 09 Earnings
  - 10 Earnings
  - 11 Earnings
  - 12 Earnings
  - 13 Earnings
  - 14 Earnings
  - 15 Earnings
  - 16 Earnings
  - 17 Earnings
  - 18 Earnings
  - 19 Earnings
  - 1998–2001 Yearlings Sold / Average
  - 1999–2002 Yearlings Sold / Average
  - 20 Earnings
  - 2000–2003 Yearlings Sold / Average
  - 2001–2004 Yearlings Sold / Average
  - 2002–2005 Yearlings Sold / Average
  - 2003–2006 Yearlings Sold / Average
  - 2004–2007 Yearlings Sold / Average
  - 2005–2008 Yearlings Sold / Average
  - 21 Earnings
  - 22 Earnings
  - 23 Earnings
  - 24 Earnings
  - 25 Earnings
  - 26 Earnings
  - AE Index
  - AEI
  - Avg.
  - BT SHs
  - BT SWrs
  - BT SWs
  - BT Wnrs
  - CI
  - Chief Earner (Earnings)
  - Comp Index
  - Crops
  - Crops / Avg Size
  - Current 2YOs
  - Foals
  - G1SWrs
  - GSWrs
  - Grade 1 Stakes Winners
  - Graded Stakes Winners
  - Lifetime Yearlings Sold / Average
  - N.H. Named Foals
  - Named Foals
  - Rank
  - Rnrs
  - Rpt. Wnrs
  - SHs
  - SWrs
  - Sold
  - Stakes Winners
  - Wnrs
  - Yearling Average

Not read: bloodhorse_sirelists/ (scraper, cache, LIST_MAPPING.md, code).
