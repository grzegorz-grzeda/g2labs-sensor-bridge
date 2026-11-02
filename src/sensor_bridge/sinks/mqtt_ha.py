"""MQTT sink with Home Assistant MQTT Discovery."""
from __future__ import annotations

import json
import logging
import time

import paho.mqtt.client as mqtt

from .. import __version__
from ..model import METRICS, Reading
from . import Sink

log = logging.getLogger(__name__)


class MqttHaSink(Sink):
    type = "mqtt_ha"

    def __init__(self, cfg: dict, names: dict[str, str]):
        super().__init__(cfg, names)
        self.base = cfg.get("base_topic", "sensor-bridge")
        self.disc = cfg.get("discovery_prefix", "homeassistant")
        self.avail = f"{self.base}/status"
        self.expire_after = int(cfg.get("expire_after", 900))
        self.announced: set[tuple[str, str]] = set()  # (device_id, metric)

        self.host, self.port = cfg.get("host", "localhost"), int(cfg.get("port", 1883))
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg.get("client_id", "sensor-bridge"))
        if cfg.get("username"):
            self.client.username_pw_set(cfg["username"], cfg.get("password"))
        if cfg.get("tls"):
            self.client.tls_set()
        self.client.will_set(self.avail, "offline", qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(1, 60)
        self._last_drop_warn = float("-inf")
        self._dropped = 0

    # paho network thread
    def _on_connect(self, client, _ud, _flags, rc, _props=None):
        if getattr(rc, "is_failure", rc != 0):
            log.error("MQTT broker %s:%s refused connection: %s", self.host, self.port, rc)
            return
        log.info("MQTT connected to %s:%s", self.host, self.port)
        client.publish(self.avail, "online", qos=1, retain=True)
        client.subscribe(f"{self.disc}/status")
        self.announced.clear()

    def _on_connect_fail(self, _client, _ud):
        log.warning("MQTT broker %s:%s unreachable, retrying (up to every 60 s)", self.host, self.port)

    def _on_disconnect(self, _client, _ud, _flags, rc, _props=None):
        if getattr(rc, "is_failure", rc != 0):
            log.warning("MQTT disconnected: %s", rc)

    def _on_message(self, _client, _ud, msg):
        if msg.topic == f"{self.disc}/status" and msg.payload == b"online":
            log.info("Home Assistant restarted - re-sending discovery")
            self.announced.clear()

    def start(self):
        self.client.connect_async(self.host, self.port, keepalive=60)
        self.client.loop_start()

    def stop(self):
        if self.client.is_connected():
            self.client.publish(self.avail, "offline", qos=1, retain=True).wait_for_publish(2)
        self.client.loop_stop()
        self.client.disconnect()

    def state_topic(self, r: Reading) -> str:
        return f"{self.base}/{r.device_id}/state"

    def discovery_config(self, r: Reading, key: str) -> tuple[str, dict]:
        m = METRICS[key]
        device = {
            "identifiers": [r.device_id],
            "name": self.display_name(r),
            "manufacturer": r.manufacturer or None,
            "model": r.model or None,
        }
        if r.connections:
            device["connections"] = [list(c) for c in r.connections]
        conf = {
            "name": m.name,
            "unique_id": f"{r.device_id}_{key}",
            "state_topic": self.state_topic(r),
            "value_template": f"{{{{ value_json.{key} }}}}",
            "device_class": m.device_class,
            "unit_of_measurement": m.unit,
            "state_class": m.state_class,
            "entity_category": m.entity_category,
            "suggested_display_precision": m.precision,
            "expire_after": self.expire_after,
            "availability_topic": self.avail,
            "device": {k: v for k, v in device.items() if v is not None},
            "origin": {"name": "g2labs-sensor-bridge", "sw": __version__},
        }
        conf = {k: v for k, v in conf.items() if v is not None}
        return f"{self.disc}/sensor/{r.device_id}/{key}/config", conf

    def publish(self, r: Reading) -> None:
        if not self.client.is_connected():
            self._dropped += 1
            now = time.monotonic()
            if now - self._last_drop_warn >= 60:
                log.warning("MQTT not connected - dropped %d reading(s) so far", self._dropped)
                self._last_drop_warn = now
            return
        for key in r.values:
            if (r.device_id, key) not in self.announced:
                topic, conf = self.discovery_config(r, key)
                self.client.publish(topic, json.dumps(conf), qos=1, retain=True)
                self.announced.add((r.device_id, key))
                log.info("Announced %s.%s ('%s')", r.device_id, key, self.display_name(r))
        self.client.publish(self.state_topic(r), json.dumps(r.values), qos=0, retain=True)
