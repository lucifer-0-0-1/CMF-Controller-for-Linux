"""Clean input event types for the CMF Linux Controller."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Kind(Enum):
    ROTATE = "rotate"
    CLICK = "click"
    DOUBLE = "double"
    TRIPLE = "triple"
    HOLD = "hold"
    PRESS = "press"
    RELEASE = "release"


@dataclass(frozen=True)
class Event:
    kind: Kind
    delta: int = 0
    source: str = ""
    timestamp: float = field(default_factory=time.monotonic)

    def __str__(self) -> str:
        if self.kind == Kind.ROTATE:
            return f"Event(ROTATE, delta={self.delta:+d}, src={self.source})"
        return f"Event({self.kind.value.upper()}, src={self.source})"
