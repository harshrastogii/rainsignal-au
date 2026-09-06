# Daily assembler

Turns the stored point-in-time BoM readings into the daily `weatherAUS` row the frozen
models expect. `collector/assemble.py`.

## The problem it solves

The models were trained on **daily** rows carrying values recorded at 09:00 and 15:00
station-local time. BoM's feed publishes **one current reading per station** and
cannot be backfilled. The assembler bridges the two — and every rule below exists to
stop that bridge from quietly inventing a row.

## What it refuses to do

Interpolate. Carry a value forward from another day. Substitute a nearby station. Use
a reading outside ±45 minutes of 09:00 or 15:00. Use an aggregate whose declared
window does not match the day being assembled. Treat a still-accumulating aggregate as
final.

Each of those would produce a row that *looks* complete. The frozen preprocessing
cannot tell the difference, so the assembler must.

Missing stays missing. The Stage 2 imputer, fitted on the training split, is the only
thing permitted to fill a gap.

## Time handling

All dates and times are **station-local**, via `zoneinfo` — the 44 stations span eight
timezones, four of which observe daylight saving.

Readings timestamped after "now" are discarded and counted. BoM publishes observations
rather than forecasts, so this should never fire; it is asserted because a clock skew
or a mis-parsed offset is exactly the fault that would slip a future value into an
observed series unnoticed.

`now` is injected, not read from the clock, so assembling the same database for the
same date always gives the same answer. That is not theoretical — the first version
called `datetime.now()` inside the window-closure check and the tests caught it.

## Dating the daily aggregates

BoM's aggregate windows are **not** weatherAUS's, so they are matched on the window
attributes the feed publishes rather than assumed:

| Feature | Rule | Exact? |
|---|---|---|
| `Rainfall` | `rainfall_24hr` whose window **ends 09:00 on D** | yes |
| `MinTemp` | overnight minimum whose window **ends 09:00 on D** | close |
| `MaxTemp` | daytime maximum whose window **falls on D and has closed** | close |

`Rainfall` is exact: the Bureau's Daily Weather Observations define it as
precipitation in the 24 hours *to* 9am, which is precisely that window.

The temperature rules are approximations, and the row records the fact in `notes`.
BoM's live feed uses a 06:00–21:00 daytime maximum and an 18:00–09:00 overnight
minimum; DWO uses 24 hours from 9am and 24 hours to 9am. They agree in practice
because a day's extremes almost always fall inside both, but they are not identical.

The dating matters more than the width. **An overnight minimum ending 09:00 on day
D+1 is `MinTemp(D+1)`, not `MinTemp(D)`.** Assuming otherwise shifts a whole feature
by a day, and nothing downstream would notice. A test pins this behaviour.

## Collection schedule

The models need readings *at* 09:00 and 15:00 local, so the collector has to be there
at those moments. The original 3-hourly cron never was — Sydney's closest run was
10:20 local, 80 minutes past 9am.

The schedule now fires at the UTC times that hit 09:00 and 15:00 across all eight
timezones in both standard and daylight-saving time, plus a late-local sweep so the
daytime maximum is read after its window closes. Verified: **every timezone is 0
minutes from both targets.**

## Output

Exactly the 22 columns in `models/metadata.json`, asserted on every row — the
assembler raises rather than emitting a row the frozen pipeline would misread.

Each row also carries `provenance` (which reading supplied each slot, and how many
minutes off target it was), `missing`, and `notes`.

## Checking readiness

```bash
python collector/report_readiness.py [db] [YYYY-MM-DD]
```

Reports complete stations, missing features, and per-station coverage.

## Tests

`tests/test_assembler.py` — 14 tests covering the happy path, tolerance boundaries,
aggregate dating in both directions, unclosed windows, future timestamps, duplicates,
schema conformance, and the no-fabrication rules.
