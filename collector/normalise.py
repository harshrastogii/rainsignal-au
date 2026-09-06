#!/usr/bin/env python3
"""Validate BoM observations and normalise them into the frozen weatherAUS schema.

Two rules govern everything here.

Nothing is invented. BoM publishes no gust *direction* for some stations and the
alternatives publish none at all, so `WindGustDir` is left as None when it is
absent. The frozen pipeline's imputer -- fitted on the training split in Stage 2 --
is the only thing allowed to fill a gap, and it does so downstream, not here.

Nothing is silently coerced. A reading outside a physically plausible range is
dropped and recorded, not clamped into range, because a clamped value looks
exactly like a real one to the model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from rainsignal.schema import RAIN_THRESHOLD_MM, degrees_to_compass  # noqa: F401
from rainsignal.stations import BY_BOM_ID

# Physically plausible ranges for Australian surface observations. A value outside
# these is a sensor fault or a parse error, never a real reading.
RANGES = {
    "air_temperature":         (-15.0, 55.0),
    "maximum_air_temperature": (-15.0, 55.0),
    "minimum_air_temperature": (-15.0, 55.0),
    "rel-humidity":            (0.0, 100.0),
    "msl_pres":                (900.0, 1100.0),
    "pres":                    (900.0, 1100.0),
    "wind_spd_kmh":            (0.0, 250.0),
    "maximum_gust_kmh":        (0.0, 350.0),
    "rainfall":                (0.0, 1000.0),
    "rainfall_24hr":           (0.0, 1000.0),
}

# BoM publishes wind direction as a compass label already; these are the only
# values weatherAUS ever contained.
VALID_COMPASS = {
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
}


@dataclass
class Reading:
    """One validated observation, ready to store."""
    location: str
    bom_id: str
    observed_local: str
    observed_utc: str
    collected_utc: str
    values: dict = field(default_factory=dict)
    rejected: dict = field(default_factory=dict)

    @property
    def n_present(self) -> int:
        return sum(v is not None for v in self.values.values())


def _num(raw, element):
    """Parse a numeric element, returning (value, reason_rejected)."""
    if raw in (None, "", "-"):
        return None, None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, f"unparseable {raw!r}"
    lo, hi = RANGES.get(element, (float("-inf"), float("inf")))
    if not (lo <= value <= hi):
        return None, f"out of range {value} not in [{lo}, {hi}]"
    return value, None


def _compass(raw):
    if raw in (None, "", "-"):
        return None, None
    label = raw.strip().upper()
    if label in VALID_COMPASS:
        return label, None
    return None, f"not a 16-point compass label: {raw!r}"


def validate(observation) -> Reading | None:
    """Turn a raw Observation into a validated Reading, or None if unmapped.

    A station BoM publishes that we did not curate is skipped deliberately: the
    model's `Location` is a fixed one-hot over 49 towns and has no slot for it.
    """
    location = BY_BOM_ID.get(observation.bom_id)
    if location is None:
        return None

    values, rejected = {}, {}
    for element in ("air_temperature", "maximum_air_temperature", "minimum_air_temperature",
                    "rel-humidity", "msl_pres", "pres", "wind_spd_kmh",
                    "maximum_gust_kmh", "rainfall", "rainfall_24hr"):
        value, reason = _num(observation.elements.get(element), element)
        values[element] = value
        if reason:
            rejected[element] = reason

    for element in ("wind_dir", "maximum_gust_dir"):
        value, reason = _compass(observation.elements.get(element))
        values[element] = value
        if reason:
            rejected[element] = reason

    return Reading(
        location=location,
        bom_id=observation.bom_id,
        observed_local=observation.time_local or "",
        observed_utc=observation.time_utc or "",
        collected_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        values=values,
        rejected=rejected,
    )


def to_weatherAUS_partial(reading: Reading) -> dict:
    """Map a single reading onto the weatherAUS column names it can fill.

    A single observation cannot populate the whole schema. weatherAUS rows are
    daily and carry readings taken at 09:00 and 15:00 local, whereas this feed
    publishes one current reading per station. The 9am/3pm columns are therefore
    filled by the daily assembler from stored readings taken at those hours; this
    function fills only what a single point-in-time observation legitimately can.
    """
    v = reading.values
    rainfall = v.get("rainfall_24hr") if v.get("rainfall_24hr") is not None else v.get("rainfall")
    return {
        "Location": reading.location,
        "MinTemp": v.get("minimum_air_temperature"),
        "MaxTemp": v.get("maximum_air_temperature"),
        "Rainfall": rainfall,
        "WindGustSpeed": v.get("maximum_gust_kmh"),
        # BoM omits gust direction at some stations and no comparable public source
        # publishes it. Left as None on purpose -- see the module docstring.
        "WindGustDir": v.get("maximum_gust_dir"),
        "RainToday": (None if rainfall is None
                      else ("Yes" if rainfall > RAIN_THRESHOLD_MM else "No")),
        # Instantaneous values, held for the assembler to place into 9am/3pm slots.
        "_obs_temp": v.get("air_temperature"),
        "_obs_humidity": v.get("rel-humidity"),
        "_obs_pressure": v.get("msl_pres") if v.get("msl_pres") is not None else v.get("pres"),
        "_obs_wind_dir": v.get("wind_dir"),
        "_obs_wind_spd": v.get("wind_spd_kmh"),
    }
