"""Download Fasig-Tipton sale-catalog PDFs linked from /results/."""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DEST = Path("/Users/maxsoncook/Desktop/PDF PEDIGREES")
YEAR_HTML = Path("/tmp/ft_pages")
MANIFEST = DEST / "_download_manifest.json"
BASE = "https://www.fasigtipton.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
CTX = ssl._create_unverified_context()
MIN_BYTES = 10_000


def fetch(url: str, timeout: int = 90) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def sale_pages() -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    for year in range(2003, 2027):
        path = YEAR_HTML / f"year_{year}.html"
        if not path.exists():
            html = fetch(f"{BASE}/results/{year}")[0].decode("utf-8", "replace")
            path.write_text(html)
        else:
            html = path.read_text(encoding="utf-8", errors="replace")
        for href, name in re.findall(
            r'<h3 class="sale-name">\s*<a href="([^"]+)"[^>]*>\s*(.*?)\s*</a>',
            html,
            re.S,
        ):
            href = href.split("#", 1)[0]
            if href.startswith("/"):
                href = BASE + href
            href = href.replace("/index.php/", "/")
            if href in seen:
                continue
            seen.add(href)
            label = " ".join(re.sub(r"<[^>]+>", "", name).split())
            found.append({"year": year, "url": href, "name": label})
    return found


def safe(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("._")
    return cleaned[:80] or "sale"


def catalog_name(sale: dict) -> str:
    ident = sale.get("sale_identifier") or "sale"
    day = sale.get("sale_start_day") or ""
    mmdd = day[5:7] + day[8:10] if len(day) >= 10 else "nodate"
    return f"FT_{sale['year']}_{mmdd}_{safe(ident)}_{safe(sale.get('sale_name') or sale.get('name'))}.pdf"


def discover(page: dict) -> dict:
    record = dict(page)
    try:
        raw, _ctype = fetch(page["url"], timeout=90)
    except Exception as exc:
        record["error"] = f"sale page: {exc}"
        return record
    html = raw.decode("utf-8", "replace")
    ident = re.search(r'"sale_identifier"\s*:\s*"([^"]+)"', html)
    title = re.search(r'"sale_name"\s*:\s*"([^"]+)"', html)
    if ident:
        record["sale_identifier"] = ident.group(1)
    if title:
        record["sale_name"] = title.group(1)
    pdfs = []
    for href in re.findall(r'href="([^"]+\.pdf[^"]*)"', html, re.I):
        low = href.lower()
        if "terms_of_use" in low or "privacy_policy" in low:
            continue
        if href.startswith("/"):
            href = BASE + href
        pdfs.append(href)
    if record.get("sale_identifier"):
        try:
            body, _ctype = fetch(
                f"{BASE}/django/api/sales/?sale_identifier={record['sale_identifier']}",
                timeout=60,
            )
            rows = json.loads(body.decode("utf-8", "replace"))
        except Exception as exc:
            record["error"] = f"api: {exc}"
            rows = []
        if rows:
            sale = rows[0]
            record["sale_id"] = sale.get("id")
            record["sale_start_day"] = sale.get("sale_start_day")
            day = sale.get("sale_start_day") or ""
            if len(day) >= 10:
                year, month, dd = day.split("-")[:3]
                suffix = "/web.pdf"
                if sale.get("id") == 185:
                    suffix = "/weba.pdf"
                elif sale.get("id") == 307:
                    suffix = "/webHORA.pdf"
                pdfs.insert(0, f"{BASE}/catalogs/{year}/{month}{dd}{suffix}")
                record["primary_pdf"] = pdfs[0]
    # de-dupe, keep order
    ordered = []
    seen = set()
    for url in pdfs:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    record["pdf_urls"] = ordered
    if not ordered and "error" not in record:
        record["error"] = "no catalog pdf"
    return record


def already_saved(path: Path) -> bool:
    if not path.exists():
        return False
    if path.stat().st_size < MIN_BYTES:
        return False
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def curl_pdf(url: str, dest: Path) -> str | None:
    """Download one PDF with curl. Returns an error string, or None on success."""
    import subprocess

    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        proc = subprocess.run(
            [
                "curl", "-fsL", "--retry", "4", "--retry-delay", "2",
                "--retry-all-errors", "--connect-timeout", "20", "--max-time", "240",
                "-A", UA, "-o", str(tmp), url,
            ],
            capture_output=True,
            text=True,
            timeout=260,
        )
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        return f"{url} {exc}"
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        err = (proc.stderr or proc.stdout or "curl failed").strip().splitlines()
        return f"{url} {err[-1][:180] if err else 'curl failed'}"
    data_head = tmp.read_bytes()[:5]
    if tmp.stat().st_size < MIN_BYTES or data_head != b"%PDF-":
        size = tmp.stat().st_size
        tmp.unlink(missing_ok=True)
        return f"{url} not a pdf ({size} bytes)"
    tmp.replace(dest)
    return None


def catalog_urls(record: dict) -> list[str]:
    urls = []
    for url in record.get("pdf_urls") or []:
        name = url.lower().split("?", 1)[0].rsplit("/", 1)[-1]
        if name in {"web.pdf", "weba.pdf", "webhora.pdf"}:
            urls.append(url)
    primary = record.get("primary_pdf")
    if primary and primary not in urls:
        urls.insert(0, primary)
    if not urls:
        for url in record.get("pdf_urls") or []:
            low = url.lower()
            if any(bad in low for bad in ("/pp/", "rag", "contract", "nomination", "setlist", "terms", "privacy")):
                continue
            if low.split("?", 1)[0].endswith(".pdf"):
                urls.append(url)
    # Keep one catalog name first, then the other book names for that folder.
    ordered = []
    seen = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    if ordered:
        folder = ordered[0].rsplit("/", 1)[0]
        for alt in ("/web.pdf", "/weba.pdf", "/webHORA.pdf"):
            alt_url = folder + alt
            if alt_url not in seen:
                ordered.append(alt_url)
    return ordered


def download_one(record: dict) -> dict:
    dest_name = catalog_name(record)
    dest = DEST / dest_name
    record["file"] = dest_name
    if already_saved(dest):
        record["status"] = "skipped"
        record["bytes"] = dest.stat().st_size
        return record
    errors = []
    for url in catalog_urls(record):
        err = curl_pdf(url, dest)
        if err:
            errors.append(err)
            continue
        record["status"] = "downloaded"
        record["bytes"] = dest.stat().st_size
        record["saved_url"] = url
        record["error"] = ""
        return record
    record["status"] = "failed"
    record["error"] = "; ".join(errors)[:500] or record.get("error") or "download failed"
    return record


def repair_start_day(record: dict) -> None:
    """Use the sale page date when the API year does not match the results year."""
    primary = record.get("primary_pdf") or ""
    year = str(record.get("year") or "")
    if primary and f"/{year}/" in primary:
        return
    try:
        html = fetch(record["url"], timeout=60)[0].decode("utf-8", "replace")
    except Exception:
        return
    match = re.search(r'"sale_start_date"\s*:\s*"(\d{2})-(\d{2})-(\d{4})"', html)
    if not match:
        return
    month, day, found_year = match.groups()
    record["sale_start_day"] = f"{found_year}-{month}-{day}"
    suffix = "/web.pdf"
    if record.get("sale_id") == 185:
        suffix = "/weba.pdf"
    elif record.get("sale_id") == 307:
        suffix = "/webHORA.pdf"
    record["primary_pdf"] = f"{BASE}/catalogs/{found_year}/{month}{day}{suffix}"
    record["pdf_urls"] = [record["primary_pdf"]]
    record["file"] = catalog_name(record)


def retry_failed() -> None:
    rows = json.loads(MANIFEST.read_text())
    pending = [row for row in rows if row.get("status") == "failed"]
    print(f"Retrying {len(pending)} failed catalogs", flush=True)
    for row in pending:
        repair_start_day(row)
    results = [row for row in rows if row.get("status") != "failed"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(download_one, row) for row in pending]
        done = 0
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            done += 1
            print(
                f"[{done}/{len(pending)}] {row.get('status')} {row.get('file')} {(row.get('error') or '')[:160]}",
                flush=True,
            )
    MANIFEST.write_text(json.dumps(results, indent=2))
    counts: dict[str, int] = {}
    for row in results:
        counts[row.get("status", "?")] = counts.get(row.get("status", "?"), 0) + 1
    print("SUMMARY", counts, flush=True)


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    pages = sale_pages()
    print(f"Sale pages: {len(pages)}", flush=True)
    discovered = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(discover, page) for page in pages]
        for index, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            discovered.append(row)
            if index % 25 == 0 or index == len(pages):
                print(f"Discovered {index}/{len(pages)}", flush=True)
    print(f"Downloading {len(discovered)} sales", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(download_one, row) for row in discovered]
        done = 0
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            done += 1
            print(
                f"[{done}/{len(discovered)}] {row.get('status')} {row.get('file')} {row.get('error','')}",
                flush=True,
            )
    MANIFEST.write_text(json.dumps(results, indent=2))
    counts: dict[str, int] = {}
    for row in results:
        counts[row.get("status", "?")] = counts.get(row.get("status", "?"), 0) + 1
    print("SUMMARY", counts, flush=True)


if __name__ == "__main__":
    import sys

    if "--retry" in sys.argv:
        retry_failed()
    else:
        main()
