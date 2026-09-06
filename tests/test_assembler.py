"""Tests for the daily assembler.

The assembler's job is to refuse. Most of these check that it declines to produce a
value rather than stretching, interpolating or mis-dating one.
"""
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.assemble import TOLERANCE_MINUTES, assemble_day
from collector.collect import COLUMNS, setup_db
from rainsignal.schema import MODEL_COLUMNS

LOC = "Darwin"
TZ = "+09:30"
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def put(db, local_iso, **kw):
    """Insert one reading. Unspecified measurements stay NULL."""
    vals = {n: None for n, _ in COLUMNS}
    local = datetime.fromisoformat(local_iso)
    vals.update(location=LOC, bom_id="014015",
                observed_local=local_iso,
                observed_utc=local.astimezone(timezone.utc).isoformat(),
                collected_utc=NOW.isoformat(), n_present=0, n_rejected=0)
    windows = kw.pop("windows", None)
    vals.update(kw)
    if windows:
        vals["windows_json"] = json.dumps(windows)
    db.execute(f"INSERT OR REPLACE INTO observations VALUES ({','.join('?'*len(COLUMNS))})",
               tuple(vals[n] for n, _ in COLUMNS))
    db.commit()


def full_day(db, d="2026-09-07"):
    """A day with everything the schema needs, shaped like real BoM output."""
    put(db, f"{d}T09:00:00{TZ}", air_temp=25.1, humidity=79.0, pressure_msl=1017.9,
        wind_dir="SSW", wind_spd_kmh=6.0,
        min_temp=22.9, rainfall_24hr=6.7,
        windows={"minimum_air_temperature": {"start": f"{d[:-2]}06T18:00:00{TZ}",
                                             "end": f"{d}T09:00:00{TZ}", "instance": "running"},
                 "rainfall_24hr": {"start": f"{d[:-2]}06T09:00:00{TZ}",
                                   "end": f"{d}T09:00:00{TZ}", "instance": None}})
    put(db, f"{d}T15:00:00{TZ}", air_temp=27.9, humidity=71.0, pressure_msl=1013.2,
        wind_dir="NW", wind_spd_kmh=14.7)
    put(db, f"{d}T21:30:00{TZ}", max_temp=28.4, gust_kmh=34.6, gust_dir="NW",
        windows={"maximum_air_temperature": {"start": f"{d}T06:00:00{TZ}",
                                             "end": f"{d}T21:00:00{TZ}", "instance": "running"}})


@pytest.fixture
def db(tmp_path):
    return setup_db(tmp_path / "obs.db")


# ------------------------------------------------------------------ happy path
def test_a_well_covered_day_assembles_completely(db):
    full_day(db)
    r = assemble_day(db.execute("select 1").connection and Path(db.execute(
        "PRAGMA database_list").fetchone()[2]), LOC, date(2026, 9, 7), now_utc=NOW)
    assert r.complete, f"still missing: {r.missing}"
    assert r.values["Temp9am"] == 25.1 and r.values["Temp3pm"] == 27.9
    assert r.values["Humidity9am"] == 79.0 and r.values["Humidity3pm"] == 71.0
    assert r.values["WindDir9am"] == "SSW" and r.values["WindDir3pm"] == "NW"
    assert r.values["MinTemp"] == 22.9 and r.values["MaxTemp"] == 28.4
    assert r.values["Rainfall"] == 6.7 and r.values["RainToday"] == "Yes"
    assert r.values["WindGustSpeed"] == 34.6 and r.values["WindGustDir"] == "NW"


def test_engineered_features_match_the_stage2_definitions(db):
    full_day(db)
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 7), now_utc=NOW)
    assert r.values["TempRange"] == pytest.approx(28.4 - 22.9)
    assert r.values["PressureChange"] == pytest.approx(1013.2 - 1017.9)
    assert r.values["HumidityChange"] == pytest.approx(71.0 - 79.0)
    import math
    assert r.values["Month_sin"] == pytest.approx(math.sin(2 * math.pi * 9 / 12))


def test_output_matches_the_frozen_model_schema_exactly(db):
    full_day(db)
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 7), now_utc=NOW)
    assert set(r.values) == set(MODEL_COLUMNS)


# ------------------------------------------------------------------ refusals
def test_reading_outside_tolerance_is_not_stretched(db):
    d = "2026-09-07"
    put(db, f"{d}T11:00:00{TZ}", air_temp=25.1, humidity=79.0)   # 120 min past 9am
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 7), now_utc=NOW)
    assert r.values["Temp9am"] is None
    assert "Temp9am" in r.missing
    assert any("no reading within" in n for n in r.notes)


def test_reading_inside_tolerance_is_used_and_its_offset_recorded(db):
    d = "2026-09-07"
    put(db, f"{d}T09:30:00{TZ}", air_temp=25.1)                  # 30 min past 9am
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 7), now_utc=NOW)
    assert r.values["Temp9am"] == 25.1
    assert r.provenance["9am"]["offset_min"] == 30.0


def test_the_closest_reading_wins(db):
    d = "2026-09-07"
    put(db, f"{d}T08:30:00{TZ}", air_temp=1.0)
    put(db, f"{d}T09:10:00{TZ}", air_temp=2.0)
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 7), now_utc=NOW)
    assert r.values["Temp9am"] == 2.0


def test_future_readings_are_discarded(db):
    d = "2026-09-07"
    put(db, f"{d}T09:00:00{TZ}", air_temp=25.1)
    put(db, "2026-09-09T09:00:00+09:30", air_temp=99.0)          # after NOW
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 7), now_utc=NOW)
    assert r.values["Temp9am"] == 25.1
    assert any("future" in n for n in r.notes)


def test_a_day_with_no_readings_yields_no_values_and_no_crash(db):
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 1), now_utc=NOW)
    assert not r.complete
    assert set(r.values) == set(MODEL_COLUMNS)
    assert all(r.values[c] is None for c in MODEL_COLUMNS if c != "Location"
               and not c.startswith("Month"))


# ------------------------------------------------- dating the daily aggregates
def test_overnight_minimum_is_dated_by_the_window_it_ends(db):
    """A minimum ending 09:00 on the 8th belongs to the 8th, never the 7th."""
    put(db, f"2026-09-08T09:00:00{TZ}", min_temp=15.0,
        windows={"minimum_air_temperature": {"start": f"2026-09-07T18:00:00{TZ}",
                                             "end": f"2026-09-08T09:00:00{TZ}",
                                             "instance": "running"}})
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    assert assemble_day(p, LOC, date(2026, 9, 8), now_utc=NOW).values["MinTemp"] == 15.0
    assert assemble_day(p, LOC, date(2026, 9, 7), now_utc=NOW).values["MinTemp"] is None


def test_rainfall_is_dated_by_the_window_it_ends(db):
    put(db, f"2026-09-07T09:00:00{TZ}", rainfall_24hr=0.4,
        windows={"rainfall_24hr": {"start": f"2026-09-06T09:00:00{TZ}",
                                   "end": f"2026-09-07T09:00:00{TZ}", "instance": None}})
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 7), now_utc=NOW)
    assert r.values["Rainfall"] == 0.4
    assert r.values["RainToday"] == "No"        # 0.4 mm is below the 1 mm rule
    assert assemble_day(p, LOC, date(2026, 9, 6), now_utc=NOW).values["Rainfall"] is None


def test_an_unclosed_maximum_window_is_not_used(db):
    """A window still accumulating cannot supply a daily maximum."""
    now = datetime(2026, 9, 7, 4, 0, tzinfo=timezone.utc)     # 13:30 local, mid-window
    put(db, f"2026-09-07T13:30:00{TZ}", max_temp=26.0,
        windows={"maximum_air_temperature": {"start": f"2026-09-07T06:00:00{TZ}",
                                             "end": f"2026-09-07T21:00:00{TZ}",
                                             "instance": "running"}})
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 7), now_utc=now)
    assert r.values["MaxTemp"] is None
    assert "MaxTemp" in r.missing


# ------------------------------------------------------------------ integrity
def test_duplicate_readings_are_collapsed_deterministically(db):
    d = "2026-09-07"
    put(db, f"{d}T09:00:00{TZ}", air_temp=25.1)
    db.execute("INSERT OR REPLACE INTO observations (location,bom_id,observed_utc,"
               "observed_local,air_temp) VALUES (?,?,?,?,?)",
               (LOC, "014015",
                datetime.fromisoformat(f"{d}T09:00:00{TZ}").astimezone(timezone.utc).isoformat(),
                f"{d}T09:00:00{TZ}", 25.1))
    db.commit()
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 7), now_utc=NOW)
    assert r.values["Temp9am"] == 25.1


def test_missing_values_are_preserved_as_none_never_filled(db):
    """Gaps must reach the frozen imputer as gaps."""
    d = "2026-09-07"
    put(db, f"{d}T09:00:00{TZ}", air_temp=25.1)      # humidity/pressure absent
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 7), now_utc=NOW)
    assert r.values["Humidity9am"] is None
    assert r.values["Pressure9am"] is None
    assert r.values["PressureChange"] is None       # derived from a gap stays a gap
    assert "Humidity9am" in r.missing


def test_gust_direction_absent_is_reported_not_invented(db):
    d = "2026-09-07"
    put(db, f"{d}T21:30:00{TZ}", gust_kmh=34.6, gust_dir=None)
    p = Path(db.execute("PRAGMA database_list").fetchone()[2])
    r = assemble_day(p, LOC, date(2026, 9, 7), now_utc=NOW)
    assert r.values["WindGustSpeed"] == 34.6
    assert r.values["WindGustDir"] is None
    assert any("gust direction" in n for n in r.notes)
