"""launchd agents for the pipeline (written, never loaded, by install-launchd).

    com.crossr.pipeline.scrape        always running; restarted 5 min after it exits
    com.crossr.pipeline.sales-import  daily at 07:00 (run at wake if the Mac slept)
    com.crossr.pipeline.racing-post   always running; works through sires due a lookup

All three run through scripts/pipeline/railway_env.sh, so DATABASE_URL is built
from the Railway CLI at start and no password is written to disk. The scrapers
run under ``caffeinate -i`` so the Mac does not idle-sleep mid-run.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENTS = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = REPO / "logs" / "pipeline"
SCRAPE = "com.crossr.pipeline.scrape"
SALES = "com.crossr.pipeline.sales-import"
RACING_POST = "com.crossr.pipeline.racing-post"


def plists(db: str, python: str) -> dict[str, dict]:
    env = str(REPO / "scripts" / "pipeline" / "railway_env.sh")
    common = {
        "WorkingDirectory": str(REPO),
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
            "PYTHONUNBUFFERED": "1",
        },
        "ProcessType": "Interactive",
    }
    return {
        SCRAPE: {
            "Label": SCRAPE,
            "ProgramArguments": [env, db, "/usr/bin/caffeinate", "-i", python, "-m", "crossr_pipeline", "scrape"],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 300,
            "StandardOutPath": str(LOG_DIR / "scrape.log"),
            "StandardErrorPath": str(LOG_DIR / "scrape.log"),
            **common,
        },
        SALES: {
            "Label": SALES,
            "ProgramArguments": [env, db, python, "-m", "crossr_pipeline", "sales-import"],
            "StartCalendarInterval": {"Hour": 7, "Minute": 0},
            "StandardOutPath": str(LOG_DIR / "sales-import.log"),
            "StandardErrorPath": str(LOG_DIR / "sales-import.log"),
            **common,
        },
        RACING_POST: {
            "Label": RACING_POST,
            "ProgramArguments": [env, db, "/usr/bin/caffeinate", "-i", python, "-m", "crossr_pipeline", "racing-post", "--loop"],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 300,
            "StandardOutPath": str(LOG_DIR / "racing-post.log"),
            "StandardErrorPath": str(LOG_DIR / "racing-post.log"),
            **common,
        },
    }


def write_plists(db: str, python: str) -> list[Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    AGENTS.mkdir(parents=True, exist_ok=True)
    out = []
    for label, body in plists(db, python).items():
        path = AGENTS / f"{label}.plist"
        with path.open("wb") as handle:
            plistlib.dump(body, handle)
        out.append(path)
    return out
