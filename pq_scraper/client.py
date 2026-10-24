"""Fetch Pedigree Query HTML with disk cache, polite delays, and Wayback fallback."""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import tempfile
import threading
import time
from pathlib import Path

PQ_HOST = "https://www.pedigreequery.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 PedigreeResearch/1.0"
)
WAYBACK_YEARS = (2020, 2016)
HOMONYM_MAX = 4
DEFAULT_DELAY = 1.0

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"


def horse_slug(name: str) -> str:
    """PQ URL slug: lowercase, strip parentheticals, drop . ' ,, spaces as +."""
    import re

    s = name or ""
    s = re.sub(r"\(.*?\)", "", s)
    s = s.replace("\u2019", "").replace("'", "").replace(".", "").replace(",", "")
    s = s.replace("&", "and")
    s = " ".join(s.split()).lower()
    return s.replace(" ", "+")


def slug_with_suffix(slug: str, n: int) -> str:
    if n <= 1:
        return slug
    return f"{slug}{n}"


def horse_url(slug: str) -> str:
    return f"{PQ_HOST}/{slug}"


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def cache_paths(url: str) -> tuple[Path, Path]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _hash_url(url)
    return CACHE_DIR / f"{key}.html", CACHE_DIR / f"{key}.meta.json"


def read_cache(url: str) -> tuple[str | None, dict | None]:
    html_path, meta_path = cache_paths(url)
    if not html_path.is_file():
        return None, None
    html = html_path.read_text(encoding="utf-8", errors="replace")
    meta = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    return html, meta


def write_cache(url: str, html: str, meta: dict) -> None:
    html_path, meta_path = cache_paths(url)
    html_path.write_text(html, encoding="utf-8")
    payload = dict(meta)
    payload["url"] = url
    payload["bytes"] = len(html.encode("utf-8", errors="replace"))
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class RateLimiter:
    def __init__(self, delay: float = DEFAULT_DELAY):
        self.delay = delay
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if self.delay <= 0:
            return
        with self._lock:
            now = time.time()
            gap = self._last + self.delay + random.uniform(0.0, 0.25) - now
            if gap > 0:
                time.sleep(gap)
            self._last = time.time()


def _decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def is_rate_limited(status: int, body: str) -> bool:
    if status == 429:
        return True
    if body and "429 too many requests" in body.lower():
        return True
    return False


class WaybackCircuit:
    """Stop hammering archive.org after repeated connect failures (HTTP 0 / curl 7)."""

    def __init__(self, fail_threshold: int = 8, cooldown_s: float = 900.0):
        self.fail_threshold = fail_threshold
        self.cooldown_s = cooldown_s
        self._lock = threading.Lock()
        self.consecutive_fails = 0
        self.opened_until = 0.0
        self.path = ROOT / "wayback_circuit.json"
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.consecutive_fails = int(data.get("consecutive_fails") or 0)
        self.opened_until = float(data.get("opened_until") or 0.0)

    def _save(self) -> None:
        payload = {
            "consecutive_fails": self.consecutive_fails,
            "opened_until": self.opened_until,
            "open": time.time() < self.opened_until,
        }
        try:
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def allow(self) -> bool:
        with self._lock:
            return time.time() >= self.opened_until

    def blocked_for(self) -> float:
        with self._lock:
            return max(0.0, self.opened_until - time.time())

    def record(self, status: int, err: str = "") -> None:
        with self._lock:
            if status and 200 <= int(status) < 500 and int(status) != 429:
                self.consecutive_fails = 0
                self._save()
                return
            self.consecutive_fails += 1
            if self.consecutive_fails >= self.fail_threshold:
                self.opened_until = time.time() + self.cooldown_s
                print(
                    f"  Wayback circuit OPEN for {self.cooldown_s:.0f}s "
                    f"after {self.consecutive_fails} failures "
                    f"(status={status} {err[:80]})",
                    flush=True,
                )
            self._save()


WAYBACK_CIRCUIT = WaybackCircuit()
WAYBACK_PAUSE_PATH = ROOT / "wayback_pause_until.txt"


def wayback_paused() -> tuple[bool, str]:
    """Honor a pause file so we do not hit IA during a cooldown."""
    if not WAYBACK_PAUSE_PATH.is_file():
        return False, ""
    raw = WAYBACK_PAUSE_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return False, ""
    try:
        from datetime import datetime

        until = datetime.fromisoformat(raw)
        if until.tzinfo is None:
            until = until.replace(tzinfo=datetime.now().astimezone().tzinfo)
        now = datetime.now(until.tzinfo)
        if now < until:
            return True, until.isoformat()
    except ValueError:
        return True, raw
    return False, ""


def curl_get(url: str, timeout: int = 35) -> tuple[int, str, str]:
    """Return (status, final_url, body). IPv4 + short connect timeout."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name
    try:
        cmd = [
            "curl",
            "-sS",
            "-4",
            "-L",
            "--compressed",
            "--connect-timeout",
            "10",
            "--max-time",
            str(timeout),
            "-A",
            UA,
            "-H",
            "Accept: text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "-H",
            "Accept-Language: en-US,en;q=0.9",
            "-o",
            tmp_path,
            "-w",
            "%{http_code}\n%{url_effective}",
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        lines = (proc.stdout or "").strip().splitlines()
        status = 0
        final = url
        if lines:
            try:
                status = int(lines[0].strip())
            except ValueError:
                status = 0
        if len(lines) >= 2:
            final = lines[1].strip()
        raw = Path(tmp_path).read_bytes() if os.path.exists(tmp_path) else b""
        body = _decode_bytes(raw)
        err = (proc.stderr or "").strip()
        if status == 0 and err:
            body = f"curl error: {err}" if not body else f"{body}\ncurl error: {err}"
        return status, final, body
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 0, url, f"curl error: {exc}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def live_get(url: str, timeout: int = 20) -> tuple[int, str, str]:
    """Fast live GET via curl_cffi Chrome impersonation, then curl."""
    try:
        from curl_cffi import requests as cr

        r = cr.get(
            url,
            impersonate="chrome131",
            timeout=timeout,
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            allow_redirects=True,
        )
        return int(r.status_code or 0), str(r.url), r.text or ""
    except Exception:
        return curl_get(url, timeout=timeout)


def is_retryable(status: int, body: str) -> bool:
    """True for 429 / transient errors. Cloudflare JS challenges are NOT 429s."""
    if is_rate_limited(status, body):
        return True
    if status == 0:
        return True
    if status in (502, 503, 504):
        return True
    return False


def curl_get_retry(url: str, limiter: RateLimiter, attempts: int = 3, live: bool = False) -> tuple[int, str, str]:
    """Retry 429 / connect failures with short backoff. Do not sit in 45s loops."""
    delays = (3, 8)
    last = (0, url, "")
    getter = live_get if live else curl_get
    for i in range(attempts):
        limiter.wait()
        status, final, body = getter(url)
        last = (status, final, body)
        if not is_retryable(status, body):
            return last
        # Immediate connect-refused: one extra try only, then give up.
        connect_refused = status == 0 and "Failed to connect" in (body or "")
        if connect_refused and i >= 1:
            return last
        if i < attempts - 1:
            wait = delays[min(i, len(delays) - 1)]
            print(f"  retryable HTTP {status} — backing off {wait}s ({url[:80]})", flush=True)
            time.sleep(wait)
    return last


def wayback_url(pq_url: str, year: int, scheme: str = "https") -> str:
    # Calendar + id_ (original HTML, no Wayback toolbar). Year is a hint; IA
    # redirects to the nearest snapshot.
    host = pq_url.replace("https://www.pedigreequery.com", f"{scheme}://www.pedigreequery.com")
    host = host.replace("http://www.pedigreequery.com", f"{scheme}://www.pedigreequery.com")
    return f"https://web.archive.org/web/{year}id_/{host}"


def fetch_url(
    url: str,
    limiter: RateLimiter | None = None,
    use_cache: bool = True,
    allow_live: bool = True,
    allow_wayback: bool = True,
) -> dict:
    """Fetch PQ (or equivalent) HTML. Result dict: ok, html, source, status, reason, url."""
    from pq_scraper.parser import looks_like_challenge, looks_like_not_found, looks_like_pedigree_page

    if use_cache:
        cached, meta = read_cache(url)
        if cached:

            if looks_like_pedigree_page(cached) and not looks_like_challenge(cached):
                return {
                    "ok": True,
                    "html": cached,
                    "source": (meta or {}).get("source", "cache"),
                    "status": 200,
                    "reason": "",
                    "url": url,
                    "from_cache": True,
                }
            if looks_like_not_found(cached) and (meta or {}).get("source") != "challenge":
                return {
                    "ok": False,
                    "html": cached,
                    "source": (meta or {}).get("source", "cache"),
                    "status": 404,
                    "reason": "404",
                    "url": url,
                    "from_cache": True,
                }

    limiter = limiter or RateLimiter()

    if allow_live:
        status, final, body = curl_get_retry(url, limiter, live=True)
        if looks_like_pedigree_page(body) and not looks_like_challenge(body):
            write_cache(url, body, {"source": "live", "status": status, "final": final})
            return {
                "ok": True,
                "html": body,
                "source": "live",
                "status": status,
                "reason": "",
                "url": url,
                "from_cache": False,
            }
        if looks_like_not_found(body) and not looks_like_challenge(body) and status in (200, 404):
            write_cache(url, body, {"source": "live", "status": status, "final": final})
            return {
                "ok": False,
                "html": body,
                "source": "live",
                "status": status or 404,
                "reason": "404",
                "url": url,
                "from_cache": False,
            }
        if looks_like_challenge(body) and not allow_wayback:
            return {
                "ok": False,
                "html": body,
                "source": "live",
                "status": status or 403,
                "reason": "blocked",
                "url": url,
                "from_cache": False,
            }

    if allow_wayback:
        paused, until = wayback_paused()
        if paused:
            return {
                "ok": False,
                "html": "",
                "source": "wayback",
                "status": 0,
                "reason": "unavailable",
                "url": url,
                "from_cache": False,
                "detail": f"wayback paused until {until}",
            }
        if not WAYBACK_CIRCUIT.allow():
            return {
                "ok": False,
                "html": "",
                "source": "wayback",
                "status": 0,
                "reason": "unavailable",
                "url": url,
                "from_cache": False,
                "detail": f"wayback circuit open {WAYBACK_CIRCUIT.blocked_for():.0f}s",
            }
        saw_unavailable = False
        last_status = 0
        last_body = ""
        for year in WAYBACK_YEARS:
            wb = wayback_url(url, year, scheme="https")
            status, final, body = curl_get_retry(wb, limiter)
            last_status, last_body = status, body
            WAYBACK_CIRCUIT.record(status, body)
            if is_retryable(status, body):
                saw_unavailable = True
                break
            if looks_like_challenge(body):
                saw_unavailable = True
                break
            if looks_like_pedigree_page(body):
                write_cache(
                    url,
                    body,
                    {"source": "wayback", "status": status, "final": final, "wb_year": year},
                )
                return {
                    "ok": True,
                    "html": body,
                    "source": "wayback",
                    "status": status,
                    "reason": "",
                    "url": url,
                    "from_cache": False,
                }
            if looks_like_not_found(body) and status in (200, 404):
                continue
        if saw_unavailable or last_status == 0:
            return {
                "ok": False,
                "html": last_body,
                "source": "wayback",
                "status": last_status or 0,
                "reason": "unavailable",
                "url": url,
                "from_cache": False,
            }

    return {
        "ok": False,
        "html": "",
        "source": "",
        "status": 0,
        "reason": "404",
        "url": url,
        "from_cache": False,
    }


def country_groups(code: str | None) -> set[str]:
    if not code:
        return set()
    c = str(code).strip().upper()
    if c in ("", "N/A", "NA", "NONE", "UNK", "UNKNOWN"):
        return set()
    aliases = {
        "USA": {"USA", "US", "USA"},
        "US": {"USA", "US"},
        "GB": {"GB", "GBR", "ENG", "UK", "IRE"} - {"IRE"},
        "GBR": {"GB", "GBR", "ENG", "UK"},
        "ENG": {"GB", "GBR", "ENG", "UK"},
        "UK": {"GB", "GBR", "ENG", "UK"},
        "IRE": {"IRE", "IRL"},
        "IRL": {"IRE", "IRL"},
        "FR": {"FR", "FRA"},
        "FRA": {"FR", "FRA"},
        "GER": {"GER", "DEU", "DE", "GER"},
        "DEU": {"GER", "DEU", "DE"},
        "JPN": {"JPN", "JP"},
        "JP": {"JPN", "JP"},
        "AUS": {"AUS", "AU"},
        "AU": {"AUS", "AU"},
        "NZ": {"NZ", "NZL"},
        "NZL": {"NZ", "NZL"},
        "SAF": {"SAF", "RSA", "SA", "ZAF"},
        "RSA": {"SAF", "RSA", "SA", "ZAF"},
        "BRZ": {"BRZ", "BRA", "BR"},
        "BRA": {"BRZ", "BRA", "BR"},
        "ARG": {"ARG"},
        "CHI": {"CHI", "CHL"},
        "CHL": {"CHI", "CHL"},
        "ITY": {"ITY", "ITA", "IT"},
        "ITA": {"ITY", "ITA", "IT"},
        "CAN": {"CAN", "CA"},
        "UAE": {"UAE"},
        "HK": {"HK", "HKG"},
        "KSA": {"KSA", "SAU"},
        "SAU": {"KSA", "SAU"},
        "TUR": {"TUR"},
        "IND": {"IND"},
        "URU": {"URU", "URY"},
        "PER": {"PER"},
        "PAN": {"PAN"},
        "VEN": {"VEN"},
        "SPA": {"SPA", "ESP"},
        "ESP": {"SPA", "ESP"},
        "SWE": {"SWE"},
        "NOR": {"NOR"},
        "DEN": {"DEN", "DNK"},
        "HUN": {"HUN"},
        "CZE": {"CZE"},
        "POL": {"POL"},
        "RUS": {"RUS"},
        "CHI": {"CHI", "CHL"},
        "KOR": {"KOR", "KR"},
        "SIN": {"SIN", "SGP"},
        "MAC": {"MAC"},
        "PHI": {"PHI", "PHI", "PHL"},
        "MEX": {"MEX"},
        "PUR": {"PUR", "PRI"},
        "TRI": {"TRI", "TTO"},
        "JAM": {"JAM"},
        "BAR": {"BAR", "BRB"},
        "UAE": {"UAE"},
    }
    g = set(aliases.get(c, {c}))
    g.add(c)
    return g


def countries_compatible(pq_country: str | None, csv_country: str | None) -> bool:
    a = country_groups(pq_country)
    b = country_groups(csv_country)
    if not a or not b:
        return True
    return bool(a & b)


def years_match(pq_year: str | None, csv_year: str | None) -> bool:
    if not pq_year or not csv_year:
        return True
    try:
        return int(pq_year) == int(str(csv_year).strip())
    except (TypeError, ValueError):
        return str(pq_year).strip() == str(csv_year).strip()
