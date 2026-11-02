import struct

import pytest

from sensor_bridge.core import Router
from sensor_bridge.model import Reading
from sensor_bridge.sources.decoders.atc import UUID_181A, decode, decode_181a
from sensor_bridge.sources.rtl433 import parse_event

MAC = bytes.fromhex("A4C138123456")


def test_atc1441():
    r = decode_181a(MAC + struct.pack(">hBBHB", 234, 45, 87, 2950, 7))
    assert r.device_id == "atc_a4c138123456"
    assert r.aliases == ("A4:C1:38:12:34:56",)
    assert r.values == {"temperature": 23.4, "humidity": 45.0, "battery": 87, "voltage": 2.95}
    assert r.counter == 7
    assert "ATC1441" in r.model


def test_pvvx_negative_temperature():
    r = decode_181a(MAC[::-1] + struct.pack("<hHHBBB", -525, 6137, 3012, 99, 200, 0))
    assert r.device_id == "atc_a4c138123456"
    assert r.values["temperature"] == -5.25
    assert r.values["humidity"] == 61.37
    assert r.values["voltage"] == 3.012
    assert "pvvx" in r.model


def test_unknown_length_ignored():
    assert decode_181a(b"\x00" * 10) is None
    assert decode("x", {}, {}) is None
    assert decode("x", {UUID_181A: b"\x01\x02"}, {}) is None


def test_reading_rejects_unknown_metric():
    with pytest.raises(ValueError):
        Reading(source="t", device_id="d", values={"bogus": 1})


def test_rtl433_mapping():
    r = parse_event({"model": "Acurite-Tower", "id": 12345, "channel": "A",
                     "temperature_F": 68.0, "humidity": 40, "rssi": -7.1})
    assert r.device_id == "rtl433_acurite_tower_12345_cha"
    assert r.aliases == ("Acurite-Tower/12345/A",)
    assert r.values == {"temperature": 20.0, "humidity": 40.0, "rssi": -7.1}
    assert parse_event({"model": "X", "id": 1, "rssi": -3}) is None  # no real measurement
    assert parse_event({"time": "..."}) is None


def test_router_dedup_and_throttle():
    rt = Router({"devices": {"min_interval": 30}})
    mk = lambda cnt: Reading(source="ble", device_id="d", values={"temperature": 1.0}, counter=cnt)
    assert rt.accept(mk(1), now=0)
    assert not rt.accept(mk(1), now=100)  # same counter
    assert not rt.accept(mk(2), now=10)   # throttled
    assert rt.accept(mk(3), now=100)


def test_router_only_named_matches_mac_case_insensitive():
    rt = Router({"devices": {"names": {"a4:c1:38:12:34:56": "Salon"}}})
    rt.only_named["ble"] = True
    r = decode_181a(MAC + struct.pack(">hBBHB", 1, 1, 1, 1, 1))
    assert rt.accept(r, now=0)
    other = decode_181a(bytes(6) + struct.pack(">hBBHB", 1, 1, 1, 1, 1))
    assert not rt.accept(other, now=0)


def test_rtl433_wind_m_s_converted():
    r = parse_event({"model": "Nexus-TH", "id": 7, "temperature_C": 5.0, "wind_avg_m_s": 2.5})
    assert r.values["wind_speed"] == 9.0
