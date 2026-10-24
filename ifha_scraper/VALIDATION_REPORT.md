# AGENT 3 ("Validator") — validation report

**Status: FINAL**  — generated 2026-10-05 20:32:41Z

- Years requested: `2003`–`2026` (24 years)
- Years with data: 24 (2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026)
- Years with **no** data: none
- Rows written: **90,518** across **30,390** races
- Uncached detail pages omitted: **0**
- Purse policy: **`--purse-source hybrid`**
- Output: `/Users/maxsoncook/Desktop/graded_stakes_results - Sheet1.csv`, `/Users/maxsoncook/Desktop/Pedigrees and pedigree Generator/ifha_scraper/ifha_graded_stakes_2003_2026.csv`
- Encoding: **UTF-8 with BOM** (`utf-8-sig`); missing values are the literal string `N/A`
- Cache at report time: **30,740** of 30,740 files

## 1. Per-year coverage

| Year | Rows | Races | G1 | G2 | G3 |
|---|---|---|---|---|---|
| 2003 | 928 | 324 | 826 | 72 | 30 |
| 2004 | 4552 | 1532 | 1135 | 1397 | 2020 |
| 2005 | 4178 | 1425 | 1038 | 1239 | 1901 |
| 2006 | 4107 | 1394 | 954 | 1288 | 1865 |
| 2007 | 4508 | 1559 | 1130 | 1330 | 2048 |
| 2008 | 3705 | 1270 | 914 | 1098 | 1693 |
| 2009 | 4427 | 1480 | 1133 | 1282 | 2012 |
| 2010 | 4342 | 1450 | 1112 | 1247 | 1983 |
| 2011 | 4126 | 1379 | 1088 | 1194 | 1844 |
| 2012 | 3811 | 1273 | 896 | 1121 | 1794 |
| 2013 | 3892 | 1297 | 892 | 1108 | 1892 |
| 2014 | 4391 | 1462 | 1139 | 1246 | 2006 |
| 2015 | 4767 | 1597 | 1295 | 1338 | 2134 |
| 2016 | 4376 | 1461 | 1166 | 1262 | 1948 |
| 2017 | 4270 | 1423 | 1020 | 1235 | 2015 |
| 2018 | 3933 | 1313 | 1034 | 1132 | 1767 |
| 2019 | 3552 | 1187 | 942 | 1022 | 1588 |
| 2020 | 2726 | 910 | 792 | 811 | 1123 |
| 2021 | 3775 | 1261 | 1159 | 1059 | 1557 |
| 2022 | 3797 | 1266 | 1141 | 1042 | 1614 |
| 2023 | 3506 | 1173 | 941 | 1010 | 1555 |
| 2024 | 3460 | 1155 | 902 | 1012 | 1546 |
| 2025 | 3128 | 1043 | 776 | 847 | 1505 |
| 2026 | 2261 | 756 | 523 | 601 | 1137 |

Median rows/year across years not already known to be sparse: **4,107**.

### Anomalous years

| Year | Rows | Races | vs median | Known/expected? | Verdict |
|---|---|---|---|---|---|
| 2003 | 928 | 324 | 23% | yes | IFHA holds only ~24 G2 and ~10 G3 races for 2003 (324 total vs ~1,400 in later years). Source-data gap, confirmed by Agent 1's per-year x group census. |
| 2020 | 2726 | 910 | 66% | yes | COVID-19 cancellations. IFHA lists 976 races for 2020, so the shortfall against other years is real racing history, not a scrape bug. |
| 2026 | 2261 | 756 | 55% | yes | Partial year: 760 races carded, and races dated after the scrape have no published result yet. |

## 2. Deduplication

Key: `Date + Track + Race Name + Group` (the user's stated key). `racepid` is **not** a unique key for a physical race, so this step is mandatory, not cosmetic.

- Duplicate races collapsed: **326**
- Rows dropped: **961** (of 91,479 parsed)
- Collapses where the two pids had **identical** finishers: 324
- Collapses where the finishers **differed** (empty placeholder dropped in favour of a copy with results): 2

Within a cluster of *identical* finishers the lower racepid is kept. Two pids that share the key but have different finishers are kept as distinct races (e.g. Blue Diamond Prelude colts vs fillies). An empty placeholder never replaces a copy that has results.

| Date | Track | Race | Grp | Kept pid | Dropped pid | Identical results | Rows dropped |
|---|---|---|---|---|---|---|---|
| 2004-01-11 | Cidade Jardim | Grande Premio Presidente do Jockey Club-Antonio Grisi Filho | G2 | 41652 | 42042 | yes | 3 |
| 2004-02-07 | Caulfield | AUTUMN STAKES | G3 | 38698 | 39296 | yes | 3 |
| 2004-02-28 | Hipodromo Argentino De Palermo | Clasico Vicente Casares | G2 | 38763 | 38958 | yes | 3 |
| 2004-03-27 | Nad Al Sheba | Dubai Duty Free | G1 | 423 | 42771 | yes | 3 |
| 2004-04-17 | Randwick | Frank Packer Plate | G3 | 39077 | 39078 | yes | 3 |
| 2004-07-11 | HOL | Milady Breeders' Cup H. | G1 | 38882 | 39926 | yes | 3 |
| 2004-07-24 | Ascot | King George VI and Queen Elizabeth Diamond S. | G1 | 126 | 40404 | yes | 3 |
| 2004-08-08 | Curragh | Phoenix S. [Independent Waterford Wedgwood] | G1 | 38847 | 39834 | yes | 3 |
| 2004-09-11 | Rosehill | Kingston Town S. | G3 | 39174 | 39176 | yes | 3 |
| 2004-09-11 | Rosehill | Research S. | G3 | 39172 | 39173 | yes | 3 |
| 2004-09-16 | Newcastle | Newcastle Cup | G3 | 39181 | 39182 | yes | 3 |
| 2004-09-18 | Morphettville | SPRING STAKES | G3 | 39188 | 39189 | yes | 3 |
| 2004-09-18 | TP | Turfway Breeders' Cup S. | G3 | 38315 | 39570 | yes | 3 |
| 2004-09-19 | BEL | Futurity S. | G2 | 622 | 39044 | yes | 3 |
| 2004-10-09 | BEL | Beldame S. | G1 | 228 | 39927 | yes | 3 |
| 2004-11-27 | Ascot | W.A. GUINEAS | G2 | 39253 | 39254 | yes | 3 |
| 2004-12-04 | Kenilworth | Cape Fillies Classic | G1 | 39460 | 39461 | yes | 1 |
| 2004-12-18 | Randwick | Villiers S. | G2 | 39262 | 39263 | yes | 3 |
| 2005-01-01 | Flemington | STANDISH HANDICAP | G3 | 39269 | 39270 | yes | 3 |
| 2005-01-08 | Caulfield | RUBITON STAKES | G3 | 39273 | 39274 | yes | 3 |
| 2005-02-05 | Rosehill | Frederick Clissold H. | G3 | 41006 | 42428 | yes | 3 |
| 2005-02-19 | Warwick Farm | Liverpool City Cup | G3 | 39304 | 41008 | yes | 3 |
| 2005-03-12 | Rosehill | MAGIC NIGHT STAKES | G2 | 39334 | 39335 | yes | 3 |
| 2005-03-26 | Randwick | AJC AUSTRALIAN DERBY | G1 | 39351 | 39936 | yes | 3 |
| 2005-04-24 | Rome | Premio Parioli-Italian Two Thousand Guineas | G2 | 40365 | 43693 | yes | 3 |
| 2005-04-30 | Newmarket | THE Ultimatepoker.com 2000 GUINEAS STAKES | G1 | 40186 | 40191 | yes | 3 |
| 2005-05-07 | Eagle Farm | QUEENSLAND GUINEAS | G2 | 39386 | 39387 | yes | 3 |
| 2005-08-05 | Hipodromo Argentino De Palermo | Carlos Menditeguy | G3 | 40792 | 40793 | yes | 3 |
| 2005-08-05 | Hipodromo Argentino De Palermo | Carlos Menditeguy | G3 | 40792 | 40794 | yes | 3 |
| 2005-08-05 | Hipodromo Argentino De Palermo | Carlos Menditeguy | G3 | 40792 | 40795 | yes | 3 |
| 2005-09-10 | Moonee Valley | MANIKATO STAKES | G1 | 40827 | 40828 | yes | 3 |
| 2005-09-17 | Rosehill | Edgell Hill S. | G2 | 41089 | 42332 | yes | 3 |
| 2005-09-17 | Rosehill | Woolworths Good Taste Magazine Gloaming S. | G3 | 40994 | 42335 | yes | 3 |
| 2005-10-01 | San Isidro | Cyllene | G2 | 40878 | 40879 | yes | 3 |
| 2005-10-01 | San Isidro | Cyllene | G2 | 40878 | 40880 | yes | 3 |
| 2005-10-01 | San Isidro | Cyllene | G2 | 40878 | 40881 | yes | 3 |
| 2005-10-08 | Caulfield | Dodo Schillaci S. | G2 | 41133 | 42365 | yes | 3 |
| 2005-10-22 | Moonee Valley | Waterford Crystal Mile | G2 | 41139 | 41175 | yes | 3 |
| 2005-11-05 | San Isidro | Enrique Acebal | G1 | 40898 | 40899 | yes | 3 |
| 2005-11-05 | San Isidro | Enrique Acebal | G1 | 40898 | 40900 | yes | 3 |
| 2005-11-05 | San Isidro | Enrique Acebal | G1 | 40898 | 40901 | yes | 3 |
| 2005-12-17 | CRC | W. L. McKnight H. | G2 | 40339 | 40340 | yes | 3 |
| 2006-01-15 | Gavea | Grande Premio Jose Buarque de Macedo | G3 | 42045 | 42046 | yes | 3 |
| 2006-02-04 | Flemington | The Vanity | G3 | 41063 | 42419 | yes | 3 |
| 2006-03-05 | Gavea | Grande Premio Presidente Arthur da Costa e Silva | G3 | 42041 | 42043 | yes | 3 |
| 2006-03-25 | TP | Bourbonette Breeders' Cup S. | G3 | 40940 | 41568 | yes | 3 |
| 2006-03-25 | Tauranga | First Sovereign Trust Japan/New Zealand Trophy | G2 | 43875 | 43876 | yes | 3 |
| 2006-04-08 | Cheltenham | Auraria S. | G3 | 39079 | 41033 | yes | 3 |
| 2006-04-21 | Club Hipico | Cotejo de Potrillos | G3 | 41372 | 46769 | yes | 3 |
| 2006-04-29 | Sandown Park | Betfred Classic Trial | G3 | 42168 | 42169 | yes | 3 |
| 2006-06-04 | Gavea | Grande Premio Marciano de Aguiar Moreir | G2 | 42008 | 42009 | yes | 3 |
| 2006-06-25 | Gavea | Grande Premio Associacao Brasileira dos Criadores e Proprietarios do Cavalo de Corrida | G1 | 42005 | 42006 | yes | 3 |
| 2006-08-18 | DMR | Rancho Bernardo H. | G3 | 41294 | 41353 | yes | 3 |
| 2006-08-22 | York | Juddmonte International S. | G1 | 42095 | 42113 | yes | 3 |
| 2006-09-08 | York | Irish Thoroughbred Marketing Park Hill S. | G2 | 42154 | 42155 | yes | 3 |
| 2006-09-30 | BEL | Kelso Breeders' Cup H. | G2 | 41257 | 41259 | yes | 3 |
| 2006-10-14 | Arawa Park | Lion Red Plate | G3 | 43812 | 43814 | yes | 1 |
| 2006-11-25 | Ellerslie | Eagle Technology Counties Cup | G2 | 43826 | 43827 | yes | 1 |
| 2006-12-16 | Awapuni | Ezibuy Eulogy S. | G3 | 43834 | 43835 | yes | 1 |
| 2007-01-01 | SA | Monrovia H. | G3 | 41258 | 42748 | yes | 3 |

_…and 266 more; the full list is in `validation_issues.csv` under `duplicate_race_collapsed`._

## 3. Row-level sanity checks

| Check | Result |
|---|---|
| Races | 30,390 |
| Finisher-row distribution | 0 rows: 373 races, 2 rows: 5 races, 3 rows: 29,913 races, 4 rows: 99 races |
| Races with no published result | 373 (source publishes none; kept with `N/A` finishers) |
| Races with a dead heat (repeated placing) | 249 |
| Races with an unexpected field size | 5 |
| Rows with a blank Horse Name despite `has_results` | 0 |
| Horse age range (min / median / max) | 2 / 4 / 13 |
| Ages outside 2–12 | 1 |
| Rows with a $0 purse | 999 (present in the source; flagged, kept) |
| Rows with no purse at all | 0 |

## 4. Text cleaning and encoding

Every field passes through `normalize.clean_text`: HTML entities (`&nbsp;`, `&amp;`, numeric), non-breaking spaces, collapsed whitespace, stray wrapping quotes. **Trailing periods are preserved** — 41,996 race names legitimately end in one (`Ack Ack S.`).

Post-write audit of the output strings: `no problems found`.

The source is cp1252 and carries `£ ¥ €` plus accented names; the CSV is written **UTF-8 with BOM** so Excel and Google Sheets auto-detect it.

## 5. Purse source

Three policies, selected with `--purse-source`:

| Mode | Rule |
|---|---|
| `site` | always IFHA's own contemporaneous `(*$USD)` figure |
| `normalized` | always `normalize.py`'s ECB annual-average conversion |
| `hybrid` **(default)** | IFHA's figure, except fall back to the normalized one where the two disagree by >25% **and** the normalized rate's provenance is `ecb` |

Why hybrid: IFHA converted every 2015 Brazilian purse at ~2.657 BRL/USD — the **2014** average — when the 2015 ECB average was 3.336. The site figure is stale there and we have real ECB data to prove it.

| Purse Source value | Rows | Meaning |
|---|---|---|
| site | 57,565 | IFHA's own USD figure |
| usd_native | 29,194 | purse already in USD; no conversion needed |
| normalized_site_missing | 2,436 | IFHA offered no USD figure |
| normalized_stale_site | 1,323 | **hybrid override** — IFHA's figure contradicted by real ECB data |

## 6. Independent correctness spot-checks

These compare the CSV against results the author knows independently of this pipeline. Agent 2 already verified 2015, so every fixture here is from another year.

| Year | Race (match) | Expected winner | Status | Winner in CSV | Date in CSV | Note |
|---|---|---|---|---|---|---|
| 2003 | breeders' cup classic | Pleasantly Perfect | pass | Pleasantly Perfect | 2003-10-25 |  |
| 2004 | breeders' cup classic | Ghostzapper | pass | Ghostzapper | 2004-10-30 |  |
| 2009 | breeders' cup classic | Zenyatta | pass | Zenyatta | 2009-11-07 |  |
| 2010 | breeders' cup classic | Blame | pass | Blame | 2010-11-06 |  |
| 2022 | breeders' cup classic | Flightline | pass | Flightline | 2022-11-05 |  |
| 2005 | kentucky derby | Giacomo | pass | Giacomo | 2005-05-07 |  |
| 2007 | kentucky derby | Street Sense | pass | Street Sense | 2007-05-05 |  |
| 2008 | kentucky derby | Big Brown | pass | Big Brown | 2008-05-03 |  |
| 2009 | preakness | Rachel Alexandra | pass | Rachel Alexandra | 2009-05-16 |  |
| 2009 | belmont s | Summer Bird | pass | Summer Bird | 2009-06-06 |  |
| 2004 | derby s | North Light | pass | North Light | 2004-06-05 |  |
| 2007 | arc de triomphe | Dylan Thomas | pass | Dylan Thomas | 2007-10-07 |  |
| 2008 | arc de triomphe | Zarkava | pass | Zarkava | 2008-10-05 |  |
| 2009 | arc de triomphe | Sea The Stars | pass | Sea The Stars | 2009-10-04 |  |
| 2010 | arc de triomphe | Workforce | pass | Workforce | 2010-10-03 |  |
| 2012 | queen anne | Frankel | pass | Frankel | 2012-06-19 |  |
| 2012 | diamond jubilee | Black Caviar | pass | Black Caviar | 2012-06-23 |  |
| 2005 | dubai world cup | Roses In May | pass | Roses in May | 2005-03-26 |  |
| 2006 | dubai world cup | Electrocutionist | pass | Electrocutionist | 2006-03-25 |  |
| 2007 | dubai world cup | Invasor | pass | Invasor | 2007-03-31 |  |
| 2009 | dubai world cup | Well Armed | pass | Well Armed | 2009-03-28 |  |
| 2007 | japan cup | Admire Moon | pass | Admire Moon | 2007-11-25 |  |
| 2006 | melbourne cup | Delta Blues | not_found |  |  | name matched 3 row(s) but none on 2006-11-07 |
| 2008 | melbourne cup | Viewed | pass | Viewed | 2008-11-04 |  |
| 2009 | cox plate | So You Think | pass | So You Think | 2009-10-24 |  |
| 2017 | cox plate | Winx | pass | Winx | 2017-10-28 |  |

Tally: `{'pass': 25, 'not_found': 1}`

## 7. Flagged rows

`validation_issues.csv` holds **2,227** flagged rows:

| Check | Count |
|---|---|
| purse_zero | 999 |
| race_without_results | 373 |
| duplicate_race_collapsed | 326 |
| surface_missing | 269 |
| dead_heat | 249 |
| unexpected_finisher_count | 5 |
| duplicate_key_distinct_races | 2 |
| duplicate_race_results_differ | 2 |
| age_implausible | 1 |
| spot_check_race_not_found | 1 |

### Issues raised by the parser itself (Agent 2)

| Issue | Count |
|---|---|
| distance_from_listing | 6,566 |
| purse_usd_disagrees | 1,361 |
| colour_blank | 1,117 |
| site_usd_missing | 494 |
| no_results_published | 381 |
| zero_purse | 340 |
| purse_dollar_sign_assumed_usd | 243 |
| missing_country_name | 206 |
| unexpected_finisher_count | 105 |
| missing_surface | 93 |
| purse_local_is_usd | 60 |
| colour_unmapped | 31 |

## 8. What you must know before trusting this dataset

1. **Only the first three finishers exist.** IFHA publishes no 4th place or below, and no trainer, owner, sire, dam, winning time, margin, weight, odds or field size. None of that is recoverable from this source.
2. **`racepid` is not a race identity.** It is kept as `race_id` because it ties the three finishers of a race together, but the same physical race can carry two pids. Join on `Date + Track + Race Name + Group` if you merge this with anything else.
3. **2003 is a source-data gap, not a bug** — IFHA holds ~24 G2 and ~10 G3 races for that year. 2020 is genuinely short (COVID). 2026 is partial.
4. **Purses are annual-average conversions, not race-day rates.** A few percent of drift is normal. Rates for ARS, CLP, PEN and UYU are hand-entered approximations, not a live feed — see `fx_provenance` in `parsed_records.jsonl`. Argentine purses in particular should not be used for anything financial.
5. **A horse with no country suffix is bred in the publishing authority's own country** — usually the USA, but not always. Those rows show `N/A` in `Horse Country Suffix` rather than a guess.
6. **Southern-Hemisphere ages** are the local official age. SH foals are aged from 1 August, so an AUS/NZ/SAF/ARG/BRZ/CHI horse can appear one year off against a Northern-Hemisphere reading.
7. **IFHA's own disclaimer** says it takes no responsibility for the accuracy of these data; the figures come from member racing authorities. Check the site's terms before republishing.

