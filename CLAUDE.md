# CLAUDE.md

Daemon bridging home sensors (BLE, SDR, more later) to Home Assistant over MQTT discovery.
Owner's HA runs in Docker on a Raspberry Pi 4 (`g2labs-rpi`) with Mosquitto alongside; this daemon
typically runs on a different Linux machine that has the radios.

## Architecture (`src/sensor_bridge/`)

- `model.py` – `Reading` (one sample from one device) and the `METRICS` catalogue (key → HA device_class/unit/...).
  Sources may only emit keys present in `METRICS`; `Reading` validates this.
- `sources/` – producers. `Source.run(emit, stop)` is an asyncio coroutine that calls `emit(Reading)` and
  returns when `stop` is set. Registered in `sources/__init__.py:SOURCES` (lazy import, so optional deps
  like bleak are only needed when the source is enabled).
  - `ble.py` – passive bleak scanner; dispatches each advertisement to decoders in `sources/decoders/`.
  - `decoders/` – pure functions `decode(address, service_data, manufacturer_data) -> Reading | None`;
    **no bleak import** so they are unit-testable. Registered in `decoders/__init__.py:BLE_DECODERS`.
  - `rtl433.py` – runs `rtl_433 -F json` subprocess, maps JSON fields via `FIELD_MAP` (experimental, untested on HW).
    `FrameMerger` keeps the last value of each metric per device (stations alternating frame types).
  - `rtl433_learn.py` – learn mode for ids re-randomised on battery change: `"Model/*/ch"` names keys are
    slots with stable device_id `rtl433_<model>_ch<ch>`; bound id persisted in `state_file`. Sources get
    the raw `[devices.names]` dict as their second constructor argument.
  - `system.py` – host metrics of the machine running the bridge via psutil (extra `[system]`),
    device `host_<hostname>`; psutil injectable for tests.
- `core.py` – `Router`: `only_named` filter per source type, de-dup by frame counter, `min_interval` throttle,
  fan-out to sinks. `run(cfg)` wires everything and handles SIGINT/SIGTERM.
- `sinks/` – consumers. `Sink.publish(Reading)` is called on the asyncio loop and must not block.
  - `mqtt_ha.py` – paho-mqtt (own network thread), HA discovery per (device_id, metric) on first sight,
    state as one JSON per device (+ `receiver`, `ts`), per-instance LWT + bridge connectivity entity,
    re-announce on `homeassistant/status: online`.
  - `arbitration.py` – multi-receiver logic (pure): each instance subscribes to `<base>/+/state`; the last
    publisher is the device's owner; others take over on `rssi_hysteresis` dB better signal or after
    `takeover_after` s of owner silence.

## Multi-instance invariants

- Sensor discovery payloads must be **identical on every instance** (no instance name, version or
  per-bridge availability in them) – otherwise HA flips config between bridges. Tested in `test_mqtt_sink.py`.
- `instance` (default hostname) and `client_id` (default `sensor-bridge-<instance>`) must be unique per machine.
- Deploy targets: systemd on a PC, Docker container on the Raspberry Pi next to HA (`Dockerfile`,
  `docker-compose.example.yml`, BLE via mounted `/run/dbus`).

## Conventions

- `device_id`: stable, `[a-z0-9_]`, prefixed by device family (`atc_<mac>`, `rtl433_<model>_<id>[_ch<ch>]`,
  learn slots `rtl433_<model>_ch<ch>`). It is the
  HA `unique_id` base – **never change the scheme for existing devices** or HA will create duplicates.
- `aliases`: user-facing ids accepted as keys in `[devices.names]` (MAC for BLE, `model/id[/channel]` for rtl_433).
- New metric → add to `METRICS`. New BLE device → new module in `decoders/` + register + tests with real
  captured payloads. New radio → new `Source` subclass + register in `SOURCES`.
- Config is TOML (`config.example.toml`); keep it in sync with code changes.

## Testing

`pip install -e ".[ble,system,dev]" && pytest`. Tests must not need a radio or a broker.
Hardware verification is manual: run `sensor-bridge -c config.toml -v` and watch the logs.

## Ideas / roadmap

- BTHome v2 decoder (pvvx firmware can advertise BTHome; also many other DIY sensors).
- `binary_sensor` support (e.g. rtl_433 `battery_ok`, door/window contacts) – needs a component field in `Metric`.
- Other sinks (InfluxDB, HTTP to own API on VPS).
- Multi-arch image published to GHCR (now built locally from the git URL).
