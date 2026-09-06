# Frozen model artefacts

Produced by `export_artifacts.py`, which refits the Stage 2/3 pipeline
deterministically and **verifies the result against the assessment notebook before
writing anything**. If any test metric drifts by more than 0.0002 the export aborts.

```bash
python models/export_artifacts.py --data /path/to/weatherAUS.csv
```

Requires scikit-learn 1.7.2 and TensorFlow 2.21 — the versions the notebook pinned.

## Verification

Every run reproduces the notebook exactly:

| Model | Accuracy | F1 | ROC-AUC |
|---|---|---|---|
| Decision Tree | 0.8419 | 0.5792 | 0.8336 |
| Random Forest | 0.8596 | 0.6141 | 0.8873 |
| Naive Bayes | 0.8049 | 0.5759 | 0.8212 |
| **Neural Network** | **0.8666** | **0.6444** | **0.8994** |

This check earned its place immediately. The first export used
`validation_split=0.25` where the notebook used `0.2`. Keras takes the *last*
fraction of the array without shuffling, so the network saw a different validation
set, early-stopped at a different epoch, and came out with different weights —
F1 0.6608 against the notebook's 0.6444. Every other metric looked fine. Without the
assertion it would have shipped silently.

## What is shipped

| File | Size | Purpose |
|---|---|---|
| `preprocessor.joblib` | 6 KB | the **fitted** imputer, scaler and one-hot encoder |
| `neural_network.keras` | 333 KB | primary model |
| `decision_tree.joblib` | 312 KB | comparison |
| `naive_bayes.joblib` | 5 KB | comparison |
| `metadata.json` | 2 KB | versions, columns, hyperparameters, verified metrics |

`preprocessor.joblib` matters most. It carries the medians, scaling parameters and
category lists learned from the **training split only**. Refitting it on live data
would change what the models see and silently invalidate every number above, so the
live layer loads it and never fits anything.

## Why the Random Forest is not here

It is exported and verified on every run, but not committed. Its 200 unpruned trees
hold **10,029,776 nodes** — 783 MB raw, and still 130 MB at maximum compression,
above GitHub's 100 MB file limit.

Leaving it out costs less than it appears. The Neural Network is the primary model on
the evidence: it beat the forest on every headline metric, in all five
cross-validation folds and at 38 of 49 stations, and it is far better calibrated
(expected calibration error 0.0120 against 0.1021 Brier), which is what makes it
honest to publish its output as a probability.

The four-model comparison is also a *historical* result measured on 80,196 held-out
days. Re-deriving it from 44 live predictions a day would be far weaker evidence, so
the interface reports the Stage 3 comparison rather than recomputing it live.

To produce it anyway:

```bash
python models/export_artifacts.py --data ... --include-rf
```

It is git-ignored, so it stays local unless attached to a release deliberately.

## The primary model

`Neural Network`, because it scored best **and** was best calibrated. Calibration is
the reason the product can show "a 70% chance" and mean it. Naive Bayes must never be
presented as a confidence figure — its calibration error is roughly eleven times
worse, and it placed 59.6% of its predictions below 0.05 and 13.5% above 0.95.
