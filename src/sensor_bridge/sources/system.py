"""Metrics of the machine the bridge runs on (CPU temperature/usage, memory, disk) via psutil.

Each instance publishes its own host as a separate HA device `host_<hostname>`.
In Docker, CPU and memory figures are the host's (psutil reads /proc), disk usage is for the path given.
"""
from __future__ import annotations

import asyncio
import logging
import re
import socket

from ..model import Reading
from .base import Emit, Source

log = logging.getLogger(__name__)

# psutil.sensors_temperatures() keys, most specific first: Intel, AMD, Raspberry Pi, generic ACPI
TEMP_SENSORS = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "soc_thermal", "acpitz")
TEMP_LABELS = ("Package id 0", "Tctl", "Tdie")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "host"


def pick_cpu_temp(temps: dict, preferred: str | None = None) -> float | None:
    """Choose the CPU temperature from psutil.sensors_temperatures() output."""
    order = ([preferred] if preferred else []) + [k for k in TEMP_SENSORS if k != preferred]
    for key in order:
        entries = temps.get(key)
        if not entries:
            continue
        for e in entries:  # prefer the package / control temperature over per-core values
            if e.label in TEMP_LABELS:
                return round(float(e.current), 1)
        return round(max(float(e.current) for e in entries), 1)
    return None


def collect(psutil, disk_path: str, temp_sensor: str | None) -> dict[str, float]:
    values: dict[str, float] = {
        "cpu_usage": round(psutil.cpu_percent(interval=None), 1),
    }
    mem = psutil.virtual_memory()
    values["memory_usage"] = round(mem.percent, 1)
    values["memory_used"] = round((mem.total - mem.available) / 2**20)
    try:
        values["disk_usage"] = round(psutil.disk_usage(disk_path).percent, 1)
    except OSError as e:
        log.debug("disk_usage(%s) failed: %s", disk_path, e)
    if hasattr(psutil, "sensors_temperatures"):  # not available on Windows/macOS
        try:
            t = pick_cpu_temp(psutil.sensors_temperatures(), temp_sensor)
        except Exception as e:  # sensor drivers can be flaky
            log.debug("sensors_temperatures failed: %s", e)
            t = None
        if t is not None:
            values["cpu_temperature"] = t
    return values


class SystemSource(Source):
    type = "system"

    def __init__(self, cfg: dict, names: dict[str, str] | None = None, psutil_module=None):
        super().__init__(cfg, names)
        if psutil_module is None:
            import psutil as psutil_module  # optional dependency, extra [system]
        self.psutil = psutil_module
        self.hostname = cfg.get("hostname") or socket.gethostname()
        self.interval = float(cfg.get("interval", 60))
        self.disk_path = cfg.get("disk_path", "/")
        self.temp_sensor = cfg.get("temperature_sensor")

    def reading(self) -> Reading:
        return Reading(
            source="system",
            device_id=f"host_{_slug(self.hostname)}",
            values=collect(self.psutil, self.disk_path, self.temp_sensor),
            model="Host",
            manufacturer="g2labs-sensor-bridge",
            default_name=self.hostname,
            aliases=(self.hostname,),
        )

    async def run(self, emit: Emit, stop: asyncio.Event) -> None:
        self.psutil.cpu_percent(interval=None)  # prime: first call always returns 0.0
        log.info("[%s] reporting host '%s' every %.0f s", self.name, self.hostname, self.interval)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval)
                break
            except asyncio.TimeoutError:
                pass
            try:
                emit(await asyncio.to_thread(self.reading))
            except Exception:
                log.exception("[%s] collecting host metrics failed", self.name)
