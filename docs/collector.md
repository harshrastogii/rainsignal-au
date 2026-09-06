# RainSignal collector

Polls the Bureau of Meteorology for current observations, validates them, and stores
them for the live layer. It collects and reports. It does not predict, and it never
retrains a model.

## Source

BoM's anonymous FTP service, `ftp://ftp.bom.gov.au/anon/gen/fwo/`, reading the seven
state observation products:

| Product | Coverage | Our stations |
|---|---|---|
| IDN60920 | NSW / ACT | 17 |
| IDV60920 | VIC | 8 |
| IDW60920 | WA | 7 |
| IDQ60920 | QLD | 4 |
| IDS60920 | SA | 4 |
| IDT60920 | TAS | 2 |
| IDD60920 | NT | 2 |

FTP rather than the website is deliberate. `www.bom.gov.au` returns HTTP 403 to
automated requests and directs machine access to this channel. It is also the better
feed: it publishes `maximum_gust_dir`, which the alternatives evaluated do not carry
at all, and seven files cover every station instead of forty-four separate requests.

Attribution: Bureau of Meteorology, © Commonwealth of Australia.

## Station mapping

`rainsignal/stations.json` maps each of the 49 weatherAUS `Location` values to a BoM
station, keyed on `bom_id`, which is stable. Station *names* are not stable and are
never matched fuzzily.

That is not a stylistic preference. Fuzzy matching was tried first and produced
silently wrong stations: `Uluru` matched `MULURULU AWS`, a station in New South
Wales, and `Nhil` matched `BROKE-N-HIL-L AIRPORT`. Both would have fed the model a
real observation from the wrong part of the country, and nothing downstream would
have noticed.

**44 of 49 locations are collectable.** Katherine, Nhil, Uluru, Watsonia and
Wollongong have no station in the live products. They are recorded with
`collectable: false` and a stated reason, and are reported as unavailable rather
than filled from a nearby site.

## What it does each run

1. Fetch the seven products over FTP, retrying transient failures twice with backoff.
2. Parse one reading per station and keep the 44 we curated. Unmapped BoM stations
   are ignored, not approximated — the model's `Location` is a fixed one-hot over 49
   towns and has no slot for them.
3. Validate. A value outside a physically plausible range is **dropped and recorded**,
   never clamped, because a clamped value is indistinguishable from a real one.
   Wind directions must be one of the 16 compass labels weatherAUS uses.
4. Normalise onto weatherAUS column names.
5. Append to SQLite. The primary key is `(location, observed_utc)` and inserts ignore
   duplicates, so runs are idempotent and a missed run backfills on the next one.
6. Write `health.json` and a `latest.json` snapshot for the frontend.

## The no-fabrication rule

`WindGustDir` is left as `None` when BoM does not publish it. It is not derived, not
carried over from a previous reading, and not substituted with the prevailing wind
direction. Gap-filling is the frozen pipeline's job — its imputer was fitted on the
Stage 2 training split and is the only thing entitled to do it.

At the time of writing this affects 3 of 44 stations. `MaxTemp`/`MinTemp` are absent
at 1, and `WindGustSpeed` at 2.

## Daily assembly, and what a single reading cannot do

weatherAUS rows are **daily**, carrying readings taken at 09:00 and 15:00 local. This
feed publishes **one current reading per station**. A single observation therefore
cannot fill the whole schema: `to_weatherAUS_partial()` fills only the columns a
point-in-time reading legitimately can, and the 9am/3pm columns are assembled from
stored readings taken at those hours.

This is why the collector stores every reading rather than only the newest, and why
the product cannot make a full-schema prediction until it has been running for a day.

## Data separation

Live observations live in `data/live/` and never mix with the historical training
data. Nothing in this process writes to the training set, the notebook, or the frozen
model artefacts.

## Storage

`data/live/observations.db` — SQLite, one row per station per observation time.
`data/live/health.json` — per-station outcome, staleness, rejected and absent fields.
`data/live/latest.json` — newest reading per station, for the frontend.

## Running it

```bash
python collector/collect.py
```

Environment: `RAINSIGNAL_DATA_DIR`, `RAINSIGNAL_DB`, `RAINSIGNAL_HEALTH`,
`RAINSIGNAL_LATEST`, `RAINSIGNAL_STALE_MINUTES` (default 180).

Exit code is non-zero only when no station reported at all, so a partial BoM outage
degrades the product rather than breaking the schedule.

## Tests

```bash
python -m pytest tests/ -q
```

28 tests covering station-map integrity, range and compass validation, the
no-fabrication rule, the 1 mm rain threshold, XML parsing and storage idempotency.
