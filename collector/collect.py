#!/usr/bin/env python3
"""RainSignal collector -- polls BoM observation products and stores new readings.

Runs on a schedule. Each run fetches the seven state observation products over
anonymous FTP, keeps the readings belonging to our 44 curated stations, validates
them, and appends anything new to SQLite.

Storage is idempotent: the primary key is (location, observed_utc), so re-running
inserts nothing twice and a missed run costs freshness, never completeness.

Live observations are written to data/live/. Historical training data is not touched
by this process and lives elsewhere; the two never share a file.

The process collects and reports. It does not retrain, and it does not predict.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector import store                                       # noqa: E402
from collector.bom_ftp import fetch_all, log                      # noqa: E402
from collector.normalise import to_weatherAUS_partial, validate   # noqa: E402
from rainsignal.stations import COLLECTABLE, PRODUCTS, UNCOLLECTABLE  # noqa: E402

# Where this run writes. `data/live` is TRACKED and belongs to the scheduled Action
# alone; the workflow sets RAINSIGNAL_STORE explicitly. A local run defaults to
# `data/local`, which is git-ignored, so running the collector on a laptop can never
# collide with the Action's commits.
STORE = Path(os.environ.get("RAINSIGNAL_STORE", "data/local"))
# Derived, never tracked. Rebuilt from the JSONL store on demand.
CACHE = Path(os.environ.get("RAINSIGNAL_CACHE", STORE / "cache.db"))
HEALTH_PATH = STORE / "health.json"
LATEST_PATH = STORE / "latest.json"

# A station whose newest reading is older than this is stale. BoM publishes most
# stations every 30 minutes; some remote sites report hourly or less often.
STALE_MINUTES = int(os.environ.get("RAINSIGNAL_STALE_MINUTES", "180"))

# Kept for the tests and for anything still holding a cache connection; the column
# set is defined once in store.FIELDS so the two cannot drift apart.
COLUMNS = [(f, store.TYPES.get(f, "TEXT")) for f in store.FIELDS]


def setup_db(path: Path) -> sqlite3.Connection:
    """Create or open the derived cache. Retained for the assembler and the tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    cols = ", ".join(f"{n} {t}" for n, t in COLUMNS)
    db.execute(f"CREATE TABLE IF NOT EXISTS observations ({cols}, "
               f"PRIMARY KEY (location, observed_utc))")
    db.execute("CREATE INDEX IF NOT EXISTS idx_loc_time "
               "ON observations(location, observed_utc DESC)")
    have = {r[1] for r in db.execute("PRAGMA table_info(observations)")}
    for name, decl in COLUMNS:
        if name not in have:
            db.execute(f"ALTER TABLE observations ADD COLUMN {name} {decl}")
    db.commit()
    return db


def to_record(reading) -> dict:
    """Flatten a validated Reading into the stored record shape."""
    v = reading.values
    return {
        "location": reading.location, "bom_id": reading.bom_id,
        "observed_utc": reading.observed_utc, "observed_local": reading.observed_local,
        "collected_utc": reading.collected_utc,
        "air_temp": v.get("air_temperature"),
        "max_temp": v.get("maximum_air_temperature"),
        "min_temp": v.get("minimum_air_temperature"),
        "humidity": v.get("rel-humidity"),
        "pressure_msl": (v.get("msl_pres") if v.get("msl_pres") is not None
                         else v.get("pres")),
        "wind_dir": v.get("wind_dir"), "wind_spd_kmh": v.get("wind_spd_kmh"),
        "gust_kmh": v.get("maximum_gust_kmh"), "gust_dir": v.get("maximum_gust_dir"),
        "rainfall": v.get("rainfall"), "rainfall_24hr": v.get("rainfall_24hr"),
        "n_present": reading.n_present, "n_rejected": len(reading.rejected),
        "windows_json": json.dumps(reading.windows) if reading.windows else None,
    }


def store_reading(db: sqlite3.Connection, reading) -> int:
    """Insert one reading into the cache, ignoring a duplicate."""
    if not reading.observed_utc:
        return 0                       # without a timestamp there is no primary key
    rec = to_record(reading)
    before = db.total_changes
    db.execute(
        f"INSERT OR IGNORE INTO observations VALUES ({','.join('?' * len(COLUMNS))})",
        tuple(rec[n] for n, _ in COLUMNS))
    return db.total_changes - before


def age_minutes(observed_utc: str) -> int | None:
    try:
        seen = datetime.fromisoformat(observed_utc)
    except (TypeError, ValueError):
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - seen).total_seconds() / 60)


def run_once() -> int:
    started = datetime.now(timezone.utc)

    # ---- phase 1: network only ----
    by_product, fetch_errors = fetch_all(PRODUCTS)

    # ---- phase 2: validate and store, serially on this thread ----
    readings, unmapped = {}, 0
    for observations in by_product.values():
        for observation in observations:
            reading = validate(observation)
            if reading is None:
                unmapped += 1
                continue
            readings[reading.location] = reading

    # JSONL is the durable store; the cache is rebuilt from it afterwards.
    inserted_total = store.append(
        STORE, [to_record(r) for r in readings.values() if r.observed_utc])
    cached = store.rebuild_cache(STORE, CACHE)

    # ---- health ----
    per_station, stale, missing_fields = [], [], {}
    for location in sorted(COLLECTABLE):
        reading = readings.get(location)
        if reading is None:
            per_station.append({"location": location, "ok": False,
                                "reason": "not present in this run's feed"})
            continue
        age = age_minutes(reading.observed_utc)
        is_stale = age is not None and age > STALE_MINUTES
        if is_stale:
            stale.append({"location": location, "age_min": age})
        row = to_weatherAUS_partial(reading)
        absent = [k for k, val in row.items() if not k.startswith("_") and val is None]
        for field_name in absent:
            missing_fields.setdefault(field_name, []).append(location)
        per_station.append({
            "location": location, "ok": True, "stale": is_stale,
            "observed_utc": reading.observed_utc, "age_min": age,
            "fields_present": reading.n_present,
            "fields_rejected": reading.rejected or None,
            "fields_absent": absent or None,
        })

    ok = [s for s in per_station if s["ok"]]
    health = {
        "run_utc": started.isoformat(timespec="seconds"),
        "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        "source": "Bureau of Meteorology, anonymous FTP observation products",
        "products_requested": PRODUCTS,
        "products_failed": fetch_errors or None,
        "stations_expected": len(COLLECTABLE),
        "stations_reporting": len(ok),
        "stations_stale": len(stale),
        "stations_missing": [s["location"] for s in per_station if not s["ok"]],
        "stale_detail": stale or None,
        "rows_inserted": inserted_total,
        "bom_stations_ignored_unmapped": unmapped,
        "locations_not_collectable": UNCOLLECTABLE,
        "fields_absent_by_field": {k: len(v) for k, v in sorted(missing_fields.items())},
        "detail": per_station,
    }
    health["store"] = str(STORE)
    health["rows_in_store"] = cached
    HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_PATH.write_text(json.dumps(health, indent=1))

    # A small snapshot the frontend can read without opening the database.
    LATEST_PATH.write_text(json.dumps({
        "generated_utc": health["run_utc"],
        "source": health["source"],
        "attribution": "Bureau of Meteorology, © Commonwealth of Australia.",
        "stale_after_minutes": STALE_MINUTES,
        "observations": {
            loc: {**{k: v for k, v in to_weatherAUS_partial(r).items()
                     if not k.startswith("_")},
                  "observed_utc": r.observed_utc,
                  "observed_local": r.observed_local,
                  "age_min": age_minutes(r.observed_utc)}
            for loc, r in sorted(readings.items())
        },
    }, indent=1))

    log("-" * 62)
    log(f"reporting {len(ok)}/{len(COLLECTABLE)}  stale {len(stale)}  "
        f"new rows {inserted_total}  store total {cached}  "
        f"unmapped BoM stations ignored {unmapped}")
    if missing_fields:
        for field_name, locs in sorted(missing_fields.items()):
            log(f"  absent: {field_name:14s} at {len(locs)} station(s)")
    # Fail loudly only when the run produced nothing usable, so a partial BoM
    # outage degrades the product instead of breaking the schedule.
    if not ok:
        log("no station reported -- exiting non-zero")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run_once())
