from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tomllib

from . import __version__
from .core import run


def main() -> None:
    ap = argparse.ArgumentParser(prog="sensor-bridge", description="Home sensors -> Home Assistant via MQTT")
    ap.add_argument("-c", "--config", default="/etc/sensor-bridge/config.toml")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else cfg.get("log_level", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("bleak").setLevel(logging.WARNING)
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
