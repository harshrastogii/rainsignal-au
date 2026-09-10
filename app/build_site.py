#!/usr/bin/env python3
"""Assemble the deployable site: the app plus the data it reads.

The app fetches everything from ./data/, so this copies the collector's and model's
outputs into one directory that a static host can serve. Run before previewing
locally, and in the Pages workflow before deploying.
"""
from __future__ import annotations
import json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP, OUT = ROOT / "app", ROOT / (sys.argv[1] if len(sys.argv) > 1 else "_site")

SOURCES = {
    "data/predictions.json":        ROOT / "data/live/predictions.json",
    "data/latest.json":             ROOT / "data/live/latest.json",
    "data/health.json":             ROOT / "data/live/health.json",
    "data/station_reliability.json": ROOT / "models/station_reliability.json",
    "data/stations.json":           ROOT / "rainsignal/stations.json",
    "data/model.json":              ROOT / "models/metadata.json",
}

if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "data").mkdir(parents=True)

for name in ("index.html", "styles.css", "app.js", "logo.svg", "favicon.svg", "_headers"):
    shutil.copy2(APP / name, OUT / name)

missing = []
for dest, src in SOURCES.items():
    if src.exists():
        shutil.copy2(src, OUT / dest)
    else:
        missing.append(str(src.relative_to(ROOT)))

if missing:
    print("MISSING (the app degrades rather than breaking):")
    for m in missing:
        print("  " + m)

total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
print(f"built {OUT.relative_to(ROOT)}  ({total/1024:.0f} KB)")
for f in sorted(OUT.rglob("*")):
    if f.is_file():
        print(f"  {f.relative_to(OUT)!s:34s} {f.stat().st_size/1024:7.1f} KB")
