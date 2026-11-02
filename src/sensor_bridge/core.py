"""Glue: runs sources, filters/throttles readings, fans out to sinks."""
from __future__ import annotations

import asyncio
import logging
import signal
import time

from . import sinks as sinks_mod
from . import sources as sources_mod
from .model import Reading

log = logging.getLogger(__name__)


class Router:
    def __init__(self, cfg: dict):
        d = cfg.get("devices", {})
        # names may be keyed by device_id or alias (e.g. MAC); alias keys are matched case-insensitively for MACs
        self.names: dict[str, str] = {}
        for k, v in d.get("names", {}).items():
            self.names[k] = v
            self.names[k.upper()] = v
        self.min_interval = float(d.get("min_interval", 30))
        self.only_named: dict[str, bool] = {}
        self.last: dict[str, tuple[float, int | None]] = {}
        self.sinks: list[sinks_mod.Sink] = []

    def is_named(self, r: Reading) -> bool:
        return any(k in self.names or k.upper() in self.names for k in (r.device_id, *r.aliases))

    def accept(self, r: Reading, now: float | None = None) -> bool:
        if self.only_named.get(r.source, False) and not self.is_named(r):
            return False
        now = time.monotonic() if now is None else now
        prev = self.last.get(r.device_id)
        if prev:
            if r.counter is not None and prev[1] == r.counter:
                return False  # same frame repeated
            if now - prev[0] < self.min_interval:
                return False
        self.last[r.device_id] = (now, r.counter)
        return True

    def emit(self, r: Reading) -> None:
        if not self.accept(r):
            return
        log.debug("%s %s", r.device_id, r.values)
        for s in self.sinks:
            try:
                s.publish(r)
            except Exception:
                log.exception("sink %s failed", s.type)


async def run(cfg: dict) -> None:
    router = Router(cfg)
    raw_names = cfg.get("devices", {}).get("names", {})
    router.sinks = [sinks_mod.create(c, router.names) for c in cfg.get("sinks", [])]
    srcs = []
    for c in cfg.get("sources", []):
        if not c.get("enabled", True):
            continue
        s = sources_mod.create(c, raw_names)
        router.only_named[s.type] = router.only_named.get(s.type, False) or c.get("only_named", False)
        srcs.append(s)
    if not srcs or not router.sinks:
        raise SystemExit("config needs at least one enabled [[sources]] and one [[sinks]]")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    for s in router.sinks:
        s.start()
    try:
        tasks = [asyncio.create_task(s.run(router.emit, stop), name=s.name) for s in srcs]
        await stop.wait()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for s in router.sinks:
            s.stop()
        log.info("stopped")
