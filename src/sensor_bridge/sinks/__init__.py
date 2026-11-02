from __future__ import annotations

import importlib
from abc import ABC, abstractmethod

from ..model import Reading


class Sink(ABC):
    """A consumer of Readings. `publish` is called from the asyncio loop and must not block."""
    type: str = ""

    def __init__(self, cfg: dict, names: dict[str, str]):
        self.cfg = cfg
        self.names = names  # device_id / alias -> user-given name

    def display_name(self, r: Reading) -> str:
        for key in (r.device_id, *r.aliases):
            if key in self.names:
                return self.names[key]
        return r.default_name or r.device_id

    def start(self) -> None: ...
    def stop(self) -> None: ...

    @abstractmethod
    def publish(self, r: Reading) -> None: ...


SINKS = {
    "mqtt_ha": "sensor_bridge.sinks.mqtt_ha:MqttHaSink",
}


def create(cfg: dict, names: dict[str, str]) -> Sink:
    mod, cls = SINKS[cfg["type"]].split(":")
    return getattr(importlib.import_module(mod), cls)(cfg, names)
