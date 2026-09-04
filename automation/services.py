import time
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pyautogui
import win32api
import win32con
import win32gui

from automation.models import FrameReference, MatchResult, WindowReference
from core.text import repair_utf8_gbk_mojibake
from core.winhandler import WindowHandler
from core.winoperator import Win32Keyboard


class AutomationHost:
    """Host-side implementation of the stable plugin automation API."""

    def __init__(
        self,
        plugin_directory: Path,
        data_directory: Path,
        permissions: list[str],
        dry_run: bool = True,
    ):
        self.plugin_directory = plugin_directory.resolve()
        self.data_directory = data_directory.resolve()
        self.dry_run = dry_run
        self.permissions = set(permissions)
        self.frames: dict[str, np.ndarray] = {}
        self.windows: dict[str, WindowReference] = {}
        self.bound_window_id: str | None = None
        self.window_handler = WindowHandler()
        self.keyboard = Win32Keyboard()

    def register_window(self, info: dict[str, Any]) -> WindowReference:
        hwnd = int(info['hwnd'])
        live_title = self.window_handler.get_unicode_window_title(
            hwnd, str(info.get('title', ''))
        )
        reference = WindowReference(
            id=str(info.get('id') or f"hwnd-{int(info['hwnd'])}"),
            hwnd=hwnd,
            pid=int(info.get('pid', 0)),
            # Repair once more at the host boundary. This must happen before the
            # JSON protocol sanitizer replaces surrogate-escaped ANSI bytes.
            title=repair_utf8_gbk_mojibake(live_title),
            number=int(info.get('number', 1)),
            left=int(info.get('left', 0)),
            top=int(info.get('top', 0)),
            width=int(info.get('width', 0)),
            height=int(info.get('height', 0)),
        )
        self.windows[reference.id] = reference
        self.bound_window_id = reference.id
        return reference

    def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        handlers = {
            'window.current': self._window_current,
            'window.is_alive': self._window_is_alive,
            'capture.window': self._capture_window,
            'vision.find_image': self._find_image,
            'vision.get_color': self._get_color,
            'vision.compare_color': self._compare_color,
            'ocr.recognize': self._ocr_recognize,
            'mouse.click': self._mouse_click,
            'keyboard.press': self._keyboard_press,
            'keyboard.hotkey': self._keyboard_hotkey,
            'keyboard.type_text': self._keyboard_type_text,
            'storage.read_json': self._storage_read_json,
            'storage.write_json': self._storage_write_json,
        }
        if method not in handlers:
            raise ValueError(f'不支持的自动化方法: {method}')
        permission = self._required_permission(method, params)
        if permission and permission not in self.permissions:
            raise PermissionError(f'插件未声明权限: {permission}')
        return handlers[method](params)

    @staticmethod
    def _required_permission(method: str, params: dict[str, Any]) -> str | None:
        if method.startswith('window.'):
            return 'window.bind'
        if method.startswith('capture.') or method.startswith('vision.') or method.startswith('ocr.'):
            return 'screen.capture'
        if method.startswith('storage.'):
            return 'filesystem.plugin_data'
        if method.startswith('mouse.'):
            return f"mouse.{params.get('mode', 'foreground')}"
        if method.startswith('keyboard.'):
            return f"keyboard.{params.get('mode', 'foreground')}"
        return None

    def _current_window(self) -> WindowReference:
        if not self.bound_window_id or self.bound_window_id not in self.windows:
            raise RuntimeError('插件尚未绑定目标窗口')
        return self.windows[self.bound_window_id]

    def _window_current(self, _params: dict[str, Any]) -> dict[str, Any]:
        window = self._current_window()
        # Refresh from HWND instead of trusting the title captured by the UI.
        window.title = self.window_handler.get_unicode_window_title(window.hwnd, window.title)
        return window.to_dict()

    def _window_is_alive(self, _params: dict[str, Any]) -> bool:
        return bool(win32gui.IsWindow(self._current_window().hwnd))

    def _capture_window(self, params: dict[str, Any]) -> dict[str, Any]:
        window = self._current_window()
        mode = str(params.get('mode', 'auto'))
        if not win32gui.IsWindow(window.hwnd):
            raise RuntimeError('目标窗口已经失效')
        left, top, right, bottom = win32gui.GetWindowRect(window.hwnd)
        width, height = right - left, bottom - top
        area = str(params.get('area', 'window'))
        if area not in {'window', 'client'}:
            raise ValueError('截图区域类型必须是 window 或 client')
        capture_mode = mode
        try:
            if mode not in {'auto', 'background'}:
                raise RuntimeError('使用前台截图')
            image = self.window_handler.capture_window_image(window.hwnd, width, height)
            if image.mean() < 1 or image.std() < 1:
                raise RuntimeError('后台截图为空白')
            capture_mode = 'background'
        except Exception:
            if mode == 'background':
                raise
            image = self.window_handler.capture_screenshot_ext(left, top, right, bottom)
            capture_mode = 'foreground'
        if area == 'client':
            client_left, client_top = win32gui.ClientToScreen(window.hwnd, (0, 0))
            _, _, client_width, client_height = win32gui.GetClientRect(window.hwnd)
            offset_x, offset_y = client_left - left, client_top - top
            image = image[offset_y:offset_y + client_height, offset_x:offset_x + client_width].copy()
            width, height = client_width, client_height
        region = params.get('region')
        if region:
            x, y, region_width, region_height = (int(value) for value in region)
            if x < 0 or y < 0 or x + region_width > width or y + region_height > height:
                raise ValueError('截图区域超出窗口范围')
            image = image[y:y + region_height, x:x + region_width].copy()
        frame_id = uuid.uuid4().hex
        self.frames[frame_id] = image
        if len(self.frames) > 20:
            self.frames.pop(next(iter(self.frames)))
        frame = FrameReference(
            id=frame_id,
            width=int(image.shape[1]),
            height=int(image.shape[0]),
            capture_mode=capture_mode,
            coordinate_space=area,
            timestamp=time.time(),
        )
        return frame.to_dict()

    def _frame(self, frame_id: str) -> np.ndarray:
        if frame_id not in self.frames:
            raise ValueError('截图已过期，请重新捕获')
        return self.frames[frame_id]

    def _resource_path(self, relative_path: str) -> Path:
        path = (self.plugin_directory / 'assets' / relative_path).resolve()
        assets_directory = (self.plugin_directory / 'assets').resolve()
        if path != assets_directory and assets_directory not in path.parents:
            raise ValueError('资源路径不能离开插件 assets 目录')
        if not path.is_file():
            raise FileNotFoundError(f'插件资源不存在: {relative_path}')
        return path

    def _data_path(self, relative_path: str) -> Path:
        path = (self.data_directory / 'data' / relative_path).resolve()
        data_root = (self.data_directory / 'data').resolve()
        if path != data_root and data_root not in path.parents:
            raise ValueError('数据路径不能离开插件 data 目录')
        return path

    def _find_image(self, params: dict[str, Any]) -> dict[str, Any]:
        image = self._frame(str(params['frame_id']))
        template_path = self._resource_path(str(params['resource']))
        template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
        if template is None:
            raise ValueError(f'无法读取模板: {params["resource"]}')
        source = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        if params.get('grayscale', True):
            source = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
            template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        if template.shape[0] > source.shape[0] or template.shape[1] > source.shape[1]:
            return MatchResult(False, 0.0).to_dict()
        result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        threshold = float(params.get('threshold', 0.85))
        match = MatchResult(
            found=bool(score >= threshold),
            score=float(score),
            x=int(location[0]),
            y=int(location[1]),
            width=int(template.shape[1]),
            height=int(template.shape[0]),
        )
        return match.to_dict()

    def _get_color(self, params: dict[str, Any]) -> list[int]:
        image = self._frame(str(params['frame_id']))
        x, y = int(params['x']), int(params['y'])
        if x < 0 or y < 0 or x >= image.shape[1] or y >= image.shape[0]:
            raise ValueError('取色坐标超出截图范围')
        color = [int(value) for value in image[y, x]]
        return color if params.get('order', 'RGB').upper() == 'RGB' else color[::-1]

    @staticmethod
    def _compare_color(params: dict[str, Any]) -> dict[str, Any]:
        actual = np.asarray(params['actual'], dtype=float)
        target = np.asarray(params['target'], dtype=float)
        difference = float(np.linalg.norm(actual - target))
        tolerance = float(params.get('tolerance', 30))
        return {'matched': difference <= tolerance, 'difference': difference}

    def _ocr_recognize(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Recognize text in a captured frame and return client-relative boxes."""
        if not hasattr(self, '_ocr_engine'):
            from core.ocr import Ocr
            self._ocr_engine = Ocr()
        image = self._frame(str(params['frame_id']))
        minimum = float(params.get('min_confidence', 0.5))
        result = self._ocr_engine.do_ocr_ext(cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        lines = []
        for item in result or []:
            if len(item) < 2 or len(item[1]) < 2:
                continue
            text, confidence = str(item[1][0]), float(item[1][1])
            if confidence < minimum:
                continue
            points = [[int(point[0]), int(point[1])] for point in item[0]]
            xs, ys = [point[0] for point in points], [point[1] for point in points]
            lines.append({
                'text': text,
                'confidence': confidence,
                'box': points,
                'center': [int(sum(xs) / len(xs)), int(sum(ys) / len(ys))],
            })
        return lines

    def _mouse_click(self, params: dict[str, Any]) -> dict[str, Any]:
        window = self._current_window()
        x, y = int(params['x']), int(params['y'])
        mode = str(params.get('mode', 'foreground'))
        button = str(params.get('button', 'left'))
        coordinate_space = str(params.get('coordinate_space', 'window'))
        window_left, window_top, window_right, window_bottom = win32gui.GetWindowRect(window.hwnd)
        client_left, client_top = win32gui.ClientToScreen(window.hwnd, (0, 0))
        _, _, client_width, client_height = win32gui.GetClientRect(window.hwnd)
        limit_width = client_width if coordinate_space == 'client' else window_right - window_left
        limit_height = client_height if coordinate_space == 'client' else window_bottom - window_top
        if x < 0 or y < 0 or x >= limit_width or y >= limit_height:
            raise ValueError('点击坐标超出绑定窗口范围')
        if self.dry_run:
            return {'executed': False, 'dry_run': True, 'x': x, 'y': y, 'mode': mode}
        if mode == 'background':
            if coordinate_space == 'window':
                x -= client_left - window_left
                y -= client_top - window_top
                if x < 0 or y < 0 or x >= client_width or y >= client_height:
                    raise ValueError('后台点击只能作用于窗口客户区')
            message_down = win32con.WM_LBUTTONDOWN if button == 'left' else win32con.WM_RBUTTONDOWN
            message_up = win32con.WM_LBUTTONUP if button == 'left' else win32con.WM_RBUTTONUP
            key_flag = win32con.MK_LBUTTON if button == 'left' else win32con.MK_RBUTTON
            position = win32api.MAKELONG(x, y)
            win32gui.PostMessage(window.hwnd, message_down, key_flag, position)
            win32gui.PostMessage(window.hwnd, message_up, 0, position)
        else:
            win32gui.ShowWindow(window.hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(window.hwnd)
            origin_x = client_left if coordinate_space == 'client' else window_left
            origin_y = client_top if coordinate_space == 'client' else window_top
            pyautogui.click(origin_x + x, origin_y + y, button=button)
        return {
            'executed': True, 'dry_run': False, 'x': x, 'y': y,
            'mode': mode, 'coordinate_space': coordinate_space,
        }

    def _keyboard_press(self, params: dict[str, Any]) -> dict[str, Any]:
        window = self._current_window()
        key = str(params['key'])
        mode = str(params.get('mode', 'foreground'))
        if self.dry_run:
            return {'executed': False, 'dry_run': True, 'key': key, 'mode': mode}
        if mode == 'background':
            self.keyboard.background_press(window.hwnd, key)
        else:
            self.keyboard.press(key)
        return {'executed': True, 'dry_run': False, 'key': key, 'mode': mode}

    def _keyboard_hotkey(self, params: dict[str, Any]) -> dict[str, Any]:
        window = self._current_window()
        keys = [str(key) for key in params['keys']]
        mode = str(params.get('mode', 'foreground'))
        if self.dry_run:
            return {'executed': False, 'dry_run': True, 'keys': keys, 'mode': mode}
        if mode == 'background':
            self.keyboard.background_press_combination(window.hwnd, *keys)
        else:
            self.keyboard.press_combination(*keys)
        return {'executed': True, 'dry_run': False, 'keys': keys, 'mode': mode}

    def _keyboard_type_text(self, params: dict[str, Any]) -> dict[str, Any]:
        window = self._current_window()
        text = str(params.get('text', ''))
        mode = str(params.get('mode', 'foreground'))
        if self.dry_run:
            return {'executed': False, 'dry_run': True, 'text': text, 'mode': mode}
        if mode == 'background':
            for character in text:
                win32gui.SendMessage(window.hwnd, win32con.WM_CHAR, ord(character), 0)
        else:
            import win32clipboard
            win32gui.ShowWindow(window.hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(window.hwnd)
            previous = None
            try:
                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        previous = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
                finally:
                    win32clipboard.CloseClipboard()
                self.keyboard.press_combination('ctrl', 'v')
            finally:
                if previous is not None:
                    time.sleep(0.05)
                    win32clipboard.OpenClipboard()
                    try:
                        win32clipboard.EmptyClipboard()
                        win32clipboard.SetClipboardText(previous, win32con.CF_UNICODETEXT)
                    finally:
                        win32clipboard.CloseClipboard()
        return {'executed': True, 'dry_run': False, 'text': text, 'mode': mode}

    def _storage_read_json(self, params: dict[str, Any]) -> Any:
        path = self._data_path(str(params['path']))
        if not path.exists():
            return params.get('default')
        import json
        return json.loads(path.read_text(encoding='utf-8'))

    def _storage_write_json(self, params: dict[str, Any]) -> dict[str, Any]:
        import json
        path = self._data_path(str(params['path']))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(params.get('value'), ensure_ascii=False, indent=2), encoding='utf-8')
        return {'path': str(path)}
