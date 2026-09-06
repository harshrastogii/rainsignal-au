# RainSignal AU

An interactive view of Australian rainfall and what a machine learning model can —
and cannot — tell you about tomorrow's rain, station by station.

Built for **PRT565 Machine Learning, Artificial Intelligence and Algorithms**,
Charles Darwin University, Darwin (Danala) Campus.

**Group 85** — Harsh Rastogi, Saira Zafar, Tharushi Wimalachandra.

## Status

| Component | State |
|---|---|
| Data collector | **built and running** — see [docs/collector.md](docs/collector.md) |
| Frozen model artefacts | not yet exported |
| Live prediction layer | not yet built |
| Frontend | not yet built |

## What this is

The models were trained and evaluated on the historical `weatherAUS` record — 267,317
station-days from 49 towns over 18 years — as part of the assessment's analysis
notebook. That work is finished and frozen.

This repository is the live layer built on top of it: a collector that fetches current
Bureau of Meteorology observations, and (once built) a frontend that runs the frozen
model against them.

Two things are kept strictly apart:

- **historical training data and trained models** — frozen, never touched by live data
- **live observations and current predictions** — appended, never fed back into training

New observations do not trigger retraining. The academic result stays exactly as it
was measured.

## Honesty rules the code enforces

- **Nothing is fabricated.** `WindGustDir` is left missing when BoM does not publish
  it, rather than derived from something else. Gap-filling belongs to the frozen
  pipeline's imputer, which was fitted on the training split.
- **Nothing is clamped.** A reading outside a plausible physical range is dropped and
  recorded, because a clamped value looks exactly like a real one.
- **Stations are matched by ID, never by name.** Fuzzy matching silently mapped
  `Uluru` to a station in New South Wales; the mapping is curated by `bom_id`.
- **Observations and predictions are never conflated.** An observed value and a model
  estimate are different things and are labelled as such.
- **Stale data is shown as stale**, not quietly served as current.

## Layout

```
collector/    fetch, validate, normalise, store
rainsignal/   frozen schema contract + curated station map
data/live/    live observations (SQLite) + health + latest snapshot
tests/        collector test suite
docs/         component documentation
```

## Running

```bash
python collector/collect.py     # collect current observations
python -m pytest tests/ -q      # 28 tests
```

The collector imports only the standard library, so it runs on a bare runner.
`rainsignal/features.py` needs numpy and is used by the prediction layer, not the
collector. `requirements-dev.txt` covers tests.

## Data source

Bureau of Meteorology observation products via the anonymous FTP service, used with
permission for research and educational purposes.

Attribution: Bureau of Meteorology, © Commonwealth of Australia.

Historical training data: Young, J. (2020). *Rain in Australia* [Data set]. Kaggle;
originally distributed with the `rattle` package (Williams, 2011).
