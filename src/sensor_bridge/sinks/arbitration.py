"""Multi-receiver arbitration.

Several bridge instances (e.g. a PC and the Raspberry Pi) may hear the same sensor. All of them
publish to the same state topic, and every instance watches that topic. For each device the
instance that published last is its current *owner*. Another instance only publishes (takes over) when:

  * the owner went silent for `takeover_after` seconds (bridge down, sensor out of its range), or
  * it hears the sensor at least `rssi_hysteresis` dB stronger than the owner last reported.

This converges to one receiver per sensor, preferring the strongest signal, without flapping on
small RSSI changes. With a single instance it is a no-op (it always owns everything).
Pure logic, no MQTT - unit-testable.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Owner:
    receiver: str
    rssi: float | None
    ts: float  # unix time of the owner's last publish (from the payload, so it survives restarts)


def should_publish(me: str, my_rssi: float | None, owner: Owner | None, now: float,
                   takeover_after: float, rssi_hysteresis: float) -> bool:
    if owner is None or owner.receiver == me:
        return True
    if now - owner.ts >= takeover_after:
        return True
    if my_rssi is not None and owner.rssi is not None and my_rssi >= owner.rssi + rssi_hysteresis:
        return True
    return False


class OwnerTable:
    """device_id -> Owner, written from the MQTT thread, read from the asyncio loop."""

    def __init__(self):
        self._lock = threading.Lock()
        self._owners: dict[str, Owner] = {}

    def update_from_state(self, device_id: str, state: dict) -> None:
        receiver, ts = state.get("receiver"), state.get("ts")
        if not isinstance(receiver, str) or not isinstance(ts, (int, float)):
            return  # legacy payload without arbitration info
        rssi = state.get("rssi")
        with self._lock:
            self._owners[device_id] = Owner(receiver, rssi if isinstance(rssi, (int, float)) else None, float(ts))

    def get(self, device_id: str) -> Owner | None:
        with self._lock:
            return self._owners.get(device_id)
