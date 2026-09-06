"""Curated mapping from weatherAUS `Location` values to BoM observation stations.

Built 7 Sep 2026 from the BoM state observation products (IDx60920) by reading the
station identity BoM itself publishes. The mapping is keyed on `bom_id`, which is
stable; station *names* change and must never be matched fuzzily.

Fuzzy matching was tried first and produced silently wrong stations -- `Uluru`
matched "MULURULU AWS" (a NSW station) and `Nhil` matched "BROKE-N-HIL-L AIRPORT".
Both would have fed a real model a real observation from the wrong place.

Five weatherAUS locations have no station in the live products. They are listed with
`collectable = False` and are reported as unavailable rather than substituted.
"""
from __future__ import annotations
import json
from pathlib import Path

_PATH = Path(__file__).with_name("stations.json")
STATIONS: dict[str, dict] = json.loads(_PATH.read_text())

COLLECTABLE = {k: v for k, v in STATIONS.items() if v["collectable"]}
UNCOLLECTABLE = {k: v["reason"] for k, v in STATIONS.items() if not v["collectable"]}

# The state observation products that between them cover every collectable station.
PRODUCTS = sorted({v["product"] for v in COLLECTABLE.values()})

# bom_id -> weatherAUS Location, the lookup the parser actually uses.
BY_BOM_ID = {v["bom_id"]: k for k, v in COLLECTABLE.items()}

assert len(STATIONS) == 49, "weatherAUS has exactly 49 locations"
assert len(BY_BOM_ID) == len(COLLECTABLE), "bom_id must be unique per location"
