"""Scrape → sample CSV pipeline.

Writes only into data/*.csv (the 8 sample tables) and pedigrees_database.py.
Runtime readers use crossr_core.sample_db; scrapers call upsert helpers here
so :3000/:8000 can stay up during merges (atomic tmp+replace).
"""
