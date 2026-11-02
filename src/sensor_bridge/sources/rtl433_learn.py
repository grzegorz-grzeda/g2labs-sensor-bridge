"""Learn mode for rtl_433 sensors whose id is re-randomised on every battery change.

Mimics what the original weather station console does: it pairs with the first transmitter heard on a
channel and follows a new id after the old one goes silent.

Config: a [devices.names] key with `*` as id, e.g. "Nexus-TH/*/1" (or "Model/*" for models without
channels), declares a *slot*. The slot gets a stable device_id `rtl433_<model>_ch<channel>` (so the HA
entity survives battery changes) and is bound to one concrete id:

  * unbound slot            -> bind to the first id heard on that model/channel ("learned")
  * frame from bound id      -> pass through under the stable device_id
  * frame from another id    -> if the bound id has been silent for `relearn_after` s, re-bind to it
                                ("re-learned"); otherwise it is someone else's sensor (a neighbour) and
                                is handled as an ordinary, unbound device.

Bindings are persisted to a JSON file so a restart does not re-pair with whatever transmits first.
Pure logic + a tiny file store; time is injectable for tests.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


@dataclass
class Slot:
    key: str               # the [devices.names] key, e.g. "Nexus-TH/*/1"
    model: str
    channel: str | None
    bound_id: str | None = None
    last_seen: float = field(default=0.0)

    @property
    def device_id(self) -> str:
        return f"rtl433_{_slug(self.model)}_" + (f"ch{_slug(self.channel)}" if self.channel is not None else "any")


def parse_slots(names: dict[str, str]) -> list[Slot]:
    slots = []
    for key in names:
        parts = key.split("/")
        if len(parts) in (2, 3) and parts[1] == "*":
            slots.append(Slot(key, parts[0], parts[2] if len(parts) == 3 else None))
    return slots


class Learner:
    def __init__(self, names: dict[str, str], relearn_after: float = 300, state_file: str | None = None,
                 clock=time.monotonic):
        self.slots = parse_slots(names)
        self.relearn_after = relearn_after
        self.state_file = state_file
        self.clock = clock
        self._load()
        now = clock()
        for s in self.slots:
            s.last_seen = now  # after a restart, give the bound sensor a full window to show up

    def __bool__(self) -> bool:
        return bool(self.slots)

    # -------------------------------------------------------------- persistence
    def _load(self) -> None:
        if not self.state_file:
            return
        try:
            with open(self.state_file) as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log.warning("cannot read %s: %s - starting with no bindings", self.state_file, e)
            return
        for s in self.slots:
            if isinstance(data.get(s.key), str):
                s.bound_id = data[s.key]
                log.info("Binding %s -> id %s (from %s)", s.key, s.bound_id, self.state_file)

    def _save(self) -> None:
        if not self.state_file:
            return
        data = {s.key: s.bound_id for s in self.slots if s.bound_id is not None}
        try:
            d = os.path.dirname(self.state_file) or "."
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".bindings")
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, self.state_file)
        except OSError as e:
            log.error("cannot save bindings to %s: %s (they will be re-learned after restart)", self.state_file, e)

    # -------------------------------------------------------------- matching
    def match(self, model: str, ident: str, channel: str | None) -> Slot | None:
        """Return the slot this frame belongs to (binding/re-binding as needed), or None."""
        now = self.clock()
        for s in self.slots:
            if s.model != model or s.channel != channel:
                continue
            if s.bound_id is None:
                s.bound_id, s.last_seen = ident, now
                log.info("Learned %s -> id %s", s.key, ident)
                self._save()
                return s
            if s.bound_id == ident:
                s.last_seen = now
                return s
            silent = now - s.last_seen
            if silent >= self.relearn_after:
                log.info("Re-learned %s: id %s -> %s (old id silent %.0f s)", s.key, s.bound_id, ident, silent)
                s.bound_id, s.last_seen = ident, now
                self._save()
                return s
            log.debug("%s/%s/%s ignored for slot %s (bound to %s, seen %.0f s ago)",
                      model, ident, channel, s.key, s.bound_id, silent)
        return None
