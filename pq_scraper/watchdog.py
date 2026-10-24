#!/usr/bin/env python3
"""Restart the detached pedigree LaunchAgent if the heartbeat goes stale."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROGRESS_PATH = ROOT / "progress.json"
AGENT = "com.maxsoncook.pq.fetch-gsw"
STALE_SECONDS = 25 * 60
CF_COOLDOWN_SECONDS = 60 * 60


def _parse_iso(value: str) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def main() -> int:
    if not PROGRESS_PATH.is_file():
        print("watchdog: no progress.json", flush=True)
        return 0
    try:
        progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("watchdog: progress.json unreadable", flush=True)
        return 0

    remaining = int(progress.get("remaining") or 0)
    if remaining <= 0 and str(progress.get("phase") or "") in {"done", "ancestors-done"}:
        print("watchdog: remaining=0, not restarting", flush=True)
        return 0

    if progress.get("stop") == "cf_blocked":
        hb = _parse_iso(str(progress.get("heartbeat_at") or progress.get("updated_at") or ""))
        if hb and time.time() - hb < CF_COOLDOWN_SECONDS:
            print("watchdog: CF-blocked cooldown, not restarting", flush=True)
            return 0

    stamp = _parse_iso(
        str(progress.get("heartbeat_at") or progress.get("updated_at") or "")
    )
    age = time.time() - stamp if stamp else 10**9
    uid = os.getuid()
    label = f"gui/{uid}/{AGENT}"

    alive = subprocess.run(
        ["pgrep", "-f", "pq_scraper/fetch_pedigrees.py"],
        capture_output=True,
        text=True,
    )
    running = bool((alive.stdout or "").strip())

    if running and age <= STALE_SECONDS:
        print(f"watchdog: ok running age={age:.0f}s remaining={remaining}", flush=True)
        return 0

    print(
        f"watchdog: restart running={running} age={age:.0f}s remaining={remaining}",
        flush=True,
    )
    subprocess.run(["launchctl", "kickstart", "-k", label], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
