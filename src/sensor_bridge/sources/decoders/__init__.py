"""BLE advertisement decoders.

Each decoder is `decode(address, service_data, manufacturer_data) -> Reading | None`
and must not import bleak, so it can be unit-tested without a radio.
To add a device type: create a module here and append its `decode` to BLE_DECODERS.
"""
from . import atc

BLE_DECODERS = {
    "atc": atc.decode,
}
