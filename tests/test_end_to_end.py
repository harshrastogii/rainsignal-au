"""End-to-end rehearsal: BoM-shaped readings -> assembler -> frozen model.

The parity test proves the model call is right but skips the assembler. This one runs
the whole chain. It takes a real historical weatherAUS day, writes the BoM readings
that would have produced it into a real store, assembles them with the real assembler,
predicts with the frozen artefacts, and requires the answer to equal the model applied
directly to the original CSV row.

If the assembler mis-slots a value, mis-dates an aggregate or drops a feature, these
numbers diverge.
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector import store
from collector.assemble import assemble_all
from rainsignal.predict import load_frozen, predict_rows
from rainsignal.stations import COLLECTABLE

DATA = Path("/Users/harsh/PRT565/Assessment3/data/weatherAUS.csv")
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="weatherAUS.csv not present")

LOC, TZ = "Darwin", "+09:30"


@pytest.fixture(scope="module")
def frozen():
    return load_frozen()


@pytest.fixture(scope="module")
def historical_row():
    df = pd.read_csv(DATA, parse_dates=["Date"]).dropna(subset=["RainTomorrow"])
    df = df[df["Location"] == LOC]
    need = ["MinTemp", "MaxTemp", "Rainfall", "WindGustSpeed", "WindGustDir",
            "WindDir9am", "WindDir3pm", "WindSpeed9am", "WindSpeed3pm",
            "Humidity9am", "Humidity3pm", "Pressure9am", "Pressure3pm",
            "Temp9am", "Temp3pm", "RainToday"]
    return df.dropna(subset=need).iloc[0]


def bom_records(rec, d):
    """The readings BoM would have published for this day, with real windows."""
    day, prev = d.isoformat(), (d - timedelta(days=1)).isoformat()
    collected = datetime.now(timezone.utc).isoformat()

    def base(local, **kw):
        r = {f: None for f in store.FIELDS}
        r.update(location=LOC, bom_id=COLLECTABLE[LOC]["bom_id"],
                 observed_local=local,
                 observed_utc=datetime.fromisoformat(local).astimezone(timezone.utc).isoformat(),
                 collected_utc=collected, n_present=0, n_rejected=0)
        r.update(kw)
        return r

    return [
        base(f"{day}T09:00:00{TZ}",
             air_temp=float(rec["Temp9am"]), humidity=float(rec["Humidity9am"]),
             pressure_msl=float(rec["Pressure9am"]), wind_dir=rec["WindDir9am"],
             wind_spd_kmh=float(rec["WindSpeed9am"]),
             min_temp=float(rec["MinTemp"]), rainfall_24hr=float(rec["Rainfall"]),
             windows_json=json.dumps({
                 "minimum_air_temperature": {"start": f"{prev}T18:00:00{TZ}",
                                             "end": f"{day}T09:00:00{TZ}",
                                             "instance": "running"},
                 "rainfall_24hr": {"start": f"{prev}T09:00:00{TZ}",
                                   "end": f"{day}T09:00:00{TZ}", "instance": None}})),
        base(f"{day}T15:00:00{TZ}",
             air_temp=float(rec["Temp3pm"]), humidity=float(rec["Humidity3pm"]),
             pressure_msl=float(rec["Pressure3pm"]), wind_dir=rec["WindDir3pm"],
             wind_spd_kmh=float(rec["WindSpeed3pm"])),
        base(f"{day}T21:30:00{TZ}",
             max_temp=float(rec["MaxTemp"]), gust_kmh=float(rec["WindGustSpeed"]),
             gust_dir=rec["WindGustDir"],
             windows_json=json.dumps({
                 "maximum_air_temperature": {"start": f"{day}T06:00:00{TZ}",
                                             "end": f"{day}T21:00:00{TZ}",
                                             "instance": "running"}})),
    ]


def test_full_chain_matches_the_model_applied_directly(tmp_path, frozen, historical_row):
    pre, ann, meta = frozen
    d = date(2026, 3, 15)          # a date the assembler treats as fully elapsed

    s = tmp_path / "store"
    store.append(s, bom_records(historical_row, d))
    cache = s / "cache.db"
    assert store.rebuild_cache(s, cache) == 3

    rows = assemble_all(cache, d, now_utc=datetime(2026, 3, 17, tzinfo=timezone.utc))
    row = rows[LOC]
    assert row.complete, f"assembler left gaps: {row.missing}"

    live, _ = predict_rows({LOC: row}, pre, ann, meta)
    assert LOC in live

    # the same features, taken straight from the CSV
    direct_input = {c: historical_row.get(c) for c in meta["input_columns"]}
    direct_input["Location"] = LOC
    direct_input["Month_sin"] = np.sin(2 * np.pi * d.month / 12)
    direct_input["Month_cos"] = np.cos(2 * np.pi * d.month / 12)
    direct_input["TempRange"] = historical_row["MaxTemp"] - historical_row["MinTemp"]
    direct_input["PressureChange"] = historical_row["Pressure3pm"] - historical_row["Pressure9am"]
    direct_input["HumidityChange"] = historical_row["Humidity3pm"] - historical_row["Humidity9am"]
    frame = pd.DataFrame([direct_input], columns=meta["input_columns"])
    for c in meta["numeric_columns"]:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    direct = float(ann.predict(pre.transform(frame).astype(np.float32), verbose=0).ravel()[0])

    assert live[LOC] == pytest.approx(direct, abs=1e-6), (
        f"assembled path gave {live[LOC]:.6f}, direct gave {direct:.6f}")


def test_the_assembler_recovers_every_value_it_was_given(tmp_path, historical_row):
    d = date(2026, 3, 15)
    s = tmp_path / "store"
    store.append(s, bom_records(historical_row, d))
    cache = s / "cache.db"
    store.rebuild_cache(s, cache)
    row = assemble_all(cache, d, now_utc=datetime(2026, 3, 17, tzinfo=timezone.utc))[LOC]

    for col in ("Temp9am", "Temp3pm", "Humidity9am", "Humidity3pm",
                "Pressure9am", "Pressure3pm", "WindSpeed9am", "WindSpeed3pm",
                "MinTemp", "MaxTemp", "Rainfall", "WindGustSpeed"):
        assert row.values[col] == pytest.approx(float(historical_row[col])), col
    for col in ("WindDir9am", "WindDir3pm", "WindGustDir", "RainToday"):
        assert row.values[col] == historical_row[col], col
