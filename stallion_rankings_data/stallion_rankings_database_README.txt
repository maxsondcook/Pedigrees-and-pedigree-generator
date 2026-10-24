Stallion Rankings Database
==========================
One SQLite table, stallion_rankings, built from the BloodHorse year-ranking
CSVs in this folder. Each published ranking row is one row. Each statistic
is a column, which is an attribute of the Stallion Rankings entity.

Output
------
  stallion_rankings_data/stallion_rankings.db

Rebuild
-------
  python3 build_stallion_rankings_database.py

The build stops if a file is unrecognized, a header has no column, a data-row
count does not match, or a non-empty source cell is not stored unchanged.
Split cells (stallion, stud fee, chief earner, crops, yearlings, early AEI
stakes winners) keep the original cell in a raw column.

Counts
------
  Files: 728 (28 lists x 26 years, 2001–2026)
  Rows:  103,957
  Lists: 13

Grain
-----
  year, list, table_name, rank, stallion, source_file

table_name is empty on the eight North American lists. On international
pages it is Summary, North America, Europe & Dubai, or Japan & Hong Kong.
A stallion who appears on more than one list or table stays on more than
one row. Filename spelling variants collapse to the same list and table;
the original filename stays in source_file.

Year is the folder year. When a stud-fee header names a different season
(1998 Stud Fee / Farm, 2002 Stud Fee, '26 Stud Fee / Farm), that season is
stud_fee_season.

Values are the published text, including "-", "N/A", blanks stored as NULL,
and fee text such as "Died 2001" or "$250,000M". An attribute that a list
does not publish is NULL.

Indexes
-------
  year, list, table_name
  stallion
  year, stallion

The entity catalog lists every column:
  entity_attributes.xlsx → Entity "Stallion Rankings"
