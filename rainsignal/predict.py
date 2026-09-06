#!/usr/bin/env python3
"""Run the frozen Stage 3 model over assembled live observations.

This produces an *estimate from a model*, from observations that have already
happened. It is not a Bureau of Meteorology forecast and must never be presented as
one. Every record it writes says so explicitly.

What it guarantees
------------------
Only completed observation days are used. A day is eligible when the assembler could
fill every required feature from readings that had already occurred; a day still in
progress cannot qualify, because its aggregate windows have not closed.

No forecast value is ever treated as an observation. The collector reads BoM's
observation products, which contain measurements only, and the assembler discards any
reading timestamped after the moment of assembly.

Missing values pass through untouched. The frozen `SimpleImputer`, fitted on the Stage
2 training split, is the only thing that fills a gap -- exactly as it did in training.
Nothing here substitutes, interpolates or carries a value forward.

Both dates are recorded. `observation_date` is the day the weather was measured;
`target_date` is the following day, the one the probability refers to. Conflating them
is the easiest way to make a prediction look better than it is.

The output is a probability, never a label. Stage 3 measured every model's best
threshold near 0.31 rather than 0.5, so publishing a yes/no would silently impose a
choice the reader cannot see. The network's expected calibration error was 0.0120,
which is what makes reporting its output as a probability honest in the first place.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODELS = Path(__file__).resolve().parent.parent / "models"

# WindGustDir is excluded from the requirement on purpose: BoM publishes no gust
# direction at a handful of stations, and Open-Meteo publishes none at all. Demanding
# it would withhold predictions for stations whose data is otherwise complete, while
# the frozen imputer already handles the gap the same way it did during training.
# Every other feature must be genuinely present.
OPTIONAL_FEATURES = {"WindGustDir"}


def load_frozen():
    """Load the artefacts exactly as exported. Nothing here is fitted."""
    import joblib
    from tensorflow import keras
    from rainsignal.models import MixedNB          # noqa: F401  (unpickling needs it)

    meta = json.loads((MODELS / "metadata.json").read_text())
    pre = joblib.load(MODELS / "preprocessor.joblib")
    ann = keras.models.load_model(MODELS / "neural_network.keras")
    return pre, ann, meta


def eligible(row, meta) -> tuple[bool, list]:
    """Is this assembled row complete enough to predict from?"""
    required = [c for c in meta["input_columns"] if c not in OPTIONAL_FEATURES]
    absent = [c for c in required if row.values.get(c) is None]
    return (not absent), absent


def predict_rows(rows, pre, ann, meta):
    """Run the frozen pipeline over eligible assembled rows."""
    import numpy as np
    import pandas as pd

    columns = meta["input_columns"]
    ready = {loc: r for loc, r in rows.items() if eligible(r, meta)[0]}
    if not ready:
        return {}, {}

    frame = pd.DataFrame(
        [{c: r.values.get(c) for c in columns} for r in ready.values()],
        columns=columns)
    # Numeric columns must carry NaN, not None, or the fitted imputer will not see
    # them as missing.
    for c in meta["numeric_columns"]:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")

    transformed = pre.transform(frame).astype(np.float32)
    if transformed.shape[1] != meta["n_features_after_transform"]:
        raise AssertionError(
            f"frozen preprocessing produced {transformed.shape[1]} features, "
            f"expected {meta['n_features_after_transform']}")

    probs = ann.predict(transformed, verbose=0).ravel()
    return dict(zip(ready.keys(), (float(p) for p in probs))), ready


def build_output(probabilities, ready, rows, meta, obs_date):
    target = obs_date + timedelta(days=1)
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "observation_date": obs_date.isoformat(),
        "target_date": target.isoformat(),
        "what_this_is": (
            "A machine-learning estimate of the chance of more than 1 mm of rain on "
            "the target date, computed from completed observations recorded on the "
            "observation date."),
        "not_a_bureau_forecast": True,
        "disclaimer": (
            "This is a model estimate produced by a student project, not a forecast "
            "issued by the Bureau of Meteorology. For official forecasts see "
            "bom.gov.au."),
        "observation_source": "Bureau of Meteorology, © Commonwealth of Australia",
        "model": {
            "name": meta["primary_model"],
            "trained_on": "weatherAUS historical record, frozen after Stage 3",
            "test_metrics": meta["test_metrics"][meta["primary_model"]],
            "reports": "probability, not a yes/no label",
            "note": ("Stage 3 measured the best decision threshold near 0.31 rather "
                     "than 0.5, so no label is imposed here."),
        },
        "stations_predicted": len(probabilities),
        "stations_withheld": len(rows) - len(probabilities),
        "predictions": {},
        "withheld": {},
    }
    for loc, p in sorted(probabilities.items()):
        r = ready[loc]
        out["predictions"][loc] = {
            "rain_probability": round(p, 4),
            "observation_date": obs_date.isoformat(),
            "target_date": target.isoformat(),
            "inputs_present": len(meta["input_columns"]) - r.n_missing,
            "inputs_total": len(meta["input_columns"]),
            "imputed_by_frozen_pipeline": r.missing or None,
            "provenance": r.provenance,
        }
    for loc, r in sorted(rows.items()):
        if loc in probabilities:
            continue
        out["withheld"][loc] = {
            "reason": "required observations incomplete",
            "missing": eligible(r, meta)[1],
            "notes": r.notes or None,
        }
    return out


def main() -> int:
    import argparse
    from collector import store
    from collector.assemble import assemble_all

    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.environ.get("RAINSIGNAL_STORE", "data/live"))
    ap.add_argument("--date", help="observation date (station-local); "
                                   "default is the most recent completed day")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    store_dir = Path(args.store)
    cache = store_dir / "cache.db"
    n = store.rebuild_cache(store_dir, cache)
    obs_date = (date.fromisoformat(args.date) if args.date
                else datetime.now(timezone.utc).date() - timedelta(days=1))
    print(f"store {store_dir}  ({n} readings)")
    print(f"observation date {obs_date}  ->  target date {obs_date + timedelta(days=1)}")

    pre, ann, meta = load_frozen()
    print(f"frozen model: {meta['primary_model']}  "
          f"(sklearn {meta['versions']['scikit-learn']}, tf {meta['versions']['tensorflow']})")

    rows = assemble_all(cache, obs_date)
    probs, ready = predict_rows(rows, pre, ann, meta)
    out = build_output(probs, ready, rows, meta, obs_date)

    dest = Path(args.out) if args.out else store_dir / "predictions.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1))
    print(f"predicted {out['stations_predicted']} station(s), "
          f"withheld {out['stations_withheld']}")
    print(f"wrote {dest}")
    if not probs:
        print("\nno station had a complete set of completed observations for this "
              "date; nothing was predicted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
