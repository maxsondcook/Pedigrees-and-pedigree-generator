#!/usr/bin/env python3
"""Deprecated entrypoint — use scripts/pipeline/run.py.

Rebuilds the 8 sample CSVs under data/ from scraper staging with atomic writes.
"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "pipeline" / "run.py"), run_name="__main__")
