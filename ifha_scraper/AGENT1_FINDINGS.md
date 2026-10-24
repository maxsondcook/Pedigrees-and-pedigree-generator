# AGENT 1 ("Inspector") — IFHA scraper reconnaissance

Target: `https://www.ifhaonline.org` — IFHA *Race Fixtures & Results* database.
Date of recon: 2026-10-05. All samples in `samples/`, cache in `cache/`.

---

## 0. TL;DR for the coordinator

| Question | Answer |
|---|---|
| Method | **POST** (GET returns HTTP 500) |
| Listing URL | `https://www.ifhaonline.org/default.asp?section=Racing&area=7` |
| Detail URL | `GET .../default.asp?section=Racing&area=20&racepid=<pid>` |
| Pagination | **None.** One slice = one response, all rows. |
| Session cookie needed | **No.** Byte-identical response with a cold cookie jar. |
| Per-race detail fetch required for finishers | **Yes, mandatory.** |
| Races 2003–2026 (G1+G2+G3) | **30,715** |
| Total HTTP requests for full job | **30,739** (24 listings + 30,715 details) |
| Wall clock @ delay 1.5s / concurrency 3 | **~4.5 hours** |
| robots.txt | `User-agent: * / Disallow:` — **everything allowed** |
| Rate limiting / WAF | **None observed** over ~3,400 requests |
| 2026 returns data? | **Yes** — 759 races; past dates have results, future dates do not |
| 2015 smoke test | **PASS** — 1,611 races, 1,612 requests, 0 retries, 0 failures |

---

## 1. The search form (`area=0`)

Saved: `samples/form_area0.html`

```
<form name="form" method="post" action="default.asp?section=Racing&area=7"
      onSubmit="return checkform( this )">
```

- **Method: POST.** `enctype` is **not specified**, so the browser default
  `application/x-www-form-urlencoded` applies. A GET with the same params
  against `area=7` returns **HTTP 500**.
- Classic ASP on **Microsoft-IIS/10.0** (`X-Powered-By: ASP.NET`).
- `Set-Cookie: ASPSESSIONIDSAADARRR=...; path=/` is issued, but it is
  **not required** (see §2.3). **No viewstate / no CSRF token / no hidden
  nonce** — the only hidden fields are `Sort` and `sCntry`, both empty.
- **Encoding gotcha:** the `Content-Type` response header carries **no
  charset**, while the page's own meta tag says `charset=iso-8859-1`. Clients
  that default to UTF-8 (including `httpx`) will **mangle the currency
  symbols** `£ ¥ €` (raw bytes `0xA3 0xA5 0x80`). Decode as **cp1252**.

### Complete field inventory

| `name` | Type | Values |
|---|---|---|
| `cntry` | select | **Navigation-only trap — see note below** |
| `raceyear` | select | `2027`, `2026`…`2003`, `""` = `< ALL Years >` |
| `track` | select | `""` = `< ALL >`; populated only after a country is chosen |
| `FromDate` | text | `mm/dd/yyyy` |
| `ToDate` | text | `mm/dd/yyyy` |
| `FromPurse` | text | integer |
| `ToPurse` | text | integer |
| `FromDistance` | text | integer |
| `ToDistance` | text | integer |
| `distanceunit` | select | `F` = Furlong (default), `M` = Meter, `Y` = Yard |
| `group` | select | `""` = `< ALL >`, **`G1`**, **`G2`**, **`G3`** |
| `age` | select | `""`, `02`=2yo, `03`=3yo, `04`=4yo, `2U`=2up, `34`=3&4, `3U`=3up, `4U`=4up |
| `sex` | select | `""`, `-`=Open, `c`, `cf`=c/f, `cg`=c/g, `f`, `fm`=f/m |
| `Sort` | hidden | `""` |
| `sCntry` | hidden | `""` |
| `Submit` | submit | `Submit` |
| `Reset` | submit | `Reset` (do not send) |

**`cntry` is not a plain value field.** Its option values are *URLs*, and an
`onChange="javascript:formHandler(this)"` handler navigates the browser:

```html
<select name="cntry" onChange="javascript:formHandler(this)">
  <option value=''>< ALL ></option>
  <option value='default.asp?section=Racing&area=0&cntry=ARG'>Argentina</option>
  ...
```

So country filtering is a **page reload** (`GET area=0&cntry=XXX`), which then
repopulates the `track` list. For scraping, **leave `cntry` empty** and filter
by the country column in the listing output instead — simpler and it avoids a
whole extra request tier.

Country codes available (27): `ARG AUS BHR BRZ CAN CHI DEN FR GER ENG HK IRE
ITY JPN NZ NOR PER KOA KSA SIN SAF SWE TUR UAE URU USA`
(note `ENG` = Great Britain, `KOA` = Republic of Korea).

---

## 2. Reproducing a query

### 2.1 Copy-pasteable request

```bash
curl -s -X POST 'https://www.ifhaonline.org/default.asp?section=Racing&area=7' \
  -A 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36' \
  -d 'cntry=&raceyear=2015&track=&FromDate=&ToDate=&FromPurse=&ToPurse=&FromDistance=&ToDistance=&distanceunit=F&group=G1&age=&sex=&Sort=&sCntry=&Submit=Submit'
```

Python equivalent:

```python
payload = {
    "cntry": "", "raceyear": "2015", "track": "",
    "FromDate": "", "ToDate": "", "FromPurse": "", "ToPurse": "",
    "FromDistance": "", "ToDistance": "", "distanceunit": "F",
    "group": "G1",            # "" | "G1" | "G2" | "G3"
    "age": "", "sex": "", "Sort": "", "sCntry": "", "Submit": "Submit",
}
r = httpx.post("https://www.ifhaonline.org/default.asp?section=Racing&area=7",
               data=payload)
r.encoding = "cp1252"
```

### 2.2 Pagination and caps — there are none

`raceyear=2015, group=G1` → HTTP 200, 339,650 bytes, **436 races in one
response**. There is no `page` parameter, no Next/Prev links, and no "showing
N of M" counter. The only query-string knob on the results page is
`&sort=0..7` (re-sorts via session state; irrelevant for scraping).

**No row cap was found.** `group=""` (ALL) for 2015 returned **1,611** races in
a single 1.1 MB response, and `436 + 457 + 718 = 1611` exactly — i.e. the
ALL-groups query returns the precise union of the three, with nothing
truncated. **This means `group=""` is safe and cuts the listing tier from 72
requests to 24.**

**The one hard limit:** `raceyear=""` (ALL years) → **HTTP 500**. The server
cannot build the ~30k-row page.

➡ **Safe slicing strategy: one POST per year, `group=""`.** 24 requests total.
Largest single response is 2015 at 1,611 rows / ~1.1 MB. No need to slice by
country.

### 2.3 Is a session cookie required? No.

Tested three ways:

| Test | Result |
|---|---|
| `GET area=0` first, reuse `ASPSESSIONID` cookie, then POST | 200, 339,650 B |
| POST with a **completely cold** cookie jar | 200, 339,650 B |
| MD5 of both bodies | **identical** (`ca0b93b4…`) |

No warm-up request is needed. The prototype still keeps a cookie jar (shared
`AsyncClient`) since it is free and guards against future behaviour changes.

### 2.4 Race counts per year × group (measured, all 72 slices)

| Year | G1 | G2 | G3 | ALL |
|---|---|---|---|---|
| 2003 | 290 | 24 | 10 | **324** |
| 2004 | 388 | 472 | 690 | 1550 |
| 2005 | 365 | 431 | 653 | 1449 |
| 2006 | 325 | 443 | 643 | 1411 |
| 2007 | 398 | 459 | 718 | 1575 |
| 2008 | 317 | 377 | 580 | 1274 |
| 2009 | 380 | 436 | 670 | 1486 |
| 2010 | 373 | 417 | 668 | 1458 |
| 2011 | 370 | 400 | 618 | 1388 |
| 2012 | 298 | 373 | 602 | 1273 |
| 2013 | 300 | 373 | 632 | 1305 |
| 2014 | 390 | 416 | 684 | 1490 |
| 2015 | 436 | 457 | 718 | **1611** |
| 2016 | 394 | 422 | 651 | 1467 |
| 2017 | 344 | 412 | 678 | 1434 |
| 2018 | 353 | 380 | 596 | 1329 |
| 2019 | 332 | 342 | 535 | 1209 |
| 2020 | 284 | 284 | 408 | 976 |
| 2021 | 390 | 359 | 525 | 1274 |
| 2022 | 384 | 350 | 541 | 1275 |
| 2023 | 316 | 343 | 520 | 1179 |
| 2024 | 308 | 339 | 526 | 1173 |
| 2025 | 261 | 282 | 503 | 1046 |
| 2026 | 175 | 198 | 386 | **759** |
| **Total** | | | | **30,715** |

Notes:
- **2003 is badly incomplete**: only 24 G2 and 10 G3 races. Treat 2003 as
  G1-only-ish and warn the user. 2004+ looks complete.
- **2020** is low (976) — genuine COVID cancellations, not a scrape bug.
- **2027** returns **0** races.

---

## 3. The listing page (`area=7`)

Saved: `samples/results_2015_G1.html`, `samples/results_2026_ALL.html`

One `<TR>` per race. The whole table is emitted on a single enormous line, so
**line-based tools are useless — parse with a regex over the full blob or an
HTML parser.** Row shape (whitespace added for readability):

```html
<TR><TD></td>
  <TD><b><a href='default.asp?section=Racing&area=8&racepid=59931'>Grand Premio Longines Asociacion Latinoamericana</a> </b></td>
  <TD align='center'>&nbsp; <a href='default.asp?section=Racing&area=20&racepid=59931'><img ... SRC='/images/raceResults.gif' ...></A></td>
  <TD align='center' >ARG</td>
  <TD align='center'>HAR</td>
  <TD align='center'><small>14 March 2015</small></td>
  <TD align='center'><small>2100 Meters (D)</small></td>
  <TD align='center'>3U<br>fm</td>
  <TD align='center'>Ps   1,000,000 (*$118,100)</td>
  <TD align='center'>G1</td>
```

Columns: race name (+ `racepid`), results link, **Country**, **Track code**,
**Date** (`DD Month YYYY`), **Distance + surface code**, **Age + sex**
(separated by `<br>`), **Purse** (local + `(*$USD)`), **Group**.

Surface code in this column is a single letter: `(D)` dirt, `(T)` turf.
*(2015: 5,546 `(D)` vs 7,137 `(T)` across all groups.)*

⚠ **The listing contains NO finishers.** There is no horse name, jockey, or
placing anywhere in the `area=7` response. **A per-race detail fetch is
therefore mandatory.**

Each `racepid` appears **twice** per row (once as `area=8`, once as `area=20`),
so always de-duplicate when harvesting IDs.

The regex in `agent1_fetch.py:ROW_RE` parsed **436/436, 457/457 and 718/718**
rows for 2015 G1/G2/G3 — 100% coverage.

---

## 4. The detail pages

Two different `area` values hang off the same `racepid`:

### 4.1 `area=20` — **RESULTS** (this is the one you need)

`GET https://www.ifhaonline.org/default.asp?section=Racing&area=20&racepid=59931`

Samples: `samples/race_area20_{39002,59931,60163,59742,59316,59756,58976}.html`

The payload sits between the HTML comments
`<!---BEGIN RACE DATA HERE ---->` and `<!---END RACE DATA ---->` — anchor on
those, they are stable across every sample and every country.

```html
<TD align="center" class="resultsInfo" bgcolor="F1F1F1" colspan="3"><BR>
  <span class="Heleven">Grand Premio Longines Asociacion Latinoamericana</span><BR>
  <b>Group 1</b><BR>
  Ps   1,000,000 (*$118,100)
  <BR>
  Saturday, March 14, 2015<BR>
  HAR Hipodromo Argentino De Palermo - Argentina<BR>
  2100 Meters on the dirt
  <BR> <BR>
</td>
...
<TR>
  <td align="right" class="resultsPosition">First: </td>
  <td bgcolor="#F2F2F2">&nbsp;<b>Liberal (PER), </b> 11 DK B/ H</td>
  <td bgcolor="#F2F2F2">&nbsp;Talaverano, E.</TD>
</TR>
```

**Header block, in fixed order** (each terminated by `<BR>`):

1. Race name — `<span class="Heleven">`
2. Group — `<b>`, literal text `Group 1` / `Group 2` / `Group 3`
3. Purse — local currency symbol + amount, then optional `(*$USD)`
4. Date — `Dayname, Month DD, YYYY`
5. Track — `<CODE> <Full track name> - <Country full name>`
6. Distance + surface — `<N> <Meters|Furlongs> on the <surface>`

**Finisher rows:** `class="resultsPosition"` labelled `First:` / `Second:` /
`Third:`, then **horse cell** and **jockey cell**. Only these two columns exist
— the table header is literally just `Horse | Jockey`.

### 4.2 `area=8` — race **conditions** (pre-race, no finishers)

`GET .../default.asp?section=Racing&area=8&racepid=59931`

Sample: `samples/race_area8_59931.html`. Label/value `<TR>` pairs:
**Date, Racecourse, Prize Money** (total *plus* the split to 1st–5th),
**Qualification** (e.g. `3 yo and up, Colts and Fillies`), **Weight
Conditions, Entry Fee(s), Forfeit Conditions, Special Conditions, Contact
Name, Contact Email**. Carries the header block too, but **no finishers**.

Only worth fetching if the user wants the prize-money breakdown or the
free-text qualification/weight conditions — it **doubles** the job to ~61k
requests. The age/sex condition codes are already on the listing page.

### 4.3 Field availability — audited over all 1,598 result pages for 2015

Produced by `validate_cache.py`.

#### ✅ AVAILABLE

| Field | Source | Notes |
|---|---|---|
| Race name | detail or listing | |
| Group/grade | both | `Group 1/2/3` (detail), `G1/G2/G3` (listing) |
| Date | both | full weekday+date on detail |
| Country | listing (code) + detail (full name) | 27 jurisdictions |
| Track | listing (code) + detail (code + full name) | |
| Distance | both | **910 pages Meters, 688 Furlongs** — mixed, must normalise. Furlongs can be fractional (`8.5 Furlongs`) |
| Surface | both | listing `(D)`/`(T)`; detail free text |
| Purse | both | local currency + `(*$USD)` conversion |
| Currency | both | **16 distinct**: `$ Ps $A CN$ € R ¥ £ S/ SEK AED HK$ $U S$ NOK DKK` |
| Age condition | listing | `3U`, `02`, `34`, … |
| Sex condition | listing | `fm`, `c`, `-`, … |
| Qualification (prose) | `area=8` | `3 yo and up, Colts and Fillies` |
| Prize split 1st–5th | `area=8` | |
| **1st/2nd/3rd horse name** | detail | |
| **Country suffix of horse** | detail | |
| **Year of birth of horse** | detail | see §4.4 — it's YOB, **not** age |
| **Colour of horse** | detail | |
| **Sex of horse** | detail | |
| **Jockey** | detail | `Surname, Initial.` |

#### ❌ NOT AVAILABLE ANYWHERE

- **Trainer** — never present (checked ARG, USA, GB, JPN, UAE, CHI, BRZ)
- **Owner** — never present
- **Sire / Dam** — never present (no pedigree data at all)
- **Winning time** — never present
- **Margin / beaten lengths** — never present
- **4th place and below** — the site states: *"It also provides the results,
  first three finishers only"*
- **Weight carried, odds, field size, barrier/draw** — never present

**Observed: exactly 3 finisher rows on 1,596 of 1,598 pages; 2 pages have 4
rows (dead heats).** Do not hard-code 3.

### 4.4 Horse string format — exact split rule

The cell is `<b>NAME (CC), </b>` followed by a **fixed-width** descriptor.

⚠ **The site's own help text is wrong.** It claims *"The first number behind a
horse name is age"*. It is actually the **2-digit year of birth**. Proof:
`racepid=39002` is an **August 2003** race whose winner reads `98 B M` — an
age of 98 is impossible; the horse was foaled **1998** (a 5yo, consistent with
sex code `M` = mare, which the site defines as "female aged 5 or over").

The descriptor is **fixed-width, 10 characters**:

```
offset: 0 1 2 3 4 5 6 7 8 9
        Y Y _ C C C C C C S
        └YOB┘ └─colour──┘ └sex
```

```python
# desc is the text after </b>, with &nbsp; -> space, then .strip()
yob_2digit = desc[0:2]            # "11"
colour     = desc[3:9].strip()    # "DK B/"  (may be EMPTY)
sex        = desc[9]              # "H"
```

Equivalent regex: `^(\d{2})\s(.{6})([A-Z])$`

**Do NOT split on whitespace** — colour values contain spaces (`DK B/`,
`DK B`, `GR/B`) and are sometimes blank. The fixed-width rule gave
**0 failures across all 4,796 finisher rows**; a naive `\s+` split failed on 28.

Observed **colour** codes (2015, 4,796 rows):
`B` 2513, `CH` 898, `DK B/` 649, `DK B` 319, `GR/RO` 198, `GR` 103, `BR` 58,
`B/BR` 13, `BLK` 8, `GR/B` 5, `BR/BL` 3, `BL` 1, **blank 28**.

Observed **sex** codes: `H` 1888 (horse, male 5+), `M` 1805 (mare),
`G` 1075 (gelding), `R` 28 (ridgling/rig). The form's legend also documents
`C` = colt and `F` = filly, which did not appear in the 2015 sample but should
be expected in other years.

**Country suffix:** `NAME (CC),` — e.g. `Liberal (PER),`. **1,410 of 4,796
rows have no suffix at all** (`Closing Bell, 12 DK B/ H`). Per Jockey Club
convention that means **USA-bred**; the IFHA site omits the suffix for the
"home" country of the publishing authority. Top suffixes: IRE 692, ARG 512,
GB 378, JPN 372, SAF 316, BRZ 280, AUS 215, CHI 185, FR 178, GER 108.

### 4.5 Data-quality traps

- **13 of 1,611** 2015 races (0.8%) are real, fully-described races with **no
  finishers published** — the `resultsPosition` block is simply absent
  (e.g. *Texas Mile S.*, *Kentucky Turf Cup S.*, several Peru races).
  Emit them with null finishers rather than crashing.
- **Future races return an empty body.** For a 2026 race dated after today,
  `area=20` returns HTTP 200 but the `BEGIN RACE DATA` block is missing
  entirely (verified: pid 82671, 82668 = 20 Oct 2026 → empty; pid 81886,
  81887 = 03 Jan 2026 → full results).
- **Surface free text is messy** on the detail page: `turf` 1082, `dirt` 449,
  `inner` 25 (Japanese inner turf), `downhill` 5 (Santa Anita), `equitrack` 3
  (AWT), `D` 2, **blank 32**. Prefer the listing's clean `(D)`/`(T)` code and
  use the detail text only to refine AWT/inner.
- **Older records have gaps:** `racepid=39002` (2003) has purse `Ps 0` and an
  empty distance/surface (`on the` with nothing after it). 5 pages in 2015
  have a zero purse.
- **Mixed distance units** within a single year (Meters for JPN/UAE/ARG/BRZ,
  Furlongs for USA/GB) — normalise before writing the CSV.

---

## 5. Politeness and feasibility

### robots.txt

`https://www.ifhaonline.org/robots.txt` → HTTP 200, `text/plain`:

```
User-agent: *
Disallow: 
```

An **empty `Disallow:`** is the explicit "allow everything" idiom. There is no
`Crawl-delay`, no sitemap, and no restricted path. **Nothing in robots.txt
prohibits this scrape.**

### Latency (measured)

| Request type | Mean |
|---|---|
| `area=0` form | 0.45 s (cold) |
| `area=7` listing POST (1,611 rows) | 0.59–0.65 s |
| `area=20` detail GET | **0.095–0.12 s** |

Full-year 2015 run: 1,612 requests in **241.7 s**, mean latency **0.095 s**.

### Rate limiting / WAF

- **No Cloudflare, no WAF, no challenge page.** Plain `Microsoft-IIS/10.0`.
- **No 429 ever returned**, and no 403s, across roughly **3,400 requests**
  including a 1,612-request burst at concurrency 4 / delay 0.5 s.
- Two transient `httpx.ReadError`s (server closing a keep-alive connection)
  appeared during one early concurrency test; **both succeeded on the first
  retry**. The final 1,612-request run had **0 retries and 0 failures**.
- The only server-side limit found is the **HTTP 500 on `raceyear=""`**, which
  is a response-size problem, not throttling.

### Full-job estimate (2003–2026, G1+G2+G3)

- Requests: **24** listing POSTs + **30,715** detail GETs = **30,739**
- Disk: ~48 KB/page → **~1.4 GB** of cached HTML (2015 alone: 1,612 files, 77 MB)

| delay | concurrency | throughput | wall clock |
|---|---|---|---|
| **1.5 s** | **3** | 1.88 req/s | **~4.5 h** (273 min) |
| 1.0 s | 3 | 2.73 req/s | ~3.1 h |
| 0.5 s | 4 | 6.67 req/s | ~1.3 h *(measured rate)* |

Because the cache makes re-runs free, the job can be run in several sessions.

### Legal note (not legal advice)

robots.txt permits crawling, but the site's own disclaimer reads: *"IFHA does
not take any responsibility for the accuracy of these data."* The data is
supplied to IFHA by member racing authorities. Check the site's terms before
**redistributing** the resulting CSV; harvesting it for private analysis is a
different matter from republishing it.

---

## 6. The prototype — `agent1_fetch.py`

```
python3 agent1_fetch.py --years 2015                 # one year, all groups
python3 agent1_fetch.py --years 2003-2026            # full job
python3 agent1_fetch.py --years 2015 --groups G1,G2  # explicit groups
python3 agent1_fetch.py --years 2015 --listing-only  # skip detail tier
python3 agent1_fetch.py --years 2015 --limit 20      # cap detail pages
    --concurrency N   (default 3)
    --delay SECONDS   (default 1.5)
```

Implements everything requested: async `httpx` with one shared `AsyncClient`
and cookie jar, realistic Chrome UA, `http2=False`, `asyncio.Semaphore`
(default 3), configurable delay (default 1.5 s), exponential backoff with
jitter on timeouts/429/5xx over **4 attempts**, and forced **cp1252** decoding.

**On-disk cache** at `cache/<first2>/<sha256>.html`, keyed by
`sha256(method + url + sorted body)` and sharded one level so ~31k entries stay
manageable. Writes are atomic (`.tmp` + `replace`). A cached page is **never**
re-requested, making the job free to re-run and resumable after an interrupt.

**Downstream API** — both generators yield `(metadata, raw_html)`:

```python
from agent1_fetch import IfhaFetcher, iter_race_details, iter_listings, scan_listing

async with IfhaFetcher(concurrency=3, delay=1.5) as f:
    async for meta, html in iter_race_details(f, years=[2015], groups=[""]):
        # meta: racepid, race, country, track, date, distance, agesex,
        #       purse, group, query_year, query_group
        # html: raw area=20 detail page (cp1252-decoded)
        ...
```

`iter_race_details` joins the listing-level metadata onto each detail page, so
the parser gets clean country/track/date/distance/purse fields **without**
re-parsing the messy detail header. `scan_listing(html)` and `racepids(html)`
are exposed for listing-only work. Pass `with_conditions=True` to also pull the
`area=8` page (doubles request count).

### Smoke test — 2015 — **PASSED**

```
2015: 1611 race detail pages fetched
done in 241.7s | network requests=1612 cache_hits=0 retries=0 failures=0
                 mean_latency=0.095s
```

Cache resumability verified by re-running **with the sandbox network
allowlist blocking the site**:

```
2015: 1611 race detail pages fetched
done in 0.3s | network requests=0 cache_hits=1612 retries=0 failures=0
```

0 network requests, 1,612 cache hits, 0.3 s — the cache is fully resumable and
re-runs cost nothing.

`validate_cache.py` then audited the cache: **1,598/1,598** header blocks
parsed, **4,796** finisher rows, **0** horse-string parse failures.

---

## 7. Recommendations for Agent 2 (parser)

1. **Decode as cp1252**, never UTF-8, or you lose `£ ¥ €`.
2. Slice **one POST per year with `group=""`** (24 requests). Never send
   `raceyear=""`.
3. Anchor detail parsing on the `BEGIN RACE DATA` / `END RACE DATA` comments.
4. Treat the horse descriptor as **fixed-width**, and the leading 2 digits as
   **year of birth**, not age. Derive age as `race_year - (1900 or 2000 + YOB)`
   with a sensible century pivot.
5. Expect **0, 3, or 4** finisher rows — never assume exactly 3.
6. Take country/track/date/distance/surface/purse/age/sex from the **listing**
   row (clean, delimited) and only the finishers from the detail page.
7. Normalise distance to a single unit; both Meters and Furlongs occur, and
   Furlongs may be fractional.
8. A horse with **no country suffix is USA-bred** (or bred in the publishing
   authority's own country) — do not leave it null.
9. Flag 2003 G2/G3 as **known-incomplete** in any report to the user.
10. Tell the user up front: **no trainer, owner, sire, dam, time, or margin
    is obtainable from this source**, and only the first three finishers.
