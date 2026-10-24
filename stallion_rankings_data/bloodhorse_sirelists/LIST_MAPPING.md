# BloodHorse archive → 28 stallion ranking CSV types

Source archive (example, 2004 NA general):

`https://www.bloodhorse.com/horse-racing/thoroughbred-breeding/sire-lists/archive?RegionOptions=region-america&seoName=general&region=&year=2004`

The archive form has two radios (`RegionOptions=region-america` | `region-intl`) and a `seoName` list. Choosing International **hides** the state/region dropdown; Europe / Japan / North America slices are **not** separate URLs. They are four tables on each international `seoName` page.

Years in the archive year dropdown: 2001–2026.

## Query parameters

| Param | Role |
| --- | --- |
| `seoName` | List type (see tables below) |
| `year` | Archive year (2004–2026 in this job) |
| `RegionOptions` | `region-america` for NA lists; omit (or `region-intl`) for international pages |
| `region` | Empty (`All Regions`) for national NA lists. Not used for international pages. |

`seoName` options and `data-region`:

| seoName | data-region | Form label |
| --- | --- | --- |
| `general` | america | General |
| `north-american-earnings` | america | North American Earnings *(not one of the 28 titles)* |
| `first-crop` | america | First-Crop |
| `second-crop` | america | Second-Crop |
| `third-crop` | america | Third-Crop |
| `two-year-old` | america | Two-Year-Old |
| `turf` | america | Turf |
| `all-weather` | america | All-Weather *(not one of the 28 titles)* |
| `lifetime-aei` | america | Lifetime AEI |
| `broodmare` | america | Broodmare |
| `international` | intl | International |
| `international-north-american` | intl | International North American *(duplicate of the NA table on `international`; unused)* |
| `international-first-crop` | intl | International First-Crop |
| `international-second-crop` | intl | International Second-Crop |
| `international-third-crop` | intl | International Third-Crop |
| `international-two-year-old` | intl | International Two-Year-Old |

## 8 North America pages (1 table → 1 file)

URL pattern:

`/sire-lists/archive?RegionOptions=region-america&seoName={seoName}&region=&year={year}`

| # | CSV title (after `{year}StallionRankings - `) | seoName |
| ---: | --- | --- |
| 20 | Leading Sire Rankings | `general` |
| 2 | Leading First Crop Sires | `first-crop` |
| 19 | Leading Second-Crop Sires | `second-crop` |
| 22 | Leading Third-Crop Sires | `third-crop` |
| 24 | Leading Two-Year-Old Sires | `two-year-old` |
| 23 | Leading Turf Sires | `turf` |
| 21 | Leading Sires by AEI | `lifetime-aei` |
| 1 | Leading Broodmare Sires | `broodmare` |

## 5 International pages (4 tables → 4 files)

URL pattern (nav links on BloodHorse omit `RegionOptions`; `seoName` + `year` is sufficient):

`/sire-lists/archive?seoName={seoName}&year={year}`

Tables on each page, in document order:

1. **Summary** — earnings columns for North America / Europe & Dubai / Japan & Hong Kong / International
2. **North America** — runners/winners/SWnrs + international totals
3. **Europe & Dubai** — same shape
4. **Japan & Hong Kong** — same shape

| # | CSV title | seoName | table |
| ---: | --- | --- | --- |
| 17 | Leading International Sires | `international` | summary |
| 16 | Leading International Sires-North America | `international` | North America |
| 14 | Leading International Sires-Europe&Dubai | `international` | Europe & Dubai |
| 15 | Leading International Sires-Japan&Hong Kong | `international` | Japan & Hong Kong |
| 11 | Leading International First-Crop Sires | `international-first-crop` | summary |
| 13 | Leading International First-CropSires-NorthAmerica | `international-first-crop` | North America |
| 12 | Leading International First-CropSires-Europe&Dubai | `international-first-crop` | Europe & Dubai |
| 25 | LeadingInternational FirstCropSires-Japan&HongKong | `international-first-crop` | Japan & Hong Kong |
| 6 | Leading International 2ndCrop Sires | `international-second-crop` | summary |
| 5 | Leading International 2ndCrop Sires-NorthAmerica | `international-second-crop` | North America |
| 3 | Leading International 2ndCrop Sires-Europe&Dubai | `international-second-crop` | Europe & Dubai |
| 4 | Leading International 2ndCrop Sires-Japan&HongKong | `international-second-crop` | Japan & Hong Kong |
| 10 | Leading International 3rdCrop Sires | `international-third-crop` | summary |
| 9 | Leading International 3rdCrop Sires-NorthAmerica | `international-third-crop` | North America |
| 7 | Leading International 3rdCrop Sires-Europe&Dubai | `international-third-crop` | Europe & Dubai |
| 8 | Leading International 3rdCrop Sires-Japan&HongKong | `international-third-crop` | Japan & Hong Kong |
| 18 | Leading International Two-Year-Old Sires | `international-two-year-old` | summary |
| 27 | LeadingInternational TwoYearOldSires-NorthAmerica | `international-two-year-old` | North America |
| 26 | LeadingInternational TwoYearOldSires-Europe&Dubai | `international-two-year-old` | Europe & Dubai |
| 28 | LeadingInternationalTwoYearOldSires-Japan&HongKong | `international-two-year-old` | Japan & Hong Kong |

## Output path

`/Users/maxsoncook/Desktop/stallion_rankings_data/{year}/{year}StallionRankings - {title}.csv`

Headers follow the 2001/2002 templates where BloodHorse still publishes the same columns. Year-specific earnings headers use `{yy} Earnings` (e.g. `04 Earnings`). If BloodHorse’s live table has extra/renamed columns, the live header is kept.

## AEI special case (2004–2008)

`seoName=lifetime-aei` for 2004–2008 redirects to a magazine PDF:

`https://cdn.bloodhorse.com/downloads/breeding/sirelists/pdfs/leading-sires-by-aei-{year}.pdf`

Those years are parsed from the PDF (typically ~50–70 sires). From 2009 onward the archive page is an HTML `table.sire-list` (top 150).

## Unpublished / blocked

Final job: **no unpublished year/list combos** for 2004–2026. Transient Imperva challenges were retried; archive tables were not behind a login/paywall. 2026 is in-season/partial but populated.

## Notes

- No login/paywall on the archive HTML tables themselves (public Equineline-powered lists). Site chrome has Sign In / Subscribe; Imperva (“Pardon Our Interruption”) may challenge rapid requests.
- `international-north-american` is a standalone seoName that duplicates the North America table already extracted from `international`; it is not used for the 28 titles.
- Scraper lives in this folder only. It does not import or touch the Pedigrees repo / `pq_scraper`.
