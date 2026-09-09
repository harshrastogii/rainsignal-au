#!/usr/bin/env python3
"""Measure how well the frozen network does at each station, on the held-out test set.

Evaluation only. Nothing is fitted, and the artefacts in models/ are loaded exactly as
exported. This is the evidence behind the interface's "how reliable is this here"
panel, which exists because Stage 3 found skill varies enormously by place -- from
0.401 to 0.778 -- and a single national figure hides that completely.
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np, pandas as pd
from sklearn.metrics import (accuracy_score, f1_score, precision_score,
                             recall_score, roc_auc_score, brier_score_loss)
from sklearn.model_selection import train_test_split

from rainsignal.features import add_engineered
from rainsignal.predict import load_frozen
from rainsignal.schema import DROPPED_STRUCTURAL, LEAKY_COLS, RANDOM_STATE, TARGET, TEST_SIZE

OUT = Path(__file__).resolve().parent / "station_reliability.json"


def main() -> int:
    data = sys.argv[1] if len(sys.argv) > 1 else "/Users/harsh/PRT565/Assessment3/data/weatherAUS.csv"
    pre, ann, meta = load_frozen()

    df = pd.read_csv(data, parse_dates=["Date"]).dropna(subset=[TARGET])
    df = df.drop(columns=LEAKY_COLS + DROPPED_STRUCTURAL)
    df = add_engineered(df)
    y = (df[TARGET] == "Yes").astype(int)
    X = df.drop(columns=[TARGET, "Date"])

    _, X_test, _, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)
    print(f"held-out test rows: {len(X_test):,}")

    prob = ann.predict(pre.transform(X_test[meta["input_columns"]]).astype(np.float32),
                       verbose=0).ravel()
    pred = (prob >= 0.5).astype(int)

    national_f1 = f1_score(y_test, pred)
    out = {"model": meta["primary_model"],
           "evaluated_on": "held-out test split, never seen during training",
           "test_rows": int(len(X_test)),
           "national": {"f1": round(national_f1, 4),
                        "accuracy": round(accuracy_score(y_test, pred), 4),
                        "recall": round(recall_score(y_test, pred), 4),
                        "precision": round(precision_score(y_test, pred), 4)},
           "stations": {}}

    for loc, idx in X_test.groupby("Location").groups.items():
        m = X_test.index.isin(idx)
        yt, yp, pp = y_test[m], pred[m], prob[m]
        if yt.sum() < 5 or (1 - yt).sum() < 5:
            continue                       # too few of one class to score honestly
        out["stations"][loc] = {
            "n_days": int(m.sum()),
            "rain_rate": round(float(yt.mean()), 4),
            "f1": round(float(f1_score(yt, yp)), 4),
            "accuracy": round(float(accuracy_score(yt, yp)), 4),
            "recall": round(float(recall_score(yt, yp)), 4),
            "precision": round(float(precision_score(yt, yp, zero_division=0)), 4),
            "roc_auc": round(float(roc_auc_score(yt, pp)), 4),
            "brier": round(float(brier_score_loss(yt, pp)), 4),
        }

    f1s = {k: v["f1"] for k, v in out["stations"].items()}
    lo, hi = min(f1s, key=f1s.get), max(f1s, key=f1s.get)
    rates = [v["rain_rate"] for v in out["stations"].values()]
    out["summary"] = {
        "stations_scored": len(out["stations"]),
        "worst": {"station": lo, "f1": f1s[lo]},
        "best": {"station": hi, "f1": f1s[hi]},
        "corr_rain_rate_vs_f1": round(float(np.corrcoef(rates, list(f1s.values()))[0, 1]), 4),
    }
    OUT.write_text(json.dumps(out, indent=1))
    print(f"national F1 {national_f1:.4f}")
    print(f"scored {len(out['stations'])} stations: worst {lo} {f1s[lo]:.3f}, "
          f"best {hi} {f1s[hi]:.3f}")
    print(f"correlation with local rain frequency: {out['summary']['corr_rain_rate_vs_f1']}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
