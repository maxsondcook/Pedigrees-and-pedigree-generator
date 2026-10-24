"""macOS notifications for the pipeline (silently skipped elsewhere)."""

from __future__ import annotations

import subprocess
import sys


def _quote(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def send(title: str, message: str) -> None:
    print(f"NOTIFY {title}: {message}", flush=True)
    if sys.platform != "darwin":
        return
    script = f"display notification {_quote(message)} with title {_quote('Crossr pipeline')} subtitle {_quote(title)}"
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=10, capture_output=True)
    except Exception:
        pass
