"""Source-agnostic data model shared by all sources and sinks."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Metric:
    """How a measurement key is presented in Home Assistant."""
    name: str
    device_class: str | None
    unit: str | None
    state_class: str | None = "measurement"
    entity_category: str | None = None  # None | "diagnostic"
    precision: int | None = None


# Catalogue of known measurement keys. Sources must only emit keys from here;
# add new ones as new sensor types appear.
METRICS: dict[str, Metric] = {
    "temperature": Metric("Temperature", "temperature", "°C", precision=1),
    "humidity": Metric("Humidity", "humidity", "%", precision=0),
    "pressure": Metric("Pressure", "atmospheric_pressure", "hPa", precision=1),
    "illuminance": Metric("Illuminance", "illuminance", "lx", precision=0),
    "co2": Metric("CO2", "carbon_dioxide", "ppm", precision=0),
    "wind_speed": Metric("Wind speed", "wind_speed", "km/h", precision=1),
    "rain": Metric("Rain", "precipitation", "mm", "total_increasing", precision=1),
    "battery": Metric("Battery", "battery", "%", entity_category="diagnostic", precision=0),
    "voltage": Metric("Battery voltage", "voltage", "V", entity_category="diagnostic", precision=3),
    "rssi": Metric("Signal strength", "signal_strength", "dBm", entity_category="diagnostic", precision=0),
}


@dataclass
class Reading:
    """One decoded sample from one physical device."""
    source: str                     # source type, e.g. "ble", "rtl433"
    device_id: str                  # stable unique id, [a-z0-9_], e.g. "atc_a4c138123456"
    values: dict[str, float | int]  # keys from METRICS
    model: str = ""
    manufacturer: str = ""
    default_name: str = ""
    aliases: tuple[str, ...] = ()   # other user-facing ids (e.g. MAC) usable in config [names]
    connections: tuple[tuple[str, str], ...] = ()  # HA device connections, e.g. (("bluetooth", mac),)
    counter: int | None = None      # frame counter for de-duplication, if the device has one

    def __post_init__(self):
        unknown = set(self.values) - METRICS.keys()
        if unknown:
            raise ValueError(f"unknown metric keys {unknown} from {self.device_id}")
