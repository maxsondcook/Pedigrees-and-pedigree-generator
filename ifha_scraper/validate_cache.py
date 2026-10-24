#!/usr/bin/env python3
"""Audit the cached area=20 detail pages to quantify what is actually parseable.

Run after agent1_fetch.py has populated ifha_scraper/cache/.
"""
import collections
import glob
import re

FIN = re.compile(
    r'class="resultsPosition">(First|Second|Third):\s*</td>\s*'
    r'<td[^>]*>&nbsp;<b>(.*?)</b>\s*(.*?)</td>\s*'
    r'<td[^>]*>&nbsp;(.*?)</TD>',
    re.S | re.I,
)
HDR = re.compile(
    r'<span class="Heleven">(?P<race>.*?)</span><BR>\s*'
    r'<b>(?P<group>.*?)</b><BR>\s*'
    r'(?P<purse>.*?)\s*<BR>\s*'
    r'(?P<date>.*?)<BR>\s*'
    r'(?P<track>.*?)<BR>\s*'
    r'(?P<dist>.*?)\s*<BR>',
    re.S,
)
# Fixed-width: "YY " + colour padded to 6 + sex. Colour is sometimes blank,
# and sometimes contains a space ("DK B/ H"), so slice rather than split.
DESC = re.compile(r"^(?P<yob>\d{2})\s{1}(?P<colour>.{6})(?P<sex>[A-Z])$")
SUFFIX = re.compile(r"\((?P<cc>[A-Z]+)\)\s*,?\s*$")

counters = {
    "sex": collections.Counter(),
    "colour": collections.Counter(),
    "suffix": collections.Counter(),
    "surface": collections.Counter(),
    "unit": collections.Counter(),
    "currency": collections.Counter(),
    "nfin": collections.Counter(),
}
pages = finrows = hdr_ok = no_suffix = blank_dist = zero_purse = 0
desc_fail: list[str] = []

for path in glob.glob("cache/*/*.html"):
    html = open(path, encoding="utf-8", errors="replace").read()
    if "resultsPosition" not in html:
        continue  # listing page, not a detail page
    pages += 1

    fins = FIN.findall(html)
    counters["nfin"][len(fins)] += 1

    m = HDR.search(html)
    if m:
        hdr_ok += 1
        dist = re.sub(r"<[^>]+>", " ", m.group("dist")).strip()
        s = re.search(r"on the (\w+)", dist)
        counters["surface"][s.group(1) if s else "<blank>"] += 1
        u = re.search(r"\d+\s+(Meters|Furlongs|Yards)", dist)
        counters["unit"][u.group(1) if u else "<blank>"] += 1
        if not u:
            blank_dist += 1
        purse = re.sub(r"<[^>]+>", "", m.group("purse")).strip()
        cur = re.match(r"([^\d\s]+|[A-Z]{3})", purse)
        counters["currency"][cur.group(1) if cur else "<blank>"] += 1
        if re.search(r"\s0\s*$", purse):
            zero_purse += 1

    for _pos, horse, desc, _jock in fins:
        finrows += 1
        desc = desc.replace("&nbsp;", " ").strip()
        d = DESC.match(desc)
        if d:
            counters["colour"][d.group("colour")] += 1
            counters["sex"][d.group("sex")] += 1
        else:
            desc_fail.append(desc)
        sm = SUFFIX.search(horse.strip())
        if sm:
            counters["suffix"][sm.group("cc")] += 1
        else:
            no_suffix += 1

print(f"detail pages audited      : {pages}")
print(f"header block parsed       : {hdr_ok}/{pages}")
print(f"finisher rows per page    : {dict(counters['nfin'])}")
print(f"total finisher rows       : {finrows}")
print(f"horse-desc parse failures : {len(desc_fail)} {desc_fail[:6]}")
print(f"sex codes                 : {dict(counters['sex'])}")
print(f"colour codes              : {dict(counters['colour'])}")
print(f"surface words             : {dict(counters['surface'])}")
print(f"distance units            : {dict(counters['unit'])}")
print(f"pages w/ blank distance   : {blank_dist}")
print(f"pages w/ zero purse       : {zero_purse}")
print(f"currencies                : {dict(counters['currency'])}")
print(f"no country suffix on horse: {no_suffix} (convention: USA-bred carry none)")
print(f"country suffixes (top 20) : {counters['suffix'].most_common(20)}")
