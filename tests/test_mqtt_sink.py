import logging
import struct

from sensor_bridge.sinks.mqtt_ha import MqttHaSink
from sensor_bridge.sources.decoders.atc import decode_181a

R = decode_181a(bytes.fromhex("A4C138123456") + struct.pack(">hBBHB", 234, 45, 87, 2950, 7))


def test_discovery_uses_configured_name():
    s = MqttHaSink({}, {"A4:C1:38:12:34:56": "Salon"})
    topic, conf = s.discovery_config(R, "voltage")
    assert topic == "homeassistant/sensor/atc_a4c138123456/voltage/config"
    assert conf["device"]["name"] == "Salon"
    assert conf["unique_id"] == "atc_a4c138123456_voltage"
    assert conf["entity_category"] == "diagnostic"


def test_publish_while_disconnected_warns_once(caplog):
    s = MqttHaSink({}, {})
    s.client.is_connected = lambda: False
    with caplog.at_level(logging.WARNING):
        s.publish(R)
        s.publish(R)
    assert s._dropped == 2
    assert sum("not connected" in m for m in caplog.messages) == 1
