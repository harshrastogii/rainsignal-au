#!/usr/bin/env python3
"""Durable store for live observations.

Two layers, with one source of truth.

**JSONL, partitioned by UTC observation date** (`observations/YYYY-MM-DD.jsonl`) is
the tracked store. Append-only text diffs cleanly, so a scheduled run adds a handful
of lines to one file instead of rewriting a binary blob. A committed SQLite database
cost a whole new object every run, which at fourteen runs a day would have grown the
repository without bound.

**SQLite is a derived cache**, rebuilt from the JSONL whenever it is missing or stale.
It is git-ignored, exists only to give the assembler fast indexed queries, and can be
deleted at any time without losing data.

Writes are idempotent: a record already present for `(location, observed_utc)` is
skipped, so a re-run or an overlapping schedule adds nothing.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

# Column order is shared with the cache table so the two never drift.
FIELDS = [
    "location", "bom_id", "observed_utc", "observed_local", "collected_utc",
    "air_temp", "max_temp", "min_temp", "humidity", "pressure_msl",
    "wind_dir", "wind_spd_kmh", "gust_kmh", "gust_dir",
    "rainfall", "rainfall_24hr", "n_present", "n_rejected", "windows_json",
]
TYPES = {
    "n_present": "INTEGER", "n_rejected": "INTEGER",
    **{k: "REAL" for k in ("air_temp", "max_temp", "min_temp", "humidity",
                           "pressure_msl", "wind_spd_kmh", "gust_kmh",
                           "rainfall", "rainfall_24hr")},
}


def _partition(store: Path, observed_utc: str) -> Path:
    """The JSONL file a record belongs in, by its UTC observation date."""
    day = (observed_utc or "")[:10] or "unknown"
    return store / "observations" / f"{day}.jsonl"


def existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue                       # a truncated tail must not lose the file
        keys.add((r.get("location"), r.get("observed_utc")))
    return keys


def append(store: Path, records: list[dict]) -> int:
    """Append records that are not already stored. Returns how many were written."""
    by_file: dict[Path, list[dict]] = {}
    for r in records:
        if not r.get("observed_utc"):
            continue                       # without a timestamp there is no identity
        by_file.setdefault(_partition(store, r["observed_utc"]), []).append(r)

    written = 0
    for path, rows in by_file.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        seen = existing_keys(path)
        fresh = []
        for r in rows:
            key = (r["location"], r["observed_utc"])
            if key in seen:
                continue
            seen.add(key)
            fresh.append(r)
        if fresh:
            # Sorted so the file stays stable and diffs stay readable.
            with path.open("a") as fh:
                for r in sorted(fresh, key=lambda x: (x["observed_utc"], x["location"])):
                    fh.write(json.dumps({k: r.get(k) for k in FIELDS},
                                        sort_keys=True) + "\n")
            written += len(fresh)
    return written


def read_all(store: Path):
    """Every stored record, oldest partition first."""
    d = store / "observations"
    if not d.exists():
        return
    for path in sorted(d.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def rebuild_cache(store: Path, cache: Path) -> int:
    """Rebuild the SQLite cache from the JSONL store. Returns rows loaded."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        cache.unlink()
    db = sqlite3.connect(cache)
    cols = ", ".join(f"{f} {TYPES.get(f, 'TEXT')}" for f in FIELDS)
    db.execute(f"CREATE TABLE observations ({cols}, "
               f"PRIMARY KEY (location, observed_utc))")
    db.execute("CREATE INDEX idx_loc_time ON observations(location, observed_utc DESC)")
    n = 0
    for r in read_all(store):
        db.execute(f"INSERT OR IGNORE INTO observations VALUES ({','.join('?'*len(FIELDS))})",
                   tuple(r.get(f) for f in FIELDS))
        n += 1
    db.commit()
    db.close()
    return n


def cache_for(store: Path, cache: Path) -> Path:
    """Return a cache path guaranteed to reflect the JSONL store."""
    rebuild_cache(store, cache)
    return cache
