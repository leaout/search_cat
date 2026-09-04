from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class WindowReference:
    id: str
    hwnd: int
    pid: int
    title: str
    number: int
    left: int
    top: int
    width: int
    height: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FrameReference:
    id: str
    width: int
    height: int
    capture_mode: str
    coordinate_space: str
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MatchResult:
    found: bool
    score: float
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result['center'] = [self.x + self.width // 2, self.y + self.height // 2]
        return result
