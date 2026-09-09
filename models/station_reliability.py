#!/usr/bin/env python3
"""Measure how well the frozen network performs at each individual station.

The headline test metrics describe the whole country. Stage 3 found they hide a very
wide spread -- the network's F1 ranged from 0.401 to 0.778 across the 49 towns, and
correlated 0.468 with how often it actually rains there. The interface needs those
per-station numbers so it can tell someone how much to trust a probability *where
they are*, rather than quoting a national average that describes almost nowhere.

Computed from the frozen artefacts on the same held-out test split as Stage 3. Nothing
is trained or refitted here.

    python models/station_reliability.py --data path/to/weatherAUS.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import joblib                                                     # noqa: E402
import numpy as np                                                # noqa: E402
import pandas as pd                                               # noqa: E402
from sklearn.metrics import (accuracy_score, f1_score,            # noqa: E402
                             precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import train_test_split              # noqa: E402

from rainsignal.features import add_engineered                    # noqa: E402
from rainsignal.models import MixedNB                             # noqa: F401,E402
from rainsignal.schema import (DROPPED_STRUCTURAL, LEAKY_COLS,    # noqa: E402
                               RANDOM_STATE, TARGET, TEST_SIZE)

OUT = Path(__file__).resolve().parent / "station_reliability.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    args = ap.parse_args()

    from tensorflow import keras
    meta = json.loads((Path(__file__).parent / "metadata.json").read_text())
    pre = joblib.load(Path(__file__).parent / "preprocessor.joblib")
    ann = keras.models.load_model(Path(__file__).parent / "neural_network.keras")

    df = pd.read_csv(args.data, parse_dates=["Date"]).dropna(subset=[TARGET])
    df = df.drop(columns=LEAKY_COLS + DROPPED_STRUCTURAL)
    df = add_engineered(df)
    y = (df[TARGET] == "Yes").astype(int)
    X = df.drop(columns=[TARGET, "Date"])

    # The identical split Stage 3 used, so this is the same held-out data.
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)
    print(f"test rows {len(X_te):,}")

    proba = ann.predict(pre.transform(X_te).astype(np.float32), verbose=0).ravel()
    pred = (proba >= 0.5).astype(int)

    out = {}
    for loc, idx in X_te.groupby("Location").groups.items():
        pos = X_te.index.get_indexer(idx)
        yt, yp, pp = y_te.loc[idx], pred[pos], proba[pos]
        if yt.nunique() < 2:
            continue                       # AUC is undefined without both classes
        out[loc] = {
            "n_test_days": int(len(yt)),
            "rain_rate": round(float(yt.mean()), 4),
            "accuracy": round(float(accuracy_score(yt, yp)), 4),
            "precision": round(float(precision_score(yt, yp, zero_division=0)), 4),
            "recall": round(float(recall_score(yt, yp)), 4),
            "f1": round(float(f1_score(yt, yp)), 4),
            "roc_auc": round(float(roc_auc_score(yt, pp)), 4),
        }

    f1s = {k: v["f1"] for k, v in out.items()}
    lo, hi = min(f1s, key=f1s.get), max(f1s, key=f1s.get)
    rates = np.array([v["rain_rate"] for v in out.values()])
    corr = float(np.corrcoef(rates, np.array(list(f1s.values())))[0, 1])

    payload = {
        "computed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": meta["primary_model"],
        "measured_on": "the held-out Stage 3 test split, never seen during training",
        "national": meta["test_metrics"][meta["primary_model"]],
        "worst": {"station": lo, "f1": f1s[lo]},
        "best": {"station": hi, "f1": f1s[hi]},
        "rain_rate_f1_correlation": round(corr, 4),
        "stations": out,
    }
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"stations measured {len(out)}")
    print(f"worst {lo} F1 {f1s[lo]:.3f}   best {hi} F1 {f1s[hi]:.3f}   corr {corr:.3f}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
