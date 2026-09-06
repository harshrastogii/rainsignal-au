#!/usr/bin/env python3
"""Refit the Stage 2/3 pipeline deterministically and freeze it to disk.

This is not a retraining step. Every constant, seed and hyperparameter is the one the
assessment notebook established, so the fit is reproducible rather than new. The run
asserts the resulting test metrics against the values the notebook recorded; if any
of them drift, the export fails rather than quietly shipping different models.

    python models/export_artifacts.py --data path/to/weatherAUS.csv

Run it with an environment that has scikit-learn 1.7.2 and TensorFlow 2.21 -- the
versions the notebook pinned.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("PYTHONHASHSEED", "42")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import joblib                                                    # noqa: E402
import numpy as np                                               # noqa: E402
import pandas as pd                                              # noqa: E402
from sklearn.compose import ColumnTransformer                    # noqa: E402
from sklearn.ensemble import RandomForestClassifier              # noqa: E402
from sklearn.impute import SimpleImputer                         # noqa: E402
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score  # noqa: E402
from sklearn.model_selection import train_test_split             # noqa: E402
from sklearn.pipeline import Pipeline                            # noqa: E402
from sklearn.preprocessing import OneHotEncoder, StandardScaler   # noqa: E402
from sklearn.tree import DecisionTreeClassifier                  # noqa: E402

from rainsignal.features import add_engineered                   # noqa: E402
from rainsignal.models import MixedNB                            # noqa: E402
from rainsignal.schema import (DROPPED_STRUCTURAL, LEAKY_COLS, RANDOM_STATE,  # noqa: E402
                               STAGE3_TEST_METRICS, TARGET, TEST_SIZE)

OUT = Path(__file__).resolve().parent
TOLERANCE = 0.0002          # metrics are quoted to 4 dp in the notebook

# Selected on validation in Stage 2. Not tuned here.
DT_DEPTH = 12
RF_PARAMS = {"n_estimators": 200, "max_depth": None, "min_samples_leaf": 1}
ANN_HIDDEN, ANN_DROPOUT = (128, 64, 32), 0.3


def build_preprocessor(frame):
    num = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    cat = [c for c in frame.columns if c not in num]
    return ColumnTransformer([
        ("num", Pipeline([("impute", SimpleImputer(strategy="median")),
                          ("scale", StandardScaler())]), num),
        ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                          ("onehot", OneHotEncoder(handle_unknown="ignore",
                                                   sparse_output=False))]), cat),
    ]), num, cat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="path to weatherAUS.csv")
    ap.add_argument("--include-rf", action="store_true",
                    help="also write the Random Forest (~780 MB uncompressed; too "
                         "large for git, see models/README.md)")
    args = ap.parse_args()

    import random
    import tensorflow as tf
    from tensorflow import keras
    random.seed(RANDOM_STATE)
    np.random.seed(RANDOM_STATE)
    keras.utils.set_random_seed(RANDOM_STATE)

    print(f"loading {args.data}")
    df = pd.read_csv(args.data, parse_dates=["Date"]).dropna(subset=[TARGET])
    df = df.drop(columns=LEAKY_COLS + DROPPED_STRUCTURAL)
    df = add_engineered(df)

    y = (df[TARGET] == "Yes").astype(int)
    X = df.drop(columns=[TARGET, "Date"])

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)
    print(f"train {len(X_train):,}  test {len(X_test):,}")

    pre, num, cat = build_preprocessor(X_train)
    pre.fit(X_train, y_train)
    T_train = pre.transform(X_train).astype(np.float32)
    T_test = pre.transform(X_test).astype(np.float32)
    n_num = len(num)
    print(f"features {X_train.shape[1]} -> {T_train.shape[1]} "
          f"({n_num} numeric + {T_train.shape[1] - n_num} one-hot)")

    fitted, metrics = {}, {}

    def score(name, proba, pred):
        m = {"accuracy": accuracy_score(y_test, pred),
             "f1": f1_score(y_test, pred),
             "roc_auc": roc_auc_score(y_test, proba)}
        metrics[name] = {k: round(v, 4) for k, v in m.items()}
        print(f"  {name:16s} acc={m['accuracy']:.4f} f1={m['f1']:.4f} auc={m['roc_auc']:.4f}")
        return m

    print("fitting:")
    dt = DecisionTreeClassifier(max_depth=DT_DEPTH, criterion="entropy",
                                random_state=RANDOM_STATE).fit(T_train, y_train)
    fitted["Decision Tree"] = dt
    score("Decision Tree", dt.predict_proba(T_test)[:, 1], dt.predict(T_test))

    rf = RandomForestClassifier(**RF_PARAMS, n_jobs=-1,
                                random_state=RANDOM_STATE).fit(T_train, y_train)
    fitted["Random Forest"] = rf
    score("Random Forest", rf.predict_proba(T_test)[:, 1], rf.predict(T_test))

    nb = MixedNB(n_numeric=n_num).fit(T_train, y_train.values)
    fitted["Naive Bayes"] = nb
    score("Naive Bayes", nb.predict_proba(T_test)[:, 1], nb.predict(T_test))

    keras.utils.set_random_seed(RANDOM_STATE)
    layers = [keras.layers.Input(shape=(T_train.shape[1],))]
    for h in ANN_HIDDEN:
        layers += [keras.layers.Dense(h, activation="relu"),
                   keras.layers.Dropout(ANN_DROPOUT)]
    layers += [keras.layers.Dense(1, activation="sigmoid")]
    ann = keras.Sequential(layers)
    ann.compile(optimizer=keras.optimizers.Adam(1e-3),
                loss="binary_crossentropy", metrics=["accuracy"])
    stop = keras.callbacks.EarlyStopping(monitor="val_loss", patience=5,
                                         restore_best_weights=True)
    # validation_split=0.2 matches the notebook exactly. It is not a free choice:
    # Keras takes the LAST fraction of the array without shuffling, so 0.25 gives a
    # different validation set, stops at a different epoch, and yields different
    # weights. The verification below catches precisely that.
    ann.fit(T_train, y_train.values, validation_split=0.2, epochs=60,
            batch_size=512, verbose=0, callbacks=[stop])
    proba = ann.predict(T_test, verbose=0).ravel()
    score("Neural Network", proba, (proba >= 0.5).astype(int))

    # ---- verify against the notebook before writing anything ----
    print("\nverifying against the Stage 3 notebook:")
    drift = []
    for name, expected in STAGE3_TEST_METRICS.items():
        for metric, want in expected.items():
            got = metrics[name][metric]
            delta = abs(got - want)
            flag = "ok" if delta <= TOLERANCE else "DRIFT"
            if delta > TOLERANCE:
                drift.append(f"{name}.{metric}: notebook {want}, export {got}")
            print(f"  {name:16s} {metric:9s} notebook={want:.4f} export={got:.4f}  {flag}")
    if drift:
        print("\nEXPORT ABORTED — artefacts do not reproduce the notebook:")
        for d in drift:
            print("  " + d)
        return 1

    # ---- write ----
    OUT.mkdir(parents=True, exist_ok=True)
    joblib.dump(pre, OUT / "preprocessor.joblib")
    joblib.dump(fitted["Decision Tree"], OUT / "decision_tree.joblib")
    # The Random Forest is verified above but not written by default. Its 200
    # unpruned trees hold 10,029,776 nodes: 783 MB raw, still 130 MB at maximum
    # compression, over GitHub's 100 MB limit. See models/README.md.
    if args.include_rf:
        joblib.dump(fitted["Random Forest"], OUT / "random_forest.joblib", compress=3)
    joblib.dump(fitted["Naive Bayes"], OUT / "naive_bayes.joblib")
    ann.save(OUT / "neural_network.keras")

    import sklearn
    (OUT / "metadata.json").write_text(json.dumps({
        "exported_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_notebook": "PRT565_A3_Notebook_Group85.ipynb",
        "random_state": RANDOM_STATE,
        "versions": {"scikit-learn": sklearn.__version__,
                     "tensorflow": tf.__version__, "keras": keras.__version__,
                     "numpy": np.__version__, "pandas": pd.__version__},
        "training_rows": int(len(X_train)), "test_rows": int(len(X_test)),
        "input_columns": list(X_train.columns),
        "numeric_columns": num, "categorical_columns": cat,
        "n_numeric_after_transform": int(n_num),
        "n_features_after_transform": int(T_train.shape[1]),
        "hyperparameters": {"decision_tree": {"max_depth": DT_DEPTH, "criterion": "entropy"},
                            "random_forest": RF_PARAMS,
                            "neural_network": {"hidden": list(ANN_HIDDEN),
                                               "dropout": ANN_DROPOUT}},
        "test_metrics": metrics,
        "verified_against_notebook": True,
        "models_shipped": ["Decision Tree", "Naive Bayes", "Neural Network"]
                          + (["Random Forest"] if args.include_rf else []),
        "random_forest_shipped": bool(args.include_rf),
        "random_forest_note": ("verified against the notebook every run, but not "
                               "stored in git: 200 unpruned trees, 10,029,776 nodes, "
                               "130 MB even at maximum compression"),
        "primary_model": "Neural Network",
        "primary_model_reason": ("best F1 and best calibrated (ECE 0.0120), so its "
                                 "probabilities can be reported as probabilities"),
    }, indent=1))
    print(f"\nwrote artefacts to {OUT}")
    for f in sorted(OUT.glob("*")):
        if f.suffix in (".joblib", ".keras", ".json"):
            print(f"  {f.name:26s} {f.stat().st_size/1024:8.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
