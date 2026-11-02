"""433/868 MHz sensors via rtl_433 (RTL-SDR dongle). EXPERIMENTAL - not yet tested on hardware.

Runs `rtl_433 -F json` as a subprocess and maps its JSON fields onto METRICS.
Sensors with a random id per battery change can be followed with learn mode, see rtl433_learn.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from ..model import Reading
from .base import Emit, Source
from .rtl433_learn import Learner

log = logging.getLogger(__name__)

# rtl_433 field -> (metric key, converter)
FIELD_MAP = {
    "temperature_C": ("temperature", lambda v: round(float(v), 2)),
    "temperature_F": ("temperature", lambda v: round((float(v) - 32) * 5 / 9, 2)),
    "humidity": ("humidity", float),
    "pressure_hPa": ("pressure", float),
    "wind_avg_km_h": ("wind_speed", float),
    "wind_avg_m_s": ("wind_speed", lambda v: round(float(v) * 3.6, 1)),
    "rain_mm": ("rain", float),
    "rssi": ("rssi", float),
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def parse_event(ev: dict, learner: Learner | None = None) -> Reading | None:
    model = ev.get("model")
    if not model or "id" not in ev:
        return None
    values: dict[str, float] = {}
    for field, (key, conv) in FIELD_MAP.items():
        if field in ev and key not in values:
            values[key] = conv(ev[field])
    if not set(values) - {"rssi"}:
        return None
    channel = str(ev["channel"]) if "channel" in ev else None
    ident = f"{ev['id']}" + (f"_ch{channel}" if channel is not None else "")
    alias = f"{model}/{ev['id']}" + (f"/{channel}" if channel is not None else "")

    slot = learner.match(model, str(ev["id"]), channel) if learner else None
    if slot is not None:
        return Reading(
            source="rtl433",
            device_id=slot.device_id,  # stable across id changes
            values=values,
            model=model,
            manufacturer=model.split("-")[0],
            default_name=f"{model} ch{channel}" if channel is not None else model,
            aliases=(slot.key, alias),
        )
    return Reading(
        source="rtl433",
        device_id=f"rtl433_{_slug(model)}_{_slug(ident)}",
        values=values,
        model=model,
        manufacturer=model.split("-")[0],
        default_name=f"{model} {ident}",
        aliases=(alias,),
    )


class Rtl433Source(Source):
    type = "rtl433"

    def __init__(self, cfg: dict, names: dict[str, str] | None = None):
        super().__init__(cfg, names)
        self.command = cfg.get("command", ["rtl_433", "-C", "si", "-F", "json", "-M", "level"])
        self.learner = Learner(
            self.names,
            relearn_after=float(cfg.get("relearn_after", 300)),
            state_file=cfg.get("state_file", "/var/lib/sensor-bridge/rtl433_bindings.json"),
        )
        for s in self.learner.slots:
            log.info("[%s] learn slot %s -> %s (bound id: %s)", self.name, s.key, s.device_id, s.bound_id or "none yet")

    async def run(self, emit: Emit, stop: asyncio.Event) -> None:
        backoff = 1
        while not stop.is_set():
            log.info("[%s] starting: %s", self.name, " ".join(self.command))
            try:
                proc = await asyncio.create_subprocess_exec(
                    *self.command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            except FileNotFoundError:
                log.error("[%s] %s not found - source disabled", self.name, self.command[0])
                return
            stop_task = asyncio.create_task(stop.wait())
            try:
                while True:
                    line_task = asyncio.create_task(proc.stdout.readline())
                    done, _ = await asyncio.wait({line_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
                    if stop_task in done:
                        line_task.cancel()
                        break
                    line = line_task.result()
                    if not line:
                        break  # process exited
                    try:
                        r = parse_event(json.loads(line), self.learner or None)
                    except (ValueError, TypeError):
                        continue
                    if r:
                        emit(r)
                        backoff = 1
            finally:
                stop_task.cancel()
                if proc.returncode is None:
                    proc.terminate()
                    await proc.wait()
            if not stop.is_set():
                log.warning("[%s] rtl_433 exited (%s), restarting in %ss", self.name, proc.returncode, backoff)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60)
