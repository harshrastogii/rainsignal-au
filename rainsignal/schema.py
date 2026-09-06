"""The frozen contract between Stage 2/3 training and the live layer.

Every constant here must match the notebook exactly. If one changes, the exported
artefacts are invalid and must be rebuilt and re-verified.
"""
from __future__ import annotations

import math

RANDOM_STATE = 42
TARGET = "RainTomorrow"
TEST_SIZE = 0.30

# Dropped in Stage 2 because their absence is structural, not random: 19 of 49 stations
# never record Sunshine, 16 never record Evaporation, 12 never record cloud.
DROPPED_STRUCTURAL = ["Sunshine", "Evaporation", "Cloud3pm", "Cloud9am"]
# Dropped because it is the next day's rainfall, i.e. the answer (proven, 100.0000% match).
LEAKY_COLS = ["RISK_MM"]

RAW_NUMERIC = [
    "MinTemp", "MaxTemp", "Rainfall", "WindGustSpeed",
    "WindSpeed9am", "WindSpeed3pm", "Humidity9am", "Humidity3pm",
    "Pressure9am", "Pressure3pm", "Temp9am", "Temp3pm",
]
RAW_CATEGORICAL = ["Location", "WindGustDir", "WindDir9am", "WindDir3pm", "RainToday"]
ENGINEERED = ["Month_sin", "Month_cos", "TempRange", "PressureChange", "HumidityChange"]

MODEL_COLUMNS = RAW_NUMERIC + ENGINEERED + RAW_CATEGORICAL

# 16-point compass, exactly the vocabulary weatherAUS uses.
COMPASS_16 = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
              "S","SSW","SW","WSW","W","WNW","NW","NNW"]

RAIN_THRESHOLD_MM = 1.0   # weatherAUS defines a rain day as > 1 mm


def degrees_to_compass(deg: float | None) -> str | None:
    """Convert a bearing in degrees to the nearest 16-point compass label."""
    if deg is None or (isinstance(deg, float) and math.isnan(deg)):
        return None
    return COMPASS_16[int((float(deg) % 360) / 22.5 + 0.5) % 16]


# Reference test-set metrics from the Stage 3 notebook run. export_artifacts.py asserts
# against these, so a silent divergence between notebook and artefacts cannot pass.
STAGE3_TEST_METRICS = {
    "Decision Tree":  {"accuracy": 0.8419, "f1": 0.5792, "roc_auc": 0.8336},
    "Random Forest":  {"accuracy": 0.8596, "f1": 0.6141, "roc_auc": 0.8873},
    "Naive Bayes":    {"accuracy": 0.8049, "f1": 0.5759, "roc_auc": 0.8212},
    "Neural Network": {"accuracy": 0.8666, "f1": 0.6444, "roc_auc": 0.8994},
}
