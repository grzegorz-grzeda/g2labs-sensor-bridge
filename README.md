# g2labs-sensor-bridge

A small daemon that collects readings from home sensors over various radios and publishes them to
**Home Assistant** via MQTT with **MQTT Discovery**, so devices and entities show up in HA automatically.

```
 sources                         router                    sinks
┌──────────────────────┐   ┌─────────────────────┐   ┌──────────────────────────┐
│ ble    (bleak)       │──▶│ filter (only_named) │──▶│ mqtt_ha (paho + HA disc.)│
│ rtl433 (RTL-SDR) [β] │──▶│ de-dup / throttle   │   └──────────────────────────┘
└──────────────────────┘   └─────────────────────┘
```

## Supported devices

| Source | Device | Status |
|---|---|---|
| `ble` / decoder `atc` | Xiaomi LYWSD03MMC with **ATC1441** or **pvvx (custom)** firmware | ✅ |
| `rtl433` | anything [rtl_433](https://github.com/merbanan/rtl_433) decodes that reports temperature / humidity / pressure / wind / rain | 🧪 experimental |

BLE is passive (advertisements only, no pairing, no GATT connections), so sensor batteries are unaffected.

Every device gets entities for the metrics it reports, plus diagnostic ones (battery, voltage, RSSI).

## Install (Linux, systemd)

```bash
sudo useradd -r -s /usr/sbin/nologin sensor-bridge
sudo python3 -m venv /opt/sensor-bridge/venv
sudo /opt/sensor-bridge/venv/bin/pip install "git+https://github.com/grzegorz-grzeda/g2labs-sensor-bridge#egg=g2labs-sensor-bridge[ble]"

sudo install -d /etc/sensor-bridge
sudo install -m 640 -g sensor-bridge config.example.toml /etc/sensor-bridge/config.toml
sudoedit /etc/sensor-bridge/config.toml

# first run in the foreground to see what it picks up
sudo -u sensor-bridge /opt/sensor-bridge/venv/bin/sensor-bridge -c /etc/sensor-bridge/config.toml -v

sudo cp systemd/sensor-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now sensor-bridge
journalctl -u sensor-bridge -f
```

Requires Python ≥ 3.11. BLE on Linux goes through BlueZ/D-Bus (the `bluetooth` group is enough on Debian/Ubuntu);
bleak also works on Windows and macOS. For `rtl433` install `rtl-433` (e.g. `apt install rtl-433`).

## MQTT broker next to Home Assistant (Docker)

```yaml
  mosquitto:
    image: eclipse-mosquitto:2
    container_name: mosquitto
    restart: unless-stopped
    ports: ["1883:1883"]
    volumes:
      - ./mosquitto/config:/mosquitto/config
      - ./mosquitto/data:/mosquitto/data
```

`mosquitto/config/mosquitto.conf`:
```
listener 1883
allow_anonymous false
password_file /mosquitto/config/passwd
persistence true
persistence_location /mosquitto/data/
```

Create the password file **before** starting the broker (otherwise it crash-loops on the missing file):
```bash
docker run --rm -it -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -c /mosquitto/config/passwd homeassistant
docker run --rm -it -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd /mosquitto/config/passwd sensor-bridge
sudo chown -R 1883:1883 mosquitto && sudo chmod 0700 mosquitto/config/passwd
docker compose up -d mosquitto
```
Then in HA: *Settings → Devices & services → Add integration → MQTT*.

## MQTT topics

| Topic | Payload |
|---|---|
| `sensor-bridge/status` | `online` / `offline` (LWT, retained) |
| `sensor-bridge/<device_id>/state` | `{"temperature":23.4,"humidity":45,"battery":87,"voltage":2.95,"rssi":-71}` |
| `homeassistant/sensor/<device_id>/<metric>/config` | discovery (retained) |

Discovery is re-sent when HA publishes `online` on `homeassistant/status`.

To remove a device from HA, clear its retained discovery topics:
`mosquitto_pub -r -n -t homeassistant/sensor/<device_id>/<metric>/config` for each metric.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[ble,dev]"
pytest
```

See [CLAUDE.md](CLAUDE.md) for architecture and how to add a new source / decoder / sink.

## License

MIT, see [LICENSE](LICENSE).
