"""Unified foreground/background keyboard and mouse automation feature."""

import json
import time
from pathlib import Path
from threading import Event

import win32con
import win32gui
from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from core.winhandler import WindowHandler
from core.winoperator import Win32Mouse
from automation.input_coordinator import GLOBAL_FOREGROUND_INPUT
from automation.services import AutomationHost
from feature.window_key_feature import WindowKeyWorker


CONFIG_FILE = Path('data/window_key_config.json')
DEFAULT_PROFILE_NAME = '默认方案'
DEFAULT_PROFILE = {
    'action_mode': 'key',
    'execution_mode': 'foreground',
    'key_combination': 'space',
    'delay_between_keys': 0.1,
    'loop_interval': 5.0,
    'mouse_x': 0,
    'mouse_y': 0,
    'mouse_button': 'left',
    'mouse_clicks': 1,
    'mouse_interval': 0.1,
}


def _show_window_preview(preview: QLabel, detail: QLabel, info: dict | None) -> None:
    """Show one bounded, on-demand portrait capture without activating the window."""
    preview.clear()
    if not info:
        preview.setText('选择窗口后显示人物预览')
        detail.clear()
        return
    hwnd = info['hwnd']
    detail.setText(
        f"{info.get('title', '窗口')} #{info.get('number', 1)}\n"
        f"PID {info.get('pid', 0)} · HWND {hwnd}"
    )
    try:
        if not win32gui.IsWindow(hwnd):
            raise RuntimeError('窗口已关闭，请重新添加')
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        frame = WindowHandler._capture_window_preview(hwnd, right - left, bottom - top)
        image = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0],
                       QImage.Format_RGB888).copy()
        preview.setPixmap(QPixmap.fromImage(image).scaled(
            preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
    except Exception as error:
        preview.setText(f'预览失败\n{error}')


class AutomationWindowDialog(QDialog):
    """Select windows by clicking rows; current-row focus is not a checkbox."""

    def __init__(self, candidates: list[dict], existing: set[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle('添加自动操作窗口')
        self.resize(880, 500)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('点击窗口即可选择；按 Ctrl/Shift 可多选。右侧预览用于确认角色。'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('筛选窗口标题或 PID，例如 QQ三国')
        layout.addWidget(self.search)
        content = QHBoxLayout()
        self.choices = QListWidget()
        self.choices.setSelectionMode(QListWidget.ExtendedSelection)
        content.addWidget(self.choices, 3)
        preview_layout = QVBoxLayout()
        self.preview = QLabel('选择窗口后显示人物预览')
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(320, 220)
        self.preview.setStyleSheet('background: #F7F9FC; border: 1px solid #E1E6EE;')
        preview_layout.addWidget(self.preview, 1)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        preview_layout.addWidget(self.detail)
        self.refresh = QPushButton('刷新人物预览')
        self.refresh.clicked.connect(self._update_preview)
        preview_layout.addWidget(self.refresh)
        content.addLayout(preview_layout, 2)
        layout.addLayout(content, 1)
        self.selection_label = QLabel('已选择 0 个窗口')
        layout.addWidget(self.selection_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText('添加所选窗口')
        self.buttons.button(QDialogButtonBox.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.choices.currentItemChanged.connect(self._update_preview)
        self.choices.itemSelectionChanged.connect(self._selection_changed)
        self.search.textChanged.connect(self._filter)
        for info in candidates:
            item = QListWidgetItem(AutomationFeature._window_text(info))
            item.setData(Qt.UserRole, info)
            self.choices.addItem(item)
            if info['hwnd'] in existing:
                item.setSelected(True)
        self._selection_changed()

    def selected_windows(self) -> list[dict]:
        return [item.data(Qt.UserRole) for item in self.choices.selectedItems() if not item.isHidden()]

    def _selection_changed(self) -> None:
        count = len(self.selected_windows())
        self.selection_label.setText(f'已选择 {count} 个窗口')
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(count > 0)

    def _filter(self, text: str) -> None:
        keyword = text.casefold().strip()
        for index in range(self.choices.count()):
            item = self.choices.item(index)
            hidden = keyword not in item.text().casefold()
            item.setHidden(hidden)
            if hidden:
                item.setSelected(False)
        self._selection_changed()
        self._update_preview()

    def _update_preview(self, *_args) -> None:
        item = self.choices.currentItem()
        info = item.data(Qt.UserRole) if item is not None and not item.isHidden() else None
        _show_window_preview(self.preview, self.detail, info)

    def accept(self) -> None:
        if not self.selected_windows():
            self.selection_label.setText('请先点击选择至少一个窗口')
            return
        super().accept()


def _normalise_profile(value):
    source = value if isinstance(value, dict) else {}
    result = dict(DEFAULT_PROFILE)
    result.update({key: source[key] for key in DEFAULT_PROFILE if key in source})
    # Keep profiles from the old window-key feature working.
    if 'background_mode' in source and 'execution_mode' not in source:
        result['execution_mode'] = 'background' if source['background_mode'] else 'foreground'
    result['action_mode'] = result['action_mode'] if result['action_mode'] in ('key', 'mouse') else 'key'
    result['execution_mode'] = result['execution_mode'] if result['execution_mode'] in ('foreground', 'background') else 'foreground'
    result['key_combination'] = str(result['key_combination'] or 'space')
    for key, low, high, fallback in (
        ('delay_between_keys', 0.0, 5.0, 0.1),
        ('loop_interval', 0.1, 300.0, 5.0),
        ('mouse_interval', 0.01, 10.0, 0.1),
    ):
        try:
            result[key] = min(high, max(low, float(result[key])))
        except (TypeError, ValueError):
            result[key] = fallback
    for key in ('mouse_x', 'mouse_y'):
        try:
            result[key] = int(result[key])
        except (TypeError, ValueError):
            result[key] = 0
    try:
        result['mouse_clicks'] = min(99, max(1, int(result['mouse_clicks'])))
    except (TypeError, ValueError):
        result['mouse_clicks'] = 1
    if result['mouse_button'] not in ('left', 'right', 'middle'):
        result['mouse_button'] = 'left'
    return result


class MouseAutomationWorker(QThread):
    status_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    _BUTTONS = {
        'left': (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON),
        'right': (win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP, win32con.MK_RBUTTON),
        'middle': (win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP, win32con.MK_MBUTTON),
    }

    def __init__(self, hwnd, x, y, button, clicks, click_interval, loop_interval, background):
        super().__init__()
        self.hwnd = hwnd
        self.client_x = int(x)
        self.client_y = int(y)
        self.button = button
        self.clicks = int(clicks)
        self.click_interval = float(click_interval)
        self.loop_interval = float(loop_interval)
        self.background = bool(background)
        self.running = False
        self._mouse = Win32Mouse()

    @staticmethod
    def _client_lparam(x, y):
        return (int(y) << 16) | (int(x) & 0xFFFF)

    def _background_click(self):
        down, up, wparam = self._BUTTONS[self.button]
        lparam = self._client_lparam(self.client_x, self.client_y)
        win32gui.PostMessage(self.hwnd, down, wparam, lparam)
        win32gui.PostMessage(self.hwnd, up, 0, lparam)

    def _foreground_click(self):
        point = win32gui.ClientToScreen(self.hwnd, (self.client_x, self.client_y))
        self._mouse.click(point[0], point[1], self.button)

    def run(self):
        self.running = True
        try:
            cycle = 0
            while self.running:
                cycle += 1
                if not self.background:
                    win32gui.SetForegroundWindow(self.hwnd)
                    time.sleep(0.05)
                for _ in range(self.clicks):
                    if not self.running:
                        break
                    if self.background:
                        self._background_click()
                    else:
                        self._foreground_click()
                    time.sleep(self.click_interval)
                self.status_updated.emit(f'第 {cycle} 轮完成，等待 {self.loop_interval:g} 秒')
                deadline = time.monotonic() + self.loop_interval
                while self.running and time.monotonic() < deadline:
                    time.sleep(min(0.1, max(0.01, deadline - time.monotonic())))
        except Exception as error:
            self.error_occurred.emit(f'鼠标操作失败: {error}')
        finally:
            self.running = False

    def stop(self):
        self.running = False


class MultiWindowAutomationWorker(QThread):
    """Execute one profile on an immutable window snapshot, with one stop flag."""

    status_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, windows: list[dict], profile: dict):
        super().__init__()
        self.windows = [dict(info) for info in windows]
        self.profile = _normalise_profile(profile)
        self._stop_event = Event()
        self.key_sequence = WindowKeyWorker._parse_key_combination(self, self.profile['key_combination'])

    def stop(self):
        self._stop_event.set()
        self.requestInterruption()

    def _wait(self, seconds: float) -> bool:
        return self._stop_event.wait(max(0.0, seconds))

    def _run_input(self, host, operation) -> None:
        """Hold the shared lock only for input, never for configurable waits."""
        def guarded():
            if self._stop_event.is_set():
                return
            host._validate_bound_window_identity()
            if self.profile['execution_mode'] == 'foreground':
                if not host._activate_bound_window():
                    raise RuntimeError('无法激活目标窗口，未发送输入')
                host._validate_bound_window_foreground()
            operation()

        if self.profile['execution_mode'] == 'foreground':
            GLOBAL_FOREGROUND_INPUT.run(guarded)
        else:
            guarded()

    @staticmethod
    def _press_keys(host, keys: list[str], background: bool) -> None:
        try:
            if background:
                if len(keys) == 1:
                    host._keyboard_press({'key': keys[0], 'mode': 'background'})
                else:
                    host._keyboard_hotkey({'keys': keys, 'mode': 'background'})
            elif len(keys) == 1:
                host.keyboard.press(keys[0])
            else:
                host.keyboard.press_combination(*keys)
        finally:
            for key in reversed(keys):
                if background:
                    host._keyboard_key_up({'key': key, 'mode': 'background'})
                else:
                    host.keyboard.release_key(key)

    def _execute_window(self, host) -> None:
        if self._stop_event.is_set():
            return
        background = self.profile['execution_mode'] == 'background'
        if self.profile['action_mode'] == 'key':
            for group in self.key_sequence:
                keys, repeat = WindowKeyWorker._normalise_group(group)
                for _ in range(repeat):
                    if self._stop_event.is_set():
                        return
                    self._run_input(host, lambda: self._press_keys(host, keys, background))
                    if self._wait(self.profile['delay_between_keys']):
                        return
        else:
            for _ in range(self.profile['mouse_clicks']):
                if self._stop_event.is_set():
                    return
                params = {
                    'x': self.profile['mouse_x'], 'y': self.profile['mouse_y'],
                    'button': self.profile['mouse_button'], 'coordinate_space': 'client',
                    'mode': 'background' if background else 'foreground',
                }
                self._run_input(host, lambda: host._mouse_click(params))
                if self._wait(self.profile['mouse_interval']):
                    return

    def run(self) -> None:
        hosts = []
        try:
            # Initialize system resources in the worker, never on the GUI thread.
            for info in self.windows:
                if self._stop_event.is_set():
                    return
                try:
                    host = AutomationHost(Path.cwd(), Path.cwd(),
                                          ['window.bind', 'keyboard.foreground', 'keyboard.background',
                                           'mouse.foreground', 'mouse.background'], dry_run=False)
                    host.register_window(info)
                    hosts.append((info, host))
                except Exception as error:
                    self.error_occurred.emit(f"窗口 {info.get('title', info['hwnd'])} 初始化失败：{error}")
            cycle = 0
            while hosts and not self._stop_event.is_set():
                cycle += 1
                active = []
                for info, host in hosts:
                    if self._stop_event.is_set():
                        break
                    try:
                        self._execute_window(host)
                        active.append((info, host))
                        if not self._stop_event.is_set():
                            self.status_updated.emit(
                                f"第 {cycle} 轮：{info.get('title', '窗口')} · PID {info.get('pid', 0)} 已执行"
                            )
                    except Exception as error:
                        self.error_occurred.emit(f"窗口 {info.get('title', info['hwnd'])} 已暂停：{error}")
                hosts = active
                if hosts and not self._stop_event.is_set():
                    self.status_updated.emit(f'第 {cycle} 轮完成，{len(hosts)} 个窗口；等待下一轮')
                    self._wait(self.profile['loop_interval'])
        except Exception as error:
            self.error_occurred.emit(f'自动操作初始化失败：{error}')
        finally:
            for _, host in hosts:
                host.release_all_keys()
            self._stop_event.set()


class AutomationFeature:
    """One automation entry point for target-window keyboard and mouse input."""

    def __init__(self, parent):
        self.parent = parent
        self.group_box = None
        self.worker = None
        self.selected_hwnd = None
        self.target_windows = []
        self.is_running = False
        self._worker_error = False
        self._stop_requested = False
        self.saved_config = self._load_config()
        self._loading_profile = False

    @staticmethod
    def _load_config():
        try:
            value = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            value = {}
        raw_profiles = value.get('profiles') if isinstance(value, dict) else None
        if isinstance(raw_profiles, dict) and raw_profiles:
            profiles = {
                str(name): _normalise_profile(profile)
                for name, profile in raw_profiles.items()
                if str(name).strip()
            }
        else:
            # Migrate the previous flat window-key configuration.
            legacy = value if isinstance(value, dict) else {}
            profiles = {DEFAULT_PROFILE_NAME: _normalise_profile(legacy)}
        if not profiles:
            profiles = {DEFAULT_PROFILE_NAME: dict(DEFAULT_PROFILE)}
        active = str(value.get('active_profile') or next(iter(profiles))) if isinstance(value, dict) else DEFAULT_PROFILE_NAME
        if active not in profiles:
            active = next(iter(profiles))
        return {
            'profiles': profiles,
            'active_profile': active,
            'last_window': value.get('last_window') if isinstance(value, dict) and isinstance(value.get('last_window'), dict) else None,
        }

    def _active_profile(self):
        name = self.saved_config['active_profile']
        return self.saved_config['profiles'].setdefault(name, dict(DEFAULT_PROFILE))

    def _capture_profile(self):
        profile = self._active_profile()
        profile.update({
            'action_mode': 'mouse' if self.action_combo.currentText() == '鼠标点击' else 'key',
            'execution_mode': 'background' if self.execution_combo.currentText() == '后台' else 'foreground',
            'key_combination': self.key_input.text().strip() or 'space',
            'delay_between_keys': self.key_delay_input.value(),
            'loop_interval': self.loop_input.value(),
            'mouse_x': self.mouse_x_input.value(),
            'mouse_y': self.mouse_y_input.value(),
            'mouse_button': self.button_combo.currentData(),
            'mouse_clicks': self.mouse_clicks_input.value(),
            'mouse_interval': self.mouse_interval_input.value(),
        })
        return profile

    def _write_config(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.saved_config, ensure_ascii=False, indent=2), encoding='utf-8')

    def create_ui(self):
        self.group_box = QGroupBox('自动操作')
        layout = QVBoxLayout(self.group_box)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel('方案:'))
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(list(self.saved_config['profiles']))
        self.profile_combo.setCurrentText(self.saved_config['active_profile'])
        profile_row.addWidget(self.profile_combo, 1)
        self.save_btn = QPushButton('保存')
        self.save_btn.clicked.connect(self.save_profile)
        profile_row.addWidget(self.save_btn)
        self.save_as_btn = QPushButton('另存为')
        self.save_as_btn.clicked.connect(self.save_as_profile)
        profile_row.addWidget(self.save_as_btn)
        self.delete_btn = QPushButton('删除')
        self.delete_btn.clicked.connect(self.delete_profile)
        profile_row.addWidget(self.delete_btn)
        layout.addLayout(profile_row)
        self.profile_combo.currentTextChanged.connect(self.switch_profile)

        window_row = QHBoxLayout()
        self.choose_btn = QPushButton('添加窗口（可多选）')
        self.choose_btn.clicked.connect(self.choose_window)
        window_row.addWidget(self.choose_btn)
        self.window_label = QLabel('未选择窗口')
        window_row.addWidget(self.window_label, 1)
        self.remove_window_btn = QPushButton('移除所选')
        self.remove_window_btn.clicked.connect(self.remove_windows)
        window_row.addWidget(self.remove_window_btn)
        self.clear_windows_btn = QPushButton('清空窗口')
        self.clear_windows_btn.clicked.connect(self.clear_windows)
        window_row.addWidget(self.clear_windows_btn)
        layout.addLayout(window_row)
        self.window_list = QListWidget()
        self.window_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.window_list.setMaximumHeight(110)
        self.window_list.setToolTip('可添加多个窗口；鼠标位置以列表选中的窗口为参考，点击坐标是客户区相对坐标')
        layout.addWidget(self.window_list)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel('动作:'))
        self.action_combo = QComboBox()
        self.action_combo.addItems(['按键链', '鼠标点击'])
        self.action_combo.currentTextChanged.connect(self.update_action_ui)
        mode_row.addWidget(self.action_combo)
        mode_row.addWidget(QLabel('输入方式:'))
        self.execution_combo = QComboBox()
        self.execution_combo.addItems(['前台', '后台'])
        self.execution_combo.currentTextChanged.connect(self.save_config)
        mode_row.addWidget(self.execution_combo)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        self.key_row = QHBoxLayout()
        self.key_row.addWidget(QLabel('按键链:'))
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText('q*3->space->ctrl+a*2')
        self.key_row.addWidget(self.key_input, 1)
        self.key_row.addWidget(QLabel('重复：q*3'))
        self.key_row.addWidget(QLabel('按键间隔'))
        self.key_delay_input = QDoubleSpinBox()
        self.key_delay_input.setRange(0.0, 5.0)
        self.key_delay_input.setSingleStep(0.1)
        self.key_delay_input.setDecimals(2)
        self.key_row.addWidget(self.key_delay_input)
        layout.addLayout(self.key_row)

        self.mouse_row = QHBoxLayout()
        self.mouse_row.addWidget(QLabel('窗口坐标:'))
        self.mouse_x_input = QSpinBox()
        self.mouse_x_input.setRange(-10000, 10000)
        self.mouse_x_input.setPrefix('X ')
        self.mouse_row.addWidget(self.mouse_x_input)
        self.mouse_y_input = QSpinBox()
        self.mouse_y_input.setRange(-10000, 10000)
        self.mouse_y_input.setPrefix('Y ')
        self.mouse_row.addWidget(self.mouse_y_input)
        self.capture_pos_btn = QPushButton('读取鼠标位置')
        self.capture_pos_btn.clicked.connect(self.capture_position)
        self.mouse_row.addWidget(self.capture_pos_btn)
        self.button_combo = QComboBox()
        self.button_combo.addItem('左键', 'left')
        self.button_combo.addItem('右键', 'right')
        self.button_combo.addItem('中键', 'middle')
        self.mouse_row.addWidget(self.button_combo)
        self.mouse_row.addWidget(QLabel('每轮次数'))
        self.mouse_clicks_input = QSpinBox()
        self.mouse_clicks_input.setRange(1, 99)
        self.mouse_row.addWidget(self.mouse_clicks_input)
        self.mouse_row.addWidget(QLabel('点击间隔'))
        self.mouse_interval_input = QDoubleSpinBox()
        self.mouse_interval_input.setRange(0.01, 10.0)
        self.mouse_interval_input.setSingleStep(0.05)
        self.mouse_interval_input.setDecimals(2)
        self.mouse_row.addWidget(self.mouse_interval_input)
        layout.addLayout(self.mouse_row)

        loop_row = QHBoxLayout()
        loop_row.addWidget(QLabel('循环间隔(秒):'))
        self.loop_input = QDoubleSpinBox()
        self.loop_input.setRange(0.1, 300.0)
        self.loop_input.setSingleStep(0.5)
        self.loop_input.setDecimals(1)
        loop_row.addWidget(self.loop_input)
        loop_row.addWidget(QLabel('后台模式不会抢占鼠标和键盘焦点'))
        loop_row.addStretch()
        layout.addLayout(loop_row)

        control_row = QHBoxLayout()
        self.start_btn = QPushButton('启动 (Home)')
        self.start_btn.clicked.connect(self.toggle)
        control_row.addWidget(self.start_btn)
        self.status_label = QLabel('状态: 就绪')
        control_row.addWidget(self.status_label, 1)
        layout.addLayout(control_row)

        self.progress_display = QTextEdit()
        self.progress_display.setReadOnly(True)
        self.progress_display.setMaximumHeight(80)
        self.progress_display.document().setMaximumBlockCount(500)
        self.progress_display.setPlaceholderText('运行状态将显示在这里')
        layout.addWidget(self.progress_display)

        for widget in (self.key_input, self.key_delay_input, self.loop_input,
                       self.mouse_x_input, self.mouse_y_input, self.button_combo,
                       self.mouse_clicks_input, self.mouse_interval_input):
            if hasattr(widget, 'textChanged'):
                widget.textChanged.connect(self.save_config)
            elif hasattr(widget, 'valueChanged'):
                widget.valueChanged.connect(self.save_config)
            else:
                widget.currentTextChanged.connect(self.save_config)

        self._load_active_profile()
        last_window = self.saved_config.get('last_window')
        if isinstance(last_window, dict) and last_window.get('title'):
            self.window_label.setText(
                f"上次：{last_window['title']} #{last_window.get('number', 1)} · PID {last_window.get('pid', 0)}（请重新选择）"
            )
        self.update_action_ui()
        self.parent.left_layout.addWidget(self.group_box)

    def _load_active_profile(self):
        profile = _normalise_profile(self._active_profile())
        self._loading_profile = True
        try:
            self.action_combo.setCurrentText('鼠标点击' if profile['action_mode'] == 'mouse' else '按键链')
            self.execution_combo.setCurrentText('后台' if profile['execution_mode'] == 'background' else '前台')
            self.key_input.setText(profile['key_combination'])
            self.key_delay_input.setValue(profile['delay_between_keys'])
            self.loop_input.setValue(profile['loop_interval'])
            self.mouse_x_input.setValue(profile['mouse_x'])
            self.mouse_y_input.setValue(profile['mouse_y'])
            self.button_combo.setCurrentIndex(max(0, self.button_combo.findData(profile['mouse_button'])))
            self.mouse_clicks_input.setValue(profile['mouse_clicks'])
            self.mouse_interval_input.setValue(profile['mouse_interval'])
        finally:
            self._loading_profile = False

    def save_config(self, *_args):
        if self._loading_profile:
            return
        self._capture_profile()
        try:
            self._write_config()
        except OSError as error:
            self.status_label.setText(f'状态: 配置保存失败：{error}')

    def save_profile(self):
        self.save_config()
        self.status_label.setText(f"状态: 方案「{self.saved_config['active_profile']}」已保存")

    def save_as_profile(self):
        name, ok = QInputDialog.getText(self.group_box, '另存为方案', '方案名称:')
        name = name.strip()
        if not ok or not name:
            return
        if name in self.saved_config['profiles']:
            answer = QMessageBox.question(self.group_box, '覆盖方案', f'方案「{name}」已存在，是否覆盖？')
            if answer != QMessageBox.Yes:
                return
        self._capture_profile()
        self.saved_config['profiles'][name] = dict(self._active_profile())
        self.saved_config['active_profile'] = name
        self.profile_combo.blockSignals(True)
        try:
            if self.profile_combo.findText(name) < 0:
                self.profile_combo.addItem(name)
            self.profile_combo.setCurrentText(name)
        finally:
            self.profile_combo.blockSignals(False)
        self.save_config()
        self.status_label.setText(f'状态: 已另存为「{name}」')

    def switch_profile(self, name):
        if self._loading_profile or name not in self.saved_config['profiles']:
            return
        self._capture_profile()
        self.saved_config['active_profile'] = name
        self._load_active_profile()
        self.save_config()
        self.status_label.setText(f'状态: 已切换到「{name}」')

    def delete_profile(self):
        if len(self.saved_config['profiles']) <= 1:
            self.status_label.setText('状态: 至少保留一套方案')
            return
        name = self.saved_config['active_profile']
        if QMessageBox.question(self.group_box, '删除方案', f'确定删除方案「{name}」吗？') != QMessageBox.Yes:
            return
        del self.saved_config['profiles'][name]
        next_name = next(iter(self.saved_config['profiles']))
        self.saved_config['active_profile'] = next_name
        self.profile_combo.blockSignals(True)
        try:
            self.profile_combo.removeItem(self.profile_combo.findText(name))
            self.profile_combo.setCurrentText(next_name)
        finally:
            self.profile_combo.blockSignals(False)
        self._load_active_profile()
        self.save_config()
        self.status_label.setText(f'状态: 已删除，当前为「{next_name}」')

    def update_action_ui(self, *_args):
        is_key = self.action_combo.currentText() == '按键链'
        for index in range(self.key_row.count()):
            widget = self.key_row.itemAt(index).widget()
            if widget:
                widget.setVisible(is_key)
        for index in range(self.mouse_row.count()):
            widget = self.mouse_row.itemAt(index).widget()
            if widget:
                widget.setVisible(not is_key)
        self.save_config()

    def choose_window(self):
        if self.is_running:
            return
        handler = WindowHandler()
        candidates = handler.list_window_candidates()
        if not candidates:
            self.status_label.setText('状态: 没有找到可选窗口')
            return
        existing = {info['hwnd'] for info in self.target_windows}
        dialog = AutomationWindowDialog(candidates, existing, self.group_box)
        try:
            if dialog.exec_() != QDialog.Accepted:
                return
            selected = dialog.selected_windows()
        finally:
            # Parent-owned dialogs otherwise retain their screenshot pixmap on every reopen.
            dialog.deleteLater()
        before = len(self.target_windows)
        self._add_windows(selected)
        added = len(self.target_windows) - before
        self.status_label.setText(f'状态: 本次新增 {added} 个窗口，共 {len(self.target_windows)} 个')

    @staticmethod
    def _window_text(info: dict) -> str:
        return f"{info.get('title', '窗口')} #{info.get('number', 1)} · PID {info.get('pid', 0)}"

    def _add_windows(self, windows: list[dict]) -> None:
        existing = {info['hwnd'] for info in self.target_windows}
        for info in windows:
            if info['hwnd'] in existing:
                continue
            self.target_windows.append({key: info[key] for key in ('hwnd', 'pid', 'title', 'number') if key in info})
            existing.add(info['hwnd'])
        self._refresh_windows()
        if self.target_windows:
            info = self.target_windows[0]
            self.saved_config['last_window'] = {key: info.get(key, '') for key in ('title', 'pid', 'number')}
            self.save_config()

    def _refresh_windows(self) -> None:
        self.window_list.clear()
        for info in self.target_windows:
            item = QListWidgetItem(self._window_text(info))
            item.setData(Qt.UserRole, info['hwnd'])
            self.window_list.addItem(item)
        self.selected_hwnd = self.target_windows[0]['hwnd'] if self.target_windows else None
        if self.target_windows:
            self.window_list.setCurrentRow(0)
        self.window_label.setText(f'已添加 {len(self.target_windows)} 个窗口')
        self.status_label.setText('状态: 窗口列表已更新')

    def remove_windows(self) -> None:
        if self.is_running:
            return
        removed = {item.data(Qt.UserRole) for item in self.window_list.selectedItems()}
        self.target_windows = [info for info in self.target_windows if info['hwnd'] not in removed]
        self._refresh_windows()

    def clear_windows(self) -> None:
        if self.is_running:
            return
        self.target_windows = []
        self._refresh_windows()

    def capture_position(self):
        if self.is_running:
            return
        item = self.window_list.currentItem()
        reference_hwnd = item.data(Qt.UserRole) if item is not None else self.selected_hwnd
        if not reference_hwnd or not win32gui.IsWindow(reference_hwnd):
            self.status_label.setText('状态: 请先选择目标窗口')
            return
        screen_x, screen_y = Win32Mouse().get_cursor_pos()
        client_x, client_y = win32gui.ScreenToClient(reference_hwnd, (screen_x, screen_y))
        self.mouse_x_input.setValue(client_x)
        self.mouse_y_input.setValue(client_y)
        self.status_label.setText(f'状态: 已读取窗口坐标 ({client_x}, {client_y})')

    def toggle(self):
        self.stop() if self.is_running else self.start()

    def start(self):
        if self.is_running:
            return
        if self.worker is not None and self.worker.isRunning():
            self.status_label.setText('状态: 正在停止，请稍候')
            return
        windows = [info for info in self.target_windows if win32gui.IsWindow(info['hwnd'])]
        if not windows:
            self.status_label.setText('状态: 请先添加有效窗口')
            return
        self.save_config()
        profile = self._capture_profile()
        self._worker_error = False
        self._stop_requested = False
        background = profile['execution_mode'] == 'background'
        self.worker = MultiWindowAutomationWorker(windows, profile)
        self.worker.status_updated.connect(self.on_status)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.finished.connect(lambda worker=self.worker: self._worker_finished(worker))
        self.is_running = True
        self._set_editing_enabled(False)
        self.start_btn.setText('停止 (Home)')
        self.status_label.setText('状态: 执行中')
        self.progress_display.append(f"启动：{len(windows)} 个窗口 / {'按键链' if profile['action_mode'] == 'key' else '鼠标点击'} / {'后台' if background else '前台'}")
        if hasattr(self.parent, 'hotkey_status_label'):
            self.parent.hotkey_status_label.setText('▶ 自动操作 - 运行中')
        self.worker.start()

    def stop(self):
        self._stop_requested = True
        if self.worker:
            self.worker.stop()
            if not self.worker.wait(2000):
                self.start_btn.setText('正在停止…')
                self.start_btn.setEnabled(False)
                self.status_label.setText('状态: 正在停止，当前输入返回后结束')
                return
        self.is_running = False
        self.start_btn.setEnabled(True)
        self._set_editing_enabled(True)
        self.start_btn.setText('启动 (Home)')
        self.status_label.setText('状态: 已停止')
        if hasattr(self.parent, 'hotkey_status_label'):
            self.parent.hotkey_status_label.setText('○ 自动操作 - 停止')

    def _worker_finished(self, worker=None):
        if worker is not None and worker is not self.worker:
            return
        self.is_running = False
        self.start_btn.setEnabled(True)
        self._set_editing_enabled(True)
        self.start_btn.setText('启动 (Home)')
        state = '已停止' if self._stop_requested else ('执行出错' if self._worker_error else '已完成')
        self.status_label.setText(f'状态: {state}')
        if hasattr(self.parent, 'hotkey_status_label'):
            self.parent.hotkey_status_label.setText(f'○ 自动操作 - {state}')

    def _set_editing_enabled(self, enabled: bool) -> None:
        for widget in (self.choose_btn, self.remove_window_btn, self.clear_windows_btn,
                       self.profile_combo, self.save_btn, self.save_as_btn, self.delete_btn,
                       self.action_combo, self.execution_combo, self.key_input, self.key_delay_input,
                       self.mouse_x_input, self.mouse_y_input, self.capture_pos_btn,
                       self.button_combo, self.mouse_clicks_input, self.mouse_interval_input, self.loop_input):
            widget.setEnabled(enabled)

    def on_status(self, status):
        self.status_label.setText(f'状态: {status}')
        self.progress_display.append(status)

    def on_error(self, error):
        self._worker_error = True
        self.status_label.setText('状态: 执行出错')
        self.progress_display.append(f'错误: {error}')
