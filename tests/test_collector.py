"""Tests for the RainSignal collector.

These guard the things that would fail silently: a station mapped to the wrong
place, a bad reading clamped into range instead of dropped, or a gust direction
invented because the model wanted one.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.bom_ftp import Observation, parse_product
from collector.normalise import to_weatherAUS_partial, validate
from rainsignal.schema import MODEL_COLUMNS, degrees_to_compass
from rainsignal.stations import BY_BOM_ID, COLLECTABLE, STATIONS, UNCOLLECTABLE


def obs(bom_id="014015", **elements):
    return Observation(bom_id=bom_id, bom_name="TEST", product="IDD60920",
                       time_local="2026-09-07T09:00:00+09:30",
                       time_utc="2026-09-06T23:30:00+00:00", elements=elements)


# ---------------------------------------------------------------- station map
def test_all_49_weatheraus_locations_present():
    assert len(STATIONS) == 49

def test_collectable_and_uncollectable_partition_cleanly():
    assert len(COLLECTABLE) + len(UNCOLLECTABLE) == 49
    assert not set(COLLECTABLE) & set(UNCOLLECTABLE)

def test_bom_ids_are_unique():
    ids = [v["bom_id"] for v in COLLECTABLE.values()]
    assert len(ids) == len(set(ids)), "a bom_id mapped to two locations"

def test_uncollectable_stations_state_a_reason():
    assert all(isinstance(r, str) and r for r in UNCOLLECTABLE.values())

def test_every_collectable_station_has_coordinates_and_product():
    for name, v in COLLECTABLE.items():
        assert v["lat"] is not None and v["lon"] is not None, name
        assert v["product"] and v["tz"], name


# ---------------------------------------------------------------- validation
def test_unmapped_bom_station_is_skipped_not_guessed():
    assert validate(obs(bom_id="999999")) is None

def test_out_of_range_value_is_dropped_and_recorded_not_clamped():
    r = validate(obs(air_temperature="83.0"))          # 83 C is not a real reading
    assert r.values["air_temperature"] is None
    assert "air_temperature" in r.rejected
    assert "out of range" in r.rejected["air_temperature"]

def test_plausible_value_survives():
    r = validate(obs(air_temperature="26.1"))
    assert r.values["air_temperature"] == 26.1
    assert "air_temperature" not in r.rejected

def test_unparseable_value_is_rejected():
    r = validate(obs(msl_pres="n/a"))
    assert r.values["msl_pres"] is None
    assert "unparseable" in r.rejected["msl_pres"]

def test_invalid_compass_label_is_rejected():
    r = validate(obs(wind_dir="NORTHISH"))
    assert r.values["wind_dir"] is None
    assert "wind_dir" in r.rejected

def test_valid_compass_label_survives():
    assert validate(obs(wind_dir="SSW")).values["wind_dir"] == "SSW"


# ---------------------------------------------------- the no-fabrication rule
def test_missing_gust_direction_stays_missing():
    row = to_weatherAUS_partial(validate(obs(maximum_gust_kmh="45")))
    assert row["WindGustDir"] is None, "WindGustDir must never be invented"
    assert row["WindGustSpeed"] == 45.0

def test_present_gust_direction_is_carried_through():
    row = to_weatherAUS_partial(validate(obs(maximum_gust_dir="NW", maximum_gust_kmh="45")))
    assert row["WindGustDir"] == "NW"

def test_rain_today_follows_the_weatheraus_1mm_rule():
    assert to_weatherAUS_partial(validate(obs(rainfall_24hr="1.2")))["RainToday"] == "Yes"
    assert to_weatherAUS_partial(validate(obs(rainfall_24hr="1.0")))["RainToday"] == "No"
    assert to_weatherAUS_partial(validate(obs(rainfall_24hr="0.0")))["RainToday"] == "No"

def test_rain_today_is_unknown_when_rainfall_is_absent():
    assert to_weatherAUS_partial(validate(obs()))["RainToday"] is None


# ---------------------------------------------------------------- schema tie
def test_normalised_row_uses_only_real_model_columns():
    row = to_weatherAUS_partial(validate(obs()))
    public = {k for k in row if not k.startswith("_")}
    assert public <= set(MODEL_COLUMNS), public - set(MODEL_COLUMNS)

@pytest.mark.parametrize("deg,expected", [(0,"N"), (90,"E"), (180,"S"), (270,"W"),
                                          (22.5,"NNE"), (359,"N"), (360,"N")])
def test_degrees_to_compass(deg, expected):
    assert degrees_to_compass(deg) == expected

def test_degrees_to_compass_handles_none():
    assert degrees_to_compass(None) is None


# ---------------------------------------------------------------- parsing
def test_parse_product_reads_elements_and_identity():
    xml = b"""<?xml version="1.0"?><product><observations>
      <station bom-id="014015" stn-name="DARWIN AIRPORT" lat="-12.4" lon="130.9">
        <period time-local="2026-09-07T09:00:00+09:30" time-utc="2026-09-06T23:30:00+00:00">
          <level><element type="air_temperature" units="Celsius">26.1</element>
                 <element type="maximum_gust_dir">NW</element></level>
        </period></station></observations></product>"""
    got = parse_product(xml, "IDD60920")
    assert len(got) == 1
    assert got[0].bom_id == "014015"
    assert got[0].elements["air_temperature"] == "26.1"
    assert got[0].elements["maximum_gust_dir"] == "NW"

def test_parse_product_tolerates_a_station_with_no_period():
    xml = b"""<?xml version="1.0"?><product><observations>
      <station bom-id="014015" stn-name="X" lat="-12.4" lon="130.9"/>
      </observations></product>"""
    assert parse_product(xml, "IDD60920") == []


# ---------------------------------------------------------------- storage
def test_storage_is_idempotent(tmp_path):
    from collector.collect import setup_db, store
    db = setup_db(tmp_path / "t.db")
    r = validate(obs(air_temperature="26.1"))
    assert store(db, r) == 1
    assert store(db, r) == 0, "the same observation must not be stored twice"
    assert db.execute("select count(*) from observations").fetchone()[0] == 1

def test_reading_without_a_timestamp_is_not_stored(tmp_path):
    from collector.collect import setup_db, store
    db = setup_db(tmp_path / "t.db")
    r = validate(obs(air_temperature="26.1"))
    r.observed_utc = ""
    assert store(db, r) == 0
