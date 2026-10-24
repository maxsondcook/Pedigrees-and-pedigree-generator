#!/usr/bin/env python3
"""Fill incomplete 5-gen trees from parent records already in pedigrees_database.py."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import clean_horse_name  # noqa: E402
from pq_scraper.ancestors import stitch_pedigree_map  # noqa: E402
from pq_scraper.dbio import load_pedigree_map, save_pedigree_map  # noqa: E402


def main() -> int:
    pedigree_map = load_pedigree_map()
    print(f"Loaded {len(pedigree_map)} top-level horses", flush=True)
    updated, stats = stitch_pedigree_map(pedigree_map, clean_horse_name)
    print(
        f"Stitch passes={stats['passes']} updated={stats['keys_updated']} "
        f"incomplete {stats['incomplete_before']} → {stats['incomplete_after']} "
        f"of {stats['top_level']}",
        flush=True,
    )
    if not updated:
        print("Nothing to write — no parent trees could complete another horse.", flush=True)
        return 0
    save_pedigree_map(pedigree_map, overwrite_keys=updated)
    print(f"Wrote {len(updated)} updated trees to pedigrees_database.py", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
