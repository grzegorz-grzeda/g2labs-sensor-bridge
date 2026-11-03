FROM python:3.12-slim

# rtl-433: decoder for the rtl433 source (RTL-SDR dongle passed in via /dev/bus/usb)
# gcc/libc6-dev: only a fallback if a Python dependency has no wheel for this arch; removed below
RUN apt-get update \
 && apt-get install -y --no-install-recommends rtl-433 gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[ble,system]" \
 && apt-get purge -y gcc libc6-dev && apt-get autoremove -y

# BLE needs the host's BlueZ over D-Bus: mount /run/dbus (see docker-compose.example.yml).
# Runs as root inside the container because the host D-Bus policy for BlueZ allows root.
ENTRYPOINT ["sensor-bridge"]
CMD ["-c", "/config/config.toml"]
