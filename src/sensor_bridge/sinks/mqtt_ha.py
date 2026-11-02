"""MQTT sink with Home Assistant MQTT Discovery.

Topics (base_topic = "sensor-bridge"):
  sensor-bridge/<device_id>/state           shared by all instances, JSON values + receiver/ts (retained)
  sensor-bridge/bridge/<instance>/status    online/offline LWT of one bridge instance (retained)
  homeassistant/sensor/<device_id>/<metric>/config          sensor discovery (retained)
  homeassistant/binary_sensor/sensor_bridge_<instance>/connectivity/config   bridge discovery

Sensor discovery must be identical on every instance (same base_topic, same [devices.names]),
otherwise HA would see it flip between instances. Therefore sensor entities carry no per-bridge
availability; they go "unavailable" through `expire_after` when no instance hears them.
"""
from __future__ import annotations

import json
import logging
import re
import socket
import time

import paho.mqtt.client as mqtt

from .. import __version__
from ..model import METRICS, Reading
from . import Sink
from .arbitration import OwnerTable, should_publish

log = logging.getLogger(__name__)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_") or "bridge"


class MqttHaSink(Sink):
    type = "mqtt_ha"

    def __init__(self, cfg: dict, names: dict[str, str]):
        super().__init__(cfg, names)
        self.instance = _slug(cfg.get("instance") or socket.gethostname())
        self.base = cfg.get("base_topic", "sensor-bridge")
        self.disc = cfg.get("discovery_prefix", "homeassistant")
        self.avail = f"{self.base}/bridge/{self.instance}/status"
        self.expire_after = int(cfg.get("expire_after", 900))
        self.takeover_after = float(cfg.get("takeover_after", 300))
        self.rssi_hysteresis = float(cfg.get("rssi_hysteresis", 6))
        self.announced: set[tuple[str, str]] = set()  # (device_id, metric)
        self.owners = OwnerTable()

        self.host, self.port = cfg.get("host", "localhost"), int(cfg.get("port", 1883))
        client_id = cfg.get("client_id", f"sensor-bridge-{self.instance}")
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
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

    # ------------------------------------------------------------------ paho network thread
    def _on_connect(self, client, _ud, _flags, rc, _props=None):
        if getattr(rc, "is_failure", rc != 0):
            log.error("MQTT broker %s:%s refused connection: %s", self.host, self.port, rc)
            return
        log.info("MQTT connected to %s:%s as instance '%s'", self.host, self.port, self.instance)
        client.publish(self.avail, "online", qos=1, retain=True)
        client.publish(f"{self.base}/status", None, qos=1, retain=True)  # clear pre-0.2 global LWT topic
        client.subscribe(f"{self.disc}/status")
        client.subscribe(f"{self.base}/+/state")
        self._announce_bridge()
        self.announced.clear()

    def _on_connect_fail(self, _client, _ud):
        log.warning("MQTT broker %s:%s unreachable, retrying (up to every 60 s)", self.host, self.port)

    def _on_disconnect(self, _client, _ud, _flags, rc, _props=None):
        if getattr(rc, "is_failure", rc != 0):
            log.warning("MQTT disconnected: %s", rc)

    def _on_message(self, _client, _ud, msg):
        if msg.topic == f"{self.disc}/status":
            if msg.payload == b"online":
                log.info("Home Assistant restarted - re-sending discovery")
                self._announce_bridge()
                self.announced.clear()
            return
        parts = msg.topic.split("/")
        if len(parts) == 3 and parts[2] == "state" and msg.payload:
            try:
                state = json.loads(msg.payload)
            except ValueError:
                return
            if isinstance(state, dict):
                self.owners.update_from_state(parts[1], state)

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        self.client.connect_async(self.host, self.port, keepalive=60)
        self.client.loop_start()

    def stop(self):
        if self.client.is_connected():
            self.client.publish(self.avail, "offline", qos=1, retain=True).wait_for_publish(2)
        self.client.loop_stop()
        self.client.disconnect()

    # ------------------------------------------------------------------ discovery
    def state_topic(self, r: Reading) -> str:
        return f"{self.base}/{r.device_id}/state"

    def _device_block(self, r: Reading) -> dict:
        device = {
            "identifiers": [r.device_id],
            "name": self.display_name(r),
            "manufacturer": r.manufacturer or None,
            "model": r.model or None,
        }
        if r.connections:
            device["connections"] = [list(c) for c in r.connections]
        return {k: v for k, v in device.items() if v is not None}

    def discovery_config(self, r: Reading, key: str) -> tuple[str, dict]:
        """Discovery for one metric. Must not depend on the instance (see module doc)."""
        if key == "receiver":
            conf = {
                "name": "Receiver",
                "unique_id": f"{r.device_id}_receiver",
                "state_topic": self.state_topic(r),
                "value_template": "{{ value_json.receiver }}",
                "entity_category": "diagnostic",
                "icon": "mdi:access-point",
            }
        else:
            m = METRICS[key]
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
            }
        conf.update({
            "expire_after": self.expire_after,
            "device": self._device_block(r),
            "origin": {"name": "g2labs-sensor-bridge"},
        })
        conf = {k: v for k, v in conf.items() if v is not None}
        return f"{self.disc}/sensor/{r.device_id}/{key}/config", conf

    def bridge_discovery_config(self) -> tuple[str, dict]:
        node = f"sensor_bridge_{self.instance}"
        conf = {
            "name": "Connectivity",
            "unique_id": f"{node}_connectivity",
            "state_topic": self.avail,
            "payload_on": "online",
            "payload_off": "offline",
            "device_class": "connectivity",
            "entity_category": "diagnostic",
            "device": {
                "identifiers": [node],
                "name": f"Sensor bridge {self.instance}",
                "manufacturer": "g2labs",
                "model": "g2labs-sensor-bridge",
                "sw_version": __version__,
            },
            "origin": {"name": "g2labs-sensor-bridge", "sw": __version__},
        }
        return f"{self.disc}/binary_sensor/{node}/connectivity/config", conf

    def _announce_bridge(self):
        topic, conf = self.bridge_discovery_config()
        self.client.publish(topic, json.dumps(conf), qos=1, retain=True)

    # ------------------------------------------------------------------ publishing
    def build_state(self, r: Reading, now: float) -> dict:
        return {**r.values, "receiver": self.instance, "ts": round(now, 1)}

    def publish(self, r: Reading) -> None:
        if not self.client.is_connected():
            self._dropped += 1
            now = time.monotonic()
            if now - self._last_drop_warn >= 60:
                log.warning("MQTT not connected - dropped %d reading(s) so far", self._dropped)
                self._last_drop_warn = now
            return

        now = time.time()
        owner = self.owners.get(r.device_id)
        my_rssi = r.values.get("rssi")
        if not should_publish(self.instance, my_rssi, owner, now, self.takeover_after, self.rssi_hysteresis):
            log.debug("%s owned by '%s' (rssi %s vs mine %s) - skipping", r.device_id, owner.receiver, owner.rssi, my_rssi)
            return
        if owner is not None and owner.receiver != self.instance:
            log.info("Taking over %s from '%s' (rssi %s -> %s, last seen %.0f s ago)",
                     r.device_id, owner.receiver, owner.rssi, my_rssi, now - owner.ts)

        for key in (*r.values, "receiver"):
            if (r.device_id, key) not in self.announced:
                topic, conf = self.discovery_config(r, key)
                self.client.publish(topic, json.dumps(conf), qos=1, retain=True)
                self.announced.add((r.device_id, key))
                log.info("Announced %s.%s ('%s')", r.device_id, key, self.display_name(r))

        state = self.build_state(r, now)
        # record ourselves as owner right away, without waiting for the broker echo
        self.owners.update_from_state(r.device_id, state)
        self.client.publish(self.state_topic(r), json.dumps(state), qos=0, retain=True)
