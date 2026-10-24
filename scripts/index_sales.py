#!/usr/bin/env python3
"""Retired: sales index is derived in-memory from data/sales_lots.csv.

Run:  python3 scripts/pipeline/run.py sales_lots
"""
raise SystemExit(
    "crossr_sales.db indexer retired. Merge catalogs with:\n"
    "  python3 scripts/pipeline/run.py sales_lots\n"
    "Runtime reads data/sales_lots.csv via crossr_core.sample_db."
)
