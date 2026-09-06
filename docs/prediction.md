# Live prediction layer

Runs the frozen Stage 3 network over assembled observations. `rainsignal/predict.py`.

## What it is, and is not

It produces **an estimate from a model, computed from weather that has already
happened**. It is not a Bureau of Meteorology forecast, and every record it writes
carries `not_a_bureau_forecast: true` plus a disclaimer pointing to bom.gov.au.

## Guarantees

**Only completed observation days.** A day is eligible when the assembler filled every
required feature from readings that had already occurred. A day still in progress
cannot qualify — its aggregate windows have not closed.

**No forecast value is ever an observation.** The collector reads BoM's observation
products, which carry measurements only, and the assembler discards any reading
timestamped after the moment of assembly.

**Missing values pass through untouched.** The frozen `SimpleImputer`, fitted on the
Stage 2 training split, is the only thing that fills a gap — exactly as in training.
Numeric gaps are converted to `NaN` rather than left as `None`, because the fitted
imputer only recognises `NaN`; a `None` silently coerced to `0.0` would be a real and
wrong measurement.

**Both dates are recorded.** `observation_date` is when the weather was measured;
`target_date` is the following day, which the probability refers to.

**A probability, never a label.** Stage 3 measured every model's best threshold near
0.31 rather than 0.5, so publishing yes/no would impose an invisible choice. The
network's expected calibration error was 0.0120, which is what makes reporting its
output as a probability defensible.

**Incomplete stations are named, not guessed.** Each withheld station is listed with
exactly which required features were absent.

`WindGustDir` is the single optional feature. BoM omits it at a few stations and no
comparable public source publishes it, so requiring it would withhold otherwise
complete stations. The frozen imputer handles it exactly as during training.

## Verification

Two independent checks, both automated.

**Parity** (`tests/test_predict_parity.py`) — real historical rows through the live
code must equal the frozen model called directly, asserted at `rtol=0, atol=0`.

**End to end** (`tests/test_end_to_end.py`) — a real historical day is written into a
real store as BoM-shaped readings, assembled by the real assembler, and predicted.
The answer must equal the model applied straight to the CSV row. If the assembler
mis-slots a value, mis-dates an aggregate or drops a feature, this diverges.

## Running

```bash
python -m rainsignal.predict --store data/live [--date YYYY-MM-DD]
```

Needs scikit-learn 1.7.2 and TensorFlow 2.21. Writes `predictions.json`.
