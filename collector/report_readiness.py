#!/usr/bin/env python3
"""Report how close the collected data is to producing a full model input."""
from __future__ import annotations
import sys, sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collector.assemble import assemble_all, TOLERANCE_MINUTES
from rainsignal.schema import MODEL_COLUMNS
from rainsignal.stations import COLLECTABLE, UNCOLLECTABLE

DB = Path(sys.argv[1] if len(sys.argv) > 1 else "data/live/observations.db")
target = (date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2
          else datetime.now(timezone.utc).date() - timedelta(days=1))

con = sqlite3.connect(DB)
n_rows, n_loc = con.execute("select count(*), count(distinct location) from observations").fetchone()
span = con.execute("select min(observed_utc), max(observed_utc) from observations").fetchone()
con.close()
print(f"database        {DB}")
print(f"stored          {n_rows} readings across {n_loc} stations")
print(f"span (UTC)      {span[0]}  ->  {span[1]}")
print(f"assembling for  {target} (station-local date), tolerance +/-{TOLERANCE_MINUTES} min\n")

rows = assemble_all(DB, target)
complete = [r for r in rows.values() if r.complete]
print(f"{'STATIONS WITH A COMPLETE MODEL INPUT':46s} {len(complete)} of {len(rows)}")
print(f"{'stations with a partial input':46s} {len(rows)-len(complete)}")
print(f"{'weatherAUS locations with no live station':46s} {len(UNCOLLECTABLE)}\n")

miss = Counter()
for r in rows.values():
    miss.update(r.missing)
print("missing features, by how many stations lack them:")
for feat, n in sorted(miss.items(), key=lambda kv: (-kv[1], kv[0])):
    print(f"  {feat:16s} {n:2d}/{len(rows)}")

print("\nper-station completeness (worst first):")
for r in sorted(rows.values(), key=lambda r: -r.n_missing)[:8]:
    got = len(MODEL_COLUMNS) - r.n_missing
    print(f"  {r.location:18s} {got:2d}/{len(MODEL_COLUMNS)} present   missing: {', '.join(r.missing[:6])}")

sample = max(rows.values(), key=lambda r: len(MODEL_COLUMNS) - r.n_missing)
print(f"\nbest-covered station: {sample.location}")
for c in MODEL_COLUMNS:
    v = sample.values[c]
    print(f"  {c:16s} {'-- missing' if v is None else v}")
print(f"  provenance: {sample.provenance}")
for n in sample.notes:
    print(f"  note: {n}")

print("\nschema conformance:")
keys = set(sample.values)
print(f"  columns produced      {len(keys)}")
print(f"  frozen model expects  {len(MODEL_COLUMNS)}")
print(f"  exact match           {keys == set(MODEL_COLUMNS)}")
