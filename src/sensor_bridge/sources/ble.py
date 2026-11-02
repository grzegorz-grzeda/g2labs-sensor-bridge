"""Passive BLE advertisement scanner (bleak)."""
from __future__ import annotations

import asyncio
import logging

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .base import Emit, Source
from .decoders import BLE_DECODERS

log = logging.getLogger(__name__)


class BleSource(Source):
    type = "ble"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        wanted = cfg.get("decoders", list(BLE_DECODERS))
        self.decoders = [BLE_DECODERS[d] for d in wanted]
        self.adapter = cfg.get("adapter")
        self.restart_every = float(cfg.get("restart_scan_every", 600))

    async def run(self, emit: Emit, stop: asyncio.Event) -> None:
        def on_adv(dev: BLEDevice, adv: AdvertisementData):
            for dec in self.decoders:
                try:
                    r = dec(dev.address, adv.service_data, adv.manufacturer_data)
                except Exception:  # never let one bad frame kill the scanner
                    log.exception("decoder failed for %s", dev.address)
                    continue
                if r is not None:
                    r.values.setdefault("rssi", adv.rssi)
                    emit(r)
                    return

        kwargs = {"bluetooth_adapter": self.adapter} if self.adapter else {}
        scanner = BleakScanner(detection_callback=on_adv, **kwargs)
        log.info("[%s] scanning (decoders: %s)", self.name, ", ".join(self.cfg.get("decoders", BLE_DECODERS)))
        while not stop.is_set():
            await scanner.start()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.restart_every or None)
            except asyncio.TimeoutError:
                log.debug("[%s] periodic scanner restart", self.name)
            finally:
                await scanner.stop()
