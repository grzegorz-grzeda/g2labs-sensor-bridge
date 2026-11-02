from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Callable

from ..model import Reading

Emit = Callable[[Reading], None]


class Source(ABC):
    """A producer of Readings. `run` must return when `stop` is set."""
    type: str = ""

    def __init__(self, cfg: dict, names: dict[str, str] | None = None):
        self.cfg = cfg
        self.names = names or {}  # [devices.names] from config (key -> display name)
        self.name = cfg.get("name", self.type)

    @abstractmethod
    async def run(self, emit: Emit, stop: asyncio.Event) -> None: ...
