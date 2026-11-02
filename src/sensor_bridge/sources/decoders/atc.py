"""LYWSD03MMC (and similar) with ATC1441 / pvvx custom firmware.

Advertising service data, UUID 0x181A:
  * ATC1441 - 13 B, big endian:    MAC(6) T(i16, 0.1 C) H(u8 %) Batt(u8 %) mV(u16) cnt(u8)
  * pvvx    - 15 B, little endian: MAC(6, reversed) T(i16, 0.01 C) H(u16, 0.01 %) mV(u16) Batt(u8 %) cnt(u8) flags(u8)
"""
from __future__ import annotations

import struct

from ...model import Reading

UUID_181A = "0000181a-0000-1000-8000-00805f9b34fb"


def _mac(b: bytes) -> str:
    return ":".join(f"{x:02X}" for x in b)


def decode_181a(payload: bytes) -> Reading | None:
    if len(payload) == 13:
        mac = _mac(payload[0:6])
        t, h, b, mv, cnt = struct.unpack(">hBBHB", payload[6:13])
        temp, hum, fmt = t / 10.0, float(h), "ATC1441"
    elif len(payload) == 15:
        mac = _mac(payload[0:6][::-1])
        t, h, mv, b, cnt, _flags = struct.unpack("<hHHBBB", payload[6:15])
        temp, hum, fmt = round(t / 100.0, 2), round(h / 100.0, 2), "pvvx"
    else:
        return None

    return Reading(
        source="ble",
        device_id="atc_" + mac.replace(":", "").lower(),
        values={"temperature": temp, "humidity": hum, "battery": b, "voltage": mv / 1000.0},
        model=f"LYWSD03MMC ({fmt})",
        manufacturer="Xiaomi",
        default_name=f"ATC {mac[-5:]}",
        aliases=(mac,),
        connections=(("bluetooth", mac),),
        counter=cnt,
    )


def decode(address: str, service_data: dict[str, bytes], manufacturer_data: dict[int, bytes]) -> Reading | None:
    payload = service_data.get(UUID_181A)
    return decode_181a(bytes(payload)) if payload else None
