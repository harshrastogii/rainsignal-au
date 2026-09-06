#!/usr/bin/env python3
"""Assemble stored point-in-time BoM readings into daily weatherAUS model inputs.

The models were trained on daily rows carrying values recorded at 09:00 and 15:00
station-local time, plus daily aggregates. BoM's live feed publishes one current
reading per station. This module bridges the two, and every rule it applies exists
to stop that bridge from quietly fabricating a row.

What it will not do
-------------------
Interpolate. Carry a value forward from another day. Substitute a nearby station.
Use a reading outside the tolerance window around 09:00 or 15:00. Use an aggregate
whose declared accumulation window does not match the day being assembled. Treat a
still-accumulating aggregate as final. Any of those would produce a row that looks
complete and is not, and the frozen preprocessing has no way to detect it.

Missing stays missing. The Stage 2 imputer, fitted on the training split, is the only
thing permitted to fill a gap.

Dating the aggregates
---------------------
BoM's own daily windows are not weatherAUS's, so they are matched on the window
attributes the feed publishes rather than assumed:

  Rainfall(D)  = rainfall_24hr whose window ENDS at 09:00 on D. This is exact --
                 the Bureau's Daily Weather Observations define rainfall as the
                 precipitation in the 24 hours to 9am.
  MinTemp(D)   = overnight minimum whose window ENDS at 09:00 on D. Note this is
                 the night of D-1 into D; the minimum ending at 09:00 on D+1 is
                 MinTemp(D+1), and using it for D would shift the feature a day.
  MaxTemp(D)   = daytime maximum whose window falls on D and has closed.

The max and min windows are approximations of the DWO definitions, which run 9am to
9am. They are close because a day's extremes almost always fall inside the Bureau's
06:00-21:00 and 18:00-09:00 windows, but they are not identical, and `notes` records
the difference on every row rather than hiding it.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from rainsignal.schema import MODEL_COLUMNS, RAIN_THRESHOLD_MM
from rainsignal.stations import COLLECTABLE

# A 9am or 3pm value may be taken from a reading this many minutes either side of
# the target. Beyond it the value is treated as missing rather than stretched: BoM
# reports every half hour, so a genuine gap this wide means the station went quiet.
TOLERANCE_MINUTES = 45

TARGETS = {"9am": time(9, 0), "3pm": time(15, 0)}


@dataclass
class DailyRow:
    """One assembled day for one station."""
    location: str
    obs_date: str                      # station-local calendar date, ISO
    values: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    missing: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def n_missing(self) -> int:
        return len(self.missing)


def _parse_local(value):
    """Parse a BoM local-time string into an aware datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load(db_path: Path, location: str) -> list[dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM observations WHERE location = ? ORDER BY observed_utc",
        (location,)).fetchall()
    con.close()

    # Deduplicate on observed time. The storage key already prevents duplicates, but
    # the assembler must not depend on that: a re-imported or merged database could
    # carry two rows for one instant, and silently averaging them would be worse
    # than picking one deterministically.
    seen, out = set(), []
    for r in rows:
        d = dict(r)
        key = d.get("observed_utc")
        if key in seen:
            continue
        seen.add(key)
        d["_local"] = _parse_local(d.get("observed_local"))
        d["_windows"] = json.loads(d["windows_json"]) if d.get("windows_json") else {}
        out.append(d)
    return out


def _nearest(readings, target_dt, tolerance_min):
    """The reading closest to target_dt within tolerance, else (None, None)."""
    best, best_gap = None, None
    for r in readings:
        local = r.get("_local")
        if local is None:
            continue
        gap = abs((local - target_dt).total_seconds()) / 60.0
        if gap <= tolerance_min and (best_gap is None or gap < best_gap):
            best, best_gap = r, gap
    return best, best_gap


def _window_end_on(reading, element, target_date, tz):
    """True when this element's accumulation window ends at 09:00 on target_date."""
    w = reading["_windows"].get(element)
    if not w or not w.get("end"):
        return False
    end = _parse_local(w["end"])
    if end is None:
        return False
    want = datetime.combine(target_date, time(9, 0), tzinfo=tz)
    return abs((end - want).total_seconds()) <= 3600      # allow an hour of slack


def _window_within_day(reading, element, target_date, now_utc):
    """True when this element's window lies inside target_date and has closed.

    `now_utc` is passed in rather than read from the clock so that assembling the
    same database for the same date always gives the same answer.
    """
    w = reading["_windows"].get(element)
    if not w or not (w.get("start") and w.get("end")):
        return False
    start, end = _parse_local(w["start"]), _parse_local(w["end"])
    if start is None or end is None:
        return False
    if start.date() != target_date or end.date() != target_date:
        return False
    return end.astimezone(timezone.utc) <= now_utc                   # window closed


def assemble_day(db_path: Path, location: str, obs_date: date,
                 tolerance_min: int = TOLERANCE_MINUTES,
                 now_utc: datetime | None = None) -> DailyRow:
    """Build the weatherAUS row for one station on one station-local date."""
    meta = COLLECTABLE[location]
    tz = ZoneInfo(meta["tz"])
    now_utc = now_utc or datetime.now(timezone.utc)
    row = DailyRow(location=location, obs_date=obs_date.isoformat())

    readings = _load(db_path, location)
    # Only observations that have actually happened. BoM publishes observations, not
    # forecasts, but this is asserted rather than assumed -- a clock skew or a
    # mis-parsed timezone is exactly the kind of fault that would slip a future
    # timestamp into an "observed" series.
    usable, future = [], 0
    for r in readings:
        local = r.get("_local")
        if local is None:
            continue
        if local.astimezone(timezone.utc) > now_utc:
            future += 1
            continue
        usable.append(r)
    if future:
        row.notes.append(f"discarded {future} reading(s) timestamped in the future")

    row.values["Location"] = location

    # ---- 9am / 3pm point-in-time values ----
    slots = {
        "9am": ("Temp9am", "Humidity9am", "Pressure9am", "WindDir9am", "WindSpeed9am"),
        "3pm": ("Temp3pm", "Humidity3pm", "Pressure3pm", "WindDir3pm", "WindSpeed3pm"),
    }
    columns = ("air_temp", "humidity", "pressure_msl", "wind_dir", "wind_spd_kmh")
    for label, target_time in TARGETS.items():
        target_dt = datetime.combine(obs_date, target_time, tzinfo=tz)
        hit, gap = _nearest(usable, target_dt, tolerance_min)
        names = slots[label]
        if hit is None:
            for n in names:
                row.values[n] = None
                row.missing.append(n)
            row.notes.append(f"no reading within {tolerance_min} min of {label}")
            continue
        row.provenance[label] = {"observed_local": hit["observed_local"],
                                 "offset_min": round(gap, 1)}
        for name, col in zip(names, columns):
            v = hit[col]
            row.values[name] = v
            if v is None:
                row.missing.append(name)

    # ---- daily aggregates, matched on BoM's declared windows ----
    rain = next((r for r in usable
                 if _window_end_on(r, "rainfall_24hr", obs_date, tz)
                 and r["rainfall_24hr"] is not None), None)
    if rain is not None:
        row.values["Rainfall"] = rain["rainfall_24hr"]
        row.values["RainToday"] = ("Yes" if rain["rainfall_24hr"] > RAIN_THRESHOLD_MM
                                   else "No")
        row.provenance["Rainfall"] = {"window_end": rain["_windows"]["rainfall_24hr"]["end"]}
    else:
        row.values["Rainfall"] = None
        row.values["RainToday"] = None
        row.missing += ["Rainfall", "RainToday"]
        row.notes.append("no rainfall_24hr window ending 09:00 on this date")

    mn = next((r for r in usable
               if _window_end_on(r, "minimum_air_temperature", obs_date, tz)
               and r["min_temp"] is not None), None)
    row.values["MinTemp"] = mn["min_temp"] if mn else None
    if mn is None:
        row.missing.append("MinTemp")
        row.notes.append("no overnight minimum window ending 09:00 on this date")
    else:
        row.provenance["MinTemp"] = {"window": mn["_windows"]["minimum_air_temperature"]}

    mx = next((r for r in reversed(usable)
               if _window_within_day(r, "maximum_air_temperature", obs_date, now_utc)
               and r["max_temp"] is not None), None)
    row.values["MaxTemp"] = mx["max_temp"] if mx else None
    if mx is None:
        row.missing.append("MaxTemp")
        row.notes.append("no closed daytime maximum window on this date")
    else:
        row.provenance["MaxTemp"] = {"window": mx["_windows"]["maximum_air_temperature"]}
        row.notes.append("MaxTemp/MinTemp use BoM's 06:00-21:00 and 18:00-09:00 "
                         "windows; weatherAUS uses 9am-to-9am")

    gust = next((r for r in reversed(usable)
                 if r["gust_kmh"] is not None
                 and r["_local"] and r["_local"].date() == obs_date), None)
    row.values["WindGustSpeed"] = gust["gust_kmh"] if gust else None
    row.values["WindGustDir"] = gust["gust_dir"] if gust else None
    for n in ("WindGustSpeed", "WindGustDir"):
        if row.values[n] is None:
            row.missing.append(n)
    if gust is not None and gust["gust_dir"] is None:
        row.notes.append("BoM published no gust direction for this station")

    # ---- engineered features, exactly as Stage 2 defined them ----
    month = obs_date.month
    row.values["Month_sin"] = math.sin(2 * math.pi * month / 12)
    row.values["Month_cos"] = math.cos(2 * math.pi * month / 12)

    def diff(a, b):
        va, vb = row.values.get(a), row.values.get(b)
        return None if va is None or vb is None else va - vb

    row.values["TempRange"] = diff("MaxTemp", "MinTemp")
    row.values["PressureChange"] = diff("Pressure3pm", "Pressure9am")
    row.values["HumidityChange"] = diff("Humidity3pm", "Humidity9am")
    for n in ("TempRange", "PressureChange", "HumidityChange"):
        if row.values[n] is None:
            row.missing.append(n)

    # ---- schema conformance ----
    missing_cols = [c for c in MODEL_COLUMNS if c not in row.values]
    extra_cols = [c for c in row.values if c not in MODEL_COLUMNS]
    if missing_cols or extra_cols:
        raise AssertionError(
            f"assembled row does not match the frozen schema: "
            f"missing={missing_cols} extra={extra_cols}")

    row.missing = sorted(set(row.missing))
    return row


def assemble_all(db_path: Path, obs_date: date, **kw) -> dict[str, DailyRow]:
    return {loc: assemble_day(db_path, loc, obs_date, **kw)
            for loc in sorted(COLLECTABLE)}
