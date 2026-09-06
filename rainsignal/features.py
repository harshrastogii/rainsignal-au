"""Feature engineering shared by training and the live prediction layer.

Kept apart from `schema.py` because it needs numpy and pandas, while the collector
must stay standard-library only so it can run on a bare GitHub Actions runner.
"""
from __future__ import annotations

import numpy as np

def add_engineered(frame):
    """Derive the five Stage 2 features. `frame` needs a `Date` column."""
    month = frame["Date"].dt.month
    frame["Month_sin"] = np.sin(2 * np.pi * month / 12)
    frame["Month_cos"] = np.cos(2 * np.pi * month / 12)
    frame["TempRange"] = frame["MaxTemp"] - frame["MinTemp"]
    frame["PressureChange"] = frame["Pressure3pm"] - frame["Pressure9am"]
    frame["HumidityChange"] = frame["Humidity3pm"] - frame["Humidity9am"]
    return frame


