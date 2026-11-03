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
| `system` | the machine the bridge runs on: CPU temperature, CPU usage, memory, disk usage | ✅ |
| `rtl433` | anything [rtl_433](https://github.com/merbanan/rtl_433) decodes that reports temperature / humidity / pressure / wind / rain | 🧪 experimental |

Many cheap 433 MHz transmitters pick a new random id on every battery change. Name them as
`"Model/*/channel"` in `[devices.names]` and the bridge pairs with the first id heard on that channel,
then follows the new id after the old one has been silent for `relearn_after` seconds – the same thing
the original station console does. The HA entity stays the same. Bindings are kept in
`/var/lib/sensor-bridge/rtl433_bindings.json`; delete an entry there to force re-pairing.

BLE is passive (advertisements only, no pairing, no GATT connections), so sensor batteries are unaffected.

Every device gets entities for the metrics it reports, plus diagnostic ones (battery, voltage, RSSI,
which receiver currently serves it).

## Multiple receivers

You can run the bridge on several machines (e.g. a PC and the Raspberry Pi with HA) to cover the whole
house. All instances publish to the same topics; for each sensor exactly one instance — its *receiver* —
publishes at a time. Another instance takes the sensor over when it hears it at least `rssi_hysteresis` dB
stronger, or when the current receiver has been silent for `takeover_after` seconds (machine down, sensor
out of range). No central coordinator, the broker is the shared state.

Requirements: same `base_topic` and same `[devices.names]` everywhere, unique `instance` / `client_id`
per machine (both default to the hostname). Each instance appears in HA as a *Sensor bridge &lt;instance&gt;*
device with a connectivity entity.

Clocks must be roughly in sync (NTP) — takeover timing uses timestamps from the state payload.

## Install (Linux, systemd)

```bash
sudo useradd -r -s /usr/sbin/nologin sensor-bridge
sudo python3 -m venv /opt/sensor-bridge/venv
sudo /opt/sensor-bridge/venv/bin/pip install "g2labs-sensor-bridge[ble,system] @ git+https://github.com/grzegorz-grzeda/g2labs-sensor-bridge"

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

## Install (Docker, e.g. Raspberry Pi next to Home Assistant)

Add the service from [`docker-compose.example.yml`](docker-compose.example.yml) to your compose file, then:

```bash
mkdir -p sensor-bridge
curl -fsSL https://raw.githubusercontent.com/grzegorz-grzeda/g2labs-sensor-bridge/main/config.example.toml \
  -o sensor-bridge/config.toml
nano sensor-bridge/config.toml        # host = "mosquitto", credentials, names
docker compose up -d --build sensor-bridge
docker logs -f sensor-bridge
```

The container uses the host's Bluetooth through BlueZ (`/run/dbus` mounted read-only), so `bluetoothd`
must be running on the host. To update: `docker compose build --pull sensor-bridge && docker compose up -d sensor-bridge`.

On a Pi 4 the on-board Bluetooth shares the chip/antenna with Wi-Fi; continuous scanning can degrade
Wi-Fi, which does not matter if the Pi is on Ethernet.

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
| `sensor-bridge/bridge/<instance>/status` | `online` / `offline` (LWT of one bridge, retained) |
| `sensor-bridge/<device_id>/state` | `{"temperature":23.4,"humidity":45,"battery":87,"voltage":2.95,"rssi":-71,"receiver":"g2labs_rpi","ts":1793660520.1}` |
| `homeassistant/sensor/<device_id>/<metric>/config` | sensor discovery (retained) |
| `homeassistant/binary_sensor/sensor_bridge_<instance>/connectivity/config` | bridge discovery (retained) |

Discovery is re-sent when HA publishes `online` on `homeassistant/status`. Sensor entities have no
bridge-level availability (several bridges may serve them); they become *unavailable* via `expire_after`
when no bridge hears them.

To remove a device from HA, clear its retained discovery topics:
`mosquitto_pub -r -n -t homeassistant/sensor/<device_id>/<metric>/config` for each metric.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[ble,system,dev]"
pytest
```

See [CLAUDE.md](CLAUDE.md) for architecture and how to add a new source / decoder / sink.

## License

MIT, see [LICENSE](LICENSE).
