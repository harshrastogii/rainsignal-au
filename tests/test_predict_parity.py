"""Prove the live prediction path is the Stage 3 path.

The live layer builds its input from BoM readings rather than from the CSV, so the
risk is not that it crashes -- it is that it quietly produces *different numbers*
through a subtly different route. These tests take real historical weatherAUS rows,
push them through the live code, and require the answers to match the frozen model
called directly, to the bit.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rainsignal.predict import OPTIONAL_FEATURES, load_frozen, predict_rows
from collector.assemble import DailyRow

DATA = Path("/Users/harsh/PRT565/Assessment3/data/weatherAUS.csv")
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="weatherAUS.csv not present")


@pytest.fixture(scope="module")
def frozen():
    return load_frozen()


@pytest.fixture(scope="module")
def historical(frozen):
    """Real rows from the historical record, shaped exactly as the model expects."""
    _, _, meta = frozen
    df = pd.read_csv(DATA, parse_dates=["Date"]).dropna(subset=["RainTomorrow"])
    df = df[df["Location"].isin(["Darwin", "Perth", "Sydney", "AliceSprings", "Hobart"])]
    df = df.dropna(subset=[c for c in meta["input_columns"]
                           if c in df.columns and c not in OPTIONAL_FEATURES]).head(25)
    month = df["Date"].dt.month
    df["Month_sin"] = np.sin(2 * np.pi * month / 12)
    df["Month_cos"] = np.cos(2 * np.pi * month / 12)
    df["TempRange"] = df["MaxTemp"] - df["MinTemp"]
    df["PressureChange"] = df["Pressure3pm"] - df["Pressure9am"]
    df["HumidityChange"] = df["Humidity3pm"] - df["Humidity9am"]
    return df.reset_index(drop=True)


def as_rows(df, meta):
    """Wrap historical rows in the object the assembler emits."""
    out = {}
    for i, rec in df.iterrows():
        vals = {c: (None if pd.isna(rec[c]) else rec[c]) for c in meta["input_columns"]}
        out[f"row{i}"] = DailyRow(location=rec["Location"], obs_date="2020-01-01",
                                  values=vals, missing=[], notes=[])
    return out


def test_live_path_reproduces_the_frozen_model_exactly(frozen, historical):
    pre, ann, meta = frozen
    direct = ann.predict(
        pre.transform(historical[meta["input_columns"]]).astype(np.float32),
        verbose=0).ravel()
    live, _ = predict_rows(as_rows(historical, meta), pre, ann, meta)
    assert len(live) == len(direct)
    np.testing.assert_allclose(np.array(list(live.values())), direct, rtol=0, atol=0)


def test_preprocessing_produces_the_frozen_feature_count(frozen, historical):
    pre, _, meta = frozen
    t = pre.transform(historical[meta["input_columns"]])
    assert t.shape[1] == meta["n_features_after_transform"] == 116


def test_probabilities_are_probabilities(frozen, historical):
    pre, ann, meta = frozen
    live, _ = predict_rows(as_rows(historical, meta), pre, ann, meta)
    assert all(0.0 <= p <= 1.0 for p in live.values())


def test_a_missing_optional_feature_still_predicts(frozen, historical):
    """WindGustDir absent must not withhold: the frozen imputer handles it."""
    pre, ann, meta = frozen
    rows = as_rows(historical.head(3), meta)
    for r in rows.values():
        r.values["WindGustDir"] = None
    live, _ = predict_rows(rows, pre, ann, meta)
    assert len(live) == 3


def test_a_missing_required_feature_withholds_the_station(frozen, historical):
    pre, ann, meta = frozen
    rows = as_rows(historical.head(3), meta)
    list(rows.values())[0].values["Humidity3pm"] = None
    live, ready = predict_rows(rows, pre, ann, meta)
    assert len(live) == 2, "a station missing a required observation must be withheld"


def test_missing_values_reach_the_imputer_as_nan_not_zero(frozen, historical):
    """A None must not become 0.0 -- that would be a real, wrong measurement."""
    pre, ann, meta = frozen
    rows = as_rows(historical.head(1), meta)
    row = list(rows.values())[0]
    row.values["WindGustDir"] = None
    frame = pd.DataFrame([{c: row.values.get(c) for c in meta["input_columns"]}],
                         columns=meta["input_columns"])
    for c in meta["numeric_columns"]:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    assert frame["WindGustDir"].isna().all()
