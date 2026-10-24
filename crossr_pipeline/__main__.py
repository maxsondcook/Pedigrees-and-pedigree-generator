"""Crossr data pipeline. Needs DATABASE_URL (see scripts/pipeline/railway_env.sh).

    python -m crossr_pipeline scrape [--limit N] [--once] [--delay 3]
    python -m crossr_pipeline scrape --refresh-only [--refresh-cap N]
    python -m crossr_pipeline sales-import [--dry-run] [--force FILE ...]
    python -m crossr_pipeline racing-post [--limit N] [--delay 3]
    python -m crossr_pipeline status
    python -m crossr_pipeline install-launchd [--db railway|crossr_dev]

See docs/PIPELINE.md.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _conn():
    from equibase_scraper import pgdb

    if not pgdb.enabled():
        raise SystemExit(
            "DATABASE_URL is not set. Run through scripts/pipeline/railway_env.sh "
            "(railway or crossr_dev)."
        )
    return pgdb.connect()


def _db_name() -> str:
    return os.environ.get("DATABASE_URL", "").rsplit("/", 1)[-1].split("?")[0]


def cmd_scrape(args) -> int:
    from crossr_pipeline.scrape import scrape

    print(f"Database: {_db_name()}", flush=True)
    return scrape(
        delay=args.delay,
        limit=args.limit,
        refresh_cap=args.refresh_cap,
        once=args.once,
        skip_refresh=args.skip_refresh,
        refresh_only=args.refresh_only,
        role=args.role,
    )


def cmd_sales_import(args) -> int:
    from crossr_pipeline.sales_import import sales_import

    conn = _conn()
    try:
        result = sales_import(conn, force=set(args.force or []), dry_run=args.dry_run)
    finally:
        conn.close()
    print(result)
    return 1 if result["failed"] else 0


def cmd_racing_post(args) -> int:
    from crossr_pipeline.racing_post import run_racing_post

    print(f"Database: {_db_name()}", flush=True)
    while True:
        conn = _conn()
        try:
            done = run_racing_post(conn, delay=args.delay, limit=args.limit)
        finally:
            conn.close()
        if not args.loop:
            return 0
        if done == 0:
            print("racing-post: nothing due. Sleeping 6 h.", flush=True)
            time.sleep(6 * 3600)


def _age(ts) -> str:
    if ts is None:
        return "-"
    seconds = (datetime.now(timezone.utc) - ts).total_seconds()
    if seconds < 120:
        return f"{int(seconds)}s ago"
    if seconds < 7200:
        return f"{int(seconds // 60)}m ago"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h ago"
    return f"{seconds / 86400:.1f}d ago"


def cmd_status(args) -> int:
    from crossr_pipeline import state

    conn = _conn()
    try:
        state.ensure(conn)
        print(f"Database: {_db_name()}\n")
        print("Recent runs")
        for run in state.recent_runs(conn, args.limit):
            status = run["status"]
            if status == "running" and run["heartbeat_at"] and (
                datetime.now(timezone.utc) - run["heartbeat_at"]
            ).total_seconds() > 3600:
                status = "running? (no heartbeat for 1h+, probably crashed)"
            counts = ", ".join(f"{k}={v}" for k, v in sorted((run["counts"] or {}).items()))
            print(
                f"  #{run['id']:<5} {run['job']:<16} {status:<10} started {_age(run['started_at'])}, "
                f"heartbeat {_age(run['heartbeat_at'])}  {counts}"
            )
            if run["detail"]:
                print(f"         {run['detail']}")
        print("\nQueue items")
        for row in state.queue_summary(conn):
            print(f"  {row['job']:<16} {row['status']:<14} {row['n']}")
        print("\nrace_horses by status")
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM race_horses GROUP BY 1 ORDER BY 2 DESC"):
            print(f"  {row['status'] or '-':<14} {row['n']}")
        print("\nTable versions (API reloads when these move)")
        for row in conn.execute("SELECT table_name, row_count, updated_at FROM crossr_table_versions ORDER BY 1"):
            print(f"  {row['table_name']:<18} {row['row_count'] or 0:>9}  {_age(row['updated_at'])}")
    finally:
        conn.close()
    return 0


def cmd_install_launchd(args) -> int:
    from crossr_pipeline import launchd

    paths = launchd.write_plists(db=args.db, python=args.python or sys.executable)
    for path in paths:
        print(f"wrote {path}")
    print("\nNothing is loaded yet. To start:")
    for path in paths:
        print(f"  launchctl bootstrap gui/$(id -u) {path}")
    print("To stop:")
    for path in paths:
        print(f"  launchctl bootout gui/$(id -u) {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m crossr_pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scrape", help="Equibase loop: weekly race refresh + sale-parent pedigrees")
    p.add_argument("--delay", type=float, default=3.0, help="Seconds between page loads (plus jitter)")
    p.add_argument("--limit", type=int, help="Stop after this many queue items (testing)")
    p.add_argument("--once", action="store_true", help="One pass over the queue, then exit")
    p.add_argument("--refresh-cap", type=int, help="At most this many horses in a race refresh")
    p.add_argument("--skip-refresh", action="store_true", help="Do not run the weekly race refresh")
    p.add_argument("--refresh-only", action="store_true", help="Run only the race refresh, then exit")
    p.add_argument("--role", choices=["sire", "dam"], help="Only sale sires or only sale dams")
    p.set_defaults(func=cmd_scrape)

    p = sub.add_parser("sales-import", help="Load new/changed sales_data/*.csv into sales_lots")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", nargs="*", metavar="FILE", help="Reload these file names even if unchanged")
    p.set_defaults(func=cmd_sales_import)

    p = sub.add_parser("racing-post", help="Racing Post fee history for every sire (adds missing stud_fees years)")
    p.add_argument("--delay", type=float, default=3.0, help="Seconds between page loads (plus jitter)")
    p.add_argument("--limit", type=int, help="Stop after this many sires (testing)")
    p.add_argument("--loop", action="store_true", help="Keep going: rerun when done, sleep 6 h when nothing is due")
    p.set_defaults(func=cmd_racing_post)

    p = sub.add_parser("status", help="Recent runs, queue state, table counts")
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("install-launchd", help="Write the launchd agents (does not load them)")
    p.add_argument("--db", default="railway", help="railway (production) or crossr_dev")
    p.add_argument("--python", help="Python to run (default: this one)")
    p.set_defaults(func=cmd_install_launchd)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
