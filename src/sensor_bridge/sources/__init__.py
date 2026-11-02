"""Source registry. Imports are lazy so a missing optional dependency (e.g. bleak)
only matters when that source is actually enabled."""
from __future__ import annotations

import importlib

from .base import Source

SOURCES = {
    "ble": "sensor_bridge.sources.ble:BleSource",
    "rtl433": "sensor_bridge.sources.rtl433:Rtl433Source",
}


def create(cfg: dict, names: dict[str, str] | None = None) -> Source:
    mod, cls = SOURCES[cfg["type"]].split(":")
    return getattr(importlib.import_module(mod), cls)(cfg, names)
