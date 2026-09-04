import contextlib
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Frame:
    id: str
    width: int
    height: int
    capture_mode: str
    coordinate_space: str
    timestamp: float


@dataclass
class Match:
    found: bool
    score: float
    x: int
    y: int
    width: int
    height: int
    center: list[int]


class WindowAPI:
    def __init__(self, call: Callable):
        self._call = call

    def current(self) -> dict[str, Any]:
        return self._call('window.current', {})

    def is_alive(self) -> bool:
        return bool(self._call('window.is_alive', {}))


class CaptureAPI:
    def __init__(self, call: Callable):
        self._call = call

    def window(
        self,
        mode: str = 'auto',
        area: str = 'window',
        region: tuple[int, int, int, int] | None = None,
    ) -> Frame:
        result = self._call('capture.window', {'mode': mode, 'area': area, 'region': region})
        return Frame(**result)


class VisionAPI:
    def __init__(self, call: Callable):
        self._call = call

    def find_image(
        self, frame: Frame, resource: str, threshold: float = 0.85, grayscale: bool = True,
    ) -> Match:
        result = self._call('vision.find_image', {
            'frame_id': frame.id,
            'resource': resource,
            'threshold': threshold,
            'grayscale': grayscale,
        })
        return Match(**result)

    def get_color(self, frame: Frame, x: int, y: int, order: str = 'RGB') -> list[int]:
        return self._call('vision.get_color', {
            'frame_id': frame.id, 'x': x, 'y': y, 'order': order,
        })

    def compare_color(
        self, actual: list[int], target: list[int], tolerance: float = 30,
    ) -> dict[str, Any]:
        return self._call('vision.compare_color', {
            'actual': actual, 'target': target, 'tolerance': tolerance,
        })


class OCRAPI:
    def __init__(self, call: Callable):
        self._call = call

    def recognize(self, frame: Frame, min_confidence: float = 0.5) -> list[dict[str, Any]]:
        return self._call('ocr.recognize', {
            'frame_id': frame.id,
            'min_confidence': min_confidence,
        })


class MouseAPI:
    def __init__(self, call: Callable):
        self._call = call

    def click(
        self,
        x: int,
        y: int,
        button: str = 'left',
        mode: str = 'foreground',
        coordinate_space: str = 'window',
    ) -> dict[str, Any]:
        return self._call('mouse.click', {
            'x': x, 'y': y, 'button': button, 'mode': mode,
            'coordinate_space': coordinate_space,
        })


class KeyboardAPI:
    def __init__(self, call: Callable):
        self._call = call

    def press(self, key: str, mode: str = 'foreground') -> dict[str, Any]:
        return self._call('keyboard.press', {'key': key, 'mode': mode})

    def hotkey(self, *keys: str, mode: str = 'foreground') -> dict[str, Any]:
        return self._call('keyboard.hotkey', {'keys': list(keys), 'mode': mode})

    def type_text(self, text: str, mode: str = 'foreground') -> dict[str, Any]:
        return self._call('keyboard.type_text', {'text': text, 'mode': mode})


class DebugAPI:
    def __init__(self, emit: Callable):
        self._emit = emit

    def watch(self, name: str, value: Any) -> None:
        self._emit('watch', {'name': name, 'value': value})


class StorageAPI:
    def __init__(self, call: Callable):
        self._call = call

    def read_json(self, path: str, default: Any = None) -> Any:
        return self._call('storage.read_json', {'path': path, 'default': default})

    def write_json(self, path: str, value: Any) -> dict[str, Any]:
        return self._call('storage.write_json', {'path': path, 'value': value})


class PluginContext:
    """Public SDK object passed to plugin lifecycle functions."""

    def __init__(self, call: Callable, emit: Callable, config: dict[str, Any], dry_run: bool):
        self._call = call
        self._emit = emit
        self.config = config
        self.dry_run = dry_run
        self.windows = WindowAPI(call)
        self.capture = CaptureAPI(call)
        self.vision = VisionAPI(call)
        self.ocr = OCRAPI(call)
        self.mouse = MouseAPI(call)
        self.keyboard = KeyboardAPI(call)
        self.debug = DebugAPI(emit)
        self.storage = StorageAPI(call)

    def log(self, message: str, level: str = 'info') -> None:
        self._emit('log', {'level': level, 'message': str(message)})

    def sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0, float(seconds))
        while time.monotonic() < deadline:
            time.sleep(min(0.05, deadline - time.monotonic()))

    @contextlib.contextmanager
    def step(self, name: str):
        started = time.monotonic()
        self._emit('step_started', {'name': name})
        try:
            yield
        except Exception as error:
            self._emit('step_failed', {'name': name, 'error': str(error)})
            raise
        else:
            self._emit('step_finished', {
                'name': name,
                'duration_ms': round((time.monotonic() - started) * 1000, 2),
            })
