import json
import logging
import struct
import time
from types import SimpleNamespace

from sensor_bridge.sinks.mqtt_ha import MqttHaSink
from sensor_bridge.sources.decoders.atc import decode_181a


def reading(rssi=-70, cnt=7):
    r = decode_181a(bytes.fromhex("A4C138123456") + struct.pack(">hBBHB", 234, 45, 87, 2950, cnt))
    r.values["rssi"] = rssi
    return r


class FakeClient:
    def __init__(self):
        self.published = []

    def is_connected(self):
        return True

    def publish(self, topic, payload=None, **kw):
        self.published.append((topic, payload))

    def states(self):
        return [json.loads(p) for t, p in self.published if t.endswith("/state")]


def sink(instance="pc", names=None, **cfg):
    s = MqttHaSink({"instance": instance, **cfg}, names or {})
    s.client = FakeClient()
    return s


def test_discovery_is_instance_independent():
    a, b = sink("pc", {"A4:C1:38:12:34:56": "Salon"}), sink("rpi", {"A4:C1:38:12:34:56": "Salon"})
    for key in ("temperature", "voltage", "receiver"):
        assert a.discovery_config(reading(), key) == b.discovery_config(reading(), key)
    topic, conf = a.discovery_config(reading(), "voltage")
    assert topic == "homeassistant/sensor/atc_a4c138123456/voltage/config"
    assert conf["device"]["name"] == "Salon"
    assert conf["entity_category"] == "diagnostic"
    assert "availability_topic" not in conf


def test_bridge_has_own_lwt_and_discovery():
    s = sink("g2labs-rpi")
    assert s.avail == "sensor-bridge/bridge/g2labs_rpi/status"
    topic, conf = s.bridge_discovery_config()
    assert topic == "homeassistant/binary_sensor/sensor_bridge_g2labs_rpi/connectivity/config"
    assert conf["state_topic"] == s.avail


def test_state_carries_receiver_and_timestamp():
    s = sink("pc")
    s.publish(reading())
    st = s.client.states()[-1]
    assert st["receiver"] == "pc" and st["temperature"] == 23.4 and abs(st["ts"] - time.time()) < 5


def on_state(s, state):
    s._on_message(None, None, SimpleNamespace(topic="sensor-bridge/atc_a4c138123456/state",
                                              payload=json.dumps(state).encode()))


def test_defers_to_peer_with_better_signal_then_takes_over_when_it_goes_silent():
    s = sink("pc")
    on_state(s, {"temperature": 23.4, "receiver": "rpi", "rssi": -60, "ts": time.time()})
    s.publish(reading(rssi=-80))
    assert s.client.states() == []
    on_state(s, {"temperature": 23.4, "receiver": "rpi", "rssi": -60, "ts": time.time() - 301})
    s.publish(reading(rssi=-80))
    assert s.client.states()[-1]["receiver"] == "pc"


def test_takes_over_on_much_better_signal():
    s = sink("pc")
    on_state(s, {"receiver": "rpi", "rssi": -85, "ts": time.time()})
    s.publish(reading(rssi=-65))
    assert s.client.states()[-1]["receiver"] == "pc"


def test_publish_while_disconnected_warns_once(caplog):
    s = sink()
    s.client.is_connected = lambda: False
    with caplog.at_level(logging.WARNING):
        s.publish(reading())
        s.publish(reading())
    assert s._dropped == 2
    assert sum("not connected" in m for m in caplog.messages) == 1
