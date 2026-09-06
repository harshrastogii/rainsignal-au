#!/usr/bin/env python3
"""Fetch and parse BoM observation products from the anonymous FTP service.

FTP rather than the website is deliberate. BoM's site returns 403 to automated
requests and directs machine access to this channel; it is also the richer feed --
it carries `maximum_gust_dir`, which the alternatives we evaluated do not publish
at all, and it serves all 44 stations in 7 files instead of 44 requests.

This module only fetches and parses. It makes no decisions about validity, and it
never invents a value that BoM did not send.
"""
from __future__ import annotations

import socket
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ftplib import FTP, all_errors
from io import BytesIO

FTP_HOST = "ftp.bom.gov.au"
FTP_DIR = "/anon/gen/fwo"
TIMEOUT = 45
MAX_RETRIES = 2
RETRY_BACKOFF = 3      # seconds, multiplied by attempt number

# The observation elements we read. Anything absent stays absent.
ELEMENTS = (
    "air_temperature", "maximum_air_temperature", "minimum_air_temperature",
    "rel-humidity", "msl_pres", "pres",
    "wind_dir", "wind_spd_kmh", "maximum_gust_kmh", "maximum_gust_dir",
    "rainfall", "rainfall_24hr",
)


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


@dataclass
class Observation:
    """One station reading, exactly as BoM published it."""
    bom_id: str
    bom_name: str
    product: str
    time_local: str | None
    time_utc: str | None
    lat: float | None = None
    lon: float | None = None
    elements: dict[str, str] = field(default_factory=dict)


def fetch_product(product: str) -> bytes:
    """Download one product file over FTP, retrying transient failures."""
    last = None
    for attempt in range(MAX_RETRIES + 1):
        buf = BytesIO()
        try:
            with FTP(FTP_HOST, timeout=TIMEOUT) as ftp:
                ftp.login()                      # anonymous
                ftp.cwd(FTP_DIR)
                ftp.retrbinary(f"RETR {product}.xml", buf.write)
            data = buf.getvalue()
            if not data:
                raise ValueError(f"{product}: empty response")
            return data
        except (*all_errors, OSError, socket.timeout, ValueError) as exc:
            last = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * (attempt + 1))
    raise RuntimeError(f"{product}: FTP failed after {MAX_RETRIES + 1} attempts: {last}")


def parse_product(xml_bytes: bytes, product: str) -> list[Observation]:
    """Extract one Observation per station from a product file."""
    root = ET.fromstring(xml_bytes)
    out: list[Observation] = []
    for station in root.findall(".//station"):
        periods = station.findall(".//period")
        if not periods:
            continue
        period = periods[0]                       # the feed carries only the latest
        elements = {
            e.get("type"): (e.text or "").strip()
            for e in period.findall(".//element")
            if e.get("type") in ELEMENTS and e.text
        }
        out.append(Observation(
            bom_id=station.get("bom-id"),
            bom_name=station.get("stn-name"),
            product=product,
            time_local=period.get("time-local"),
            time_utc=period.get("time-utc"),
            lat=_maybe_float(station.get("lat")),
            lon=_maybe_float(station.get("lon")),
            elements=elements,
        ))
    return out


def _maybe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_all(products) -> tuple[dict[str, list[Observation]], dict[str, str]]:
    """Fetch every product. Returns (observations by product, errors by product).

    Products are fetched sequentially: there are only seven of them, and a single
    polite connection at a time is the right thing to point at a public service.
    """
    got, errors = {}, {}
    for product in products:
        try:
            observations = parse_product(fetch_product(product), product)
            got[product] = observations
            log(f"{product}  ok    {len(observations)} stations")
        except Exception as exc:                  # noqa: BLE001 - recorded per product
            errors[product] = str(exc)[:200]
            log(f"{product}  FAIL  {errors[product]}")
    return got, errors
