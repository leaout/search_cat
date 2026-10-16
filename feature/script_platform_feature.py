import json
import re
import shutil
import time
from copy import deepcopy
from pathlib import Path
from threading import Event

import cv2
import win32gui
import win32process
from PyQt5.QtCore import QThread, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QTextCursor, QTextOption
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox, QHBoxLayout,
                             QLabel, QListWidget, QListWidgetItem, QLineEdit, QMessageBox,
                             QPushButton, QSizePolicy, QSplitter, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout,
                             QWidget)

from automation.services import AutomationHost
from core.winhandler import WindowHandler
from core.text import repair_utf8_gbk_mojibake
from core.window_titles import is_qqsg_game_window_title
from plugin_platform.manager import PluginManager, PluginManifest
from plugin_platform.qqsg_data import (QQSGPackage, find_installation, import_routes,
                                       parse_map_catalog)
from plugin_platform.runner import PluginProcess
from plugin_platform.line_grid import find_line_target, infer_server_menu_button
from plugin_platform.qqsg_pickaxe_shop import purchase_session_key


class ScalablePreviewLabel(QLabel):
    """Preview viewport whose source image never affects layout sizing."""

    def __init__(self, placeholder: str):
        super().__init__(placeholder)
        self._source_pixmap = QPixmap()

    def show_image(self, image: QImage):
        self._source_pixmap = QPixmap.fromImage(image)
        self.setText('')
        self._fit_image()

    def clear_image(self, placeholder: str):
        self._source_pixmap = QPixmap()
        super().setPixmap(QPixmap())
        self.setText(placeholder)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_image()

    def _fit_image(self):
        if self._source_pixmap.isNull():
            return
        target_size = self.contentsRect().size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            return
        super().setPixmap(self._source_pixmap.scaled(
            target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        ))


class BatchLineSwitchWorker(QThread):
    """Switch several QQ 三国 windows one at a time using the game UI."""

    log_received = pyqtSignal(str, str)
    finished_result = pyqtSignal(int, int)

    def __init__(self, manager: PluginManager, windows: list[dict], target_line: int,
                 dry_run: bool, max_attempts: int = 20, parent=None):
        super().__init__(parent)
        self._stop_event = Event()
        self.manager = manager
        self.windows = [dict(item) for item in windows]
        self.target_line = int(target_line)
        self.dry_run = bool(dry_run)
        # A full line is expected while "挤线".  Keep retrying the same
        # window instead of counting a click/submit as a successful switch.
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay = 0.20
        self.menu_wait = 0.15
        self.selector_wait = 0.20
        self.verify_timeout = 2.40

    def requestInterruption(self):
        # Qt clears its interruption flag after run() exits. Keep the user's
        # stop request until the queued completion signal is handled by the UI.
        self._stop_event.set()
        super().requestInterruption()

    def isInterruptionRequested(self):
        return self._stop_event.is_set() or super().isInterruptionRequested()

    def _check_stop(self):
        if self.isInterruptionRequested():
            raise InterruptedError('收到停止请求')

    def _wait(self, seconds: float):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._check_stop()
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        self._check_stop()

    @staticmethod
    def _compact(text: str) -> str:
        return re.sub(r'\s+', '', str(text or '')).replace('：', ':')

    @staticmethod
    def _item_center(item: dict) -> tuple[int, int] | None:
        center = item.get('center')
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            return int(center[0]), int(center[1])
        box = item.get('box')
        if isinstance(box, (list, tuple)) and box:
            points = [point for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
            if points:
                return (
                    int(sum(float(point[0]) for point in points) / len(points)),
                    int(sum(float(point[1]) for point in points) / len(points)),
                )
        return None

    def _emit_log(self, info: dict, message: str):
        session_id = str(info.get('id') or f"hwnd-{info.get('hwnd', 0)}")
        self.log_received.emit(session_id, f'[批量换线] {message}')

    @staticmethod
    def _window_title(info: dict) -> str:
        """Read the live native title; the stored binding title is stale after a line switch."""
        hwnd = int(info.get('hwnd') or 0)
        if hwnd:
            try:
                if win32gui.IsWindow(hwnd):
                    title = str(win32gui.GetWindowText(hwnd) or '')
                    if title:
                        return title
            except (OSError, TypeError, ValueError):
                pass
        return str(info.get('title') or info.get('id') or '')

    @classmethod
    def _window_state(cls, info: dict) -> tuple[int | None, str]:
        title = cls._window_title(info)
        # QQ 三国 titles end in e.g. "7线".  Restrict the match to a line
        # suffix so a build number or a character level is not mistaken for it.
        matches = re.findall(r'(?<!\d)(\d{1,3})\s*[线線](?!\d)', title)
        return (int(matches[-1]) if matches else None), title

    def _wait_for_target_line(self, info: dict) -> tuple[bool, str, int | None]:
        """Wait until the native title confirms the requested line."""
        deadline = time.monotonic() + self.verify_timeout
        last_title = self._window_title(info)
        last_line, _ = self._window_state(info)
        while time.monotonic() < deadline:
            line, title = self._window_state(info)
            last_line, last_title = line, title
            if line == self.target_line:
                return True, title, line
            self._wait(0.12)
        return False, last_title, last_line

    @staticmethod
    def _capture_items(host: AutomationHost, include_yellow: bool = False) -> list[dict]:
        frame = host.dispatch('capture.window', {'mode': 'auto', 'area': 'client'})
        try:
            base_items = list(host.dispatch('ocr.recognize', {
                'frame_id': frame['id'],
                'min_confidence': 0.35,
                'preprocess': 'none',
            }) or [])
            # Only enlarge/mask the screen if the normal pass cannot locate
            # the control. Full-screen enhanced OCR is expensive.
            yellow_items = []
            if include_yellow:
                try:
                    yellow_items = list(host.dispatch('ocr.recognize', {
                        'frame_id': frame['id'],
                        'min_confidence': 0.30,
                        'preprocess': 'task_yellow',
                    }) or [])
                except InterruptedError:
                    raise
                except Exception:
                    yellow_items = []
            merged = []
            seen = set()
            for item in base_items + yellow_items:
                text = BatchLineSwitchWorker._compact(item.get('text', ''))
                center = BatchLineSwitchWorker._item_center(item)
                key = (text, center)
                if not text or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
            for item in merged:
                item['_frame_width'] = int(frame.get('width', 0))
                item['_frame_height'] = int(frame.get('height', 0))
            return merged
        finally:
            host.clear_frames()

    @classmethod
    def _find_server_button(cls, items: list[dict]) -> dict | None:
        candidates = []
        for item in items:
            text = cls._compact(item.get('text', ''))
            if not text or '客服' in text:
                continue
            score = 0
            if '服务器选线' in text:
                score = 4
            elif '服务器' in text and '选线' in text:
                score = 3
            elif text in {'选线', '服务器'}:
                score = 2
            if score and cls._item_center(item):
                candidates.append((score, item))
        return (max(candidates, key=lambda value: value[0])[1] if candidates
                else infer_server_menu_button(items, cls._item_center))

    @classmethod
    def _find_target_line(cls, items: list[dict], target_line: int) -> dict | None:
        return find_line_target(items, target_line, cls._item_center)

    @classmethod
    def _available_lines(cls, items: list[dict]) -> list[int]:
        """Return line numbers visible in the current server selector."""
        found = set()
        pattern = re.compile(r'(?<!\d)(\d{1,2})\s*(?:线|号线|线路)')
        for item in items:
            text = cls._compact(item.get('text', ''))
            for match in pattern.finditer(text):
                found.add(int(match.group(1)))
            if text.isdigit() and 1 <= int(text) <= 99:
                found.add(int(text))
        return sorted(found)

    @classmethod
    def _find_confirm(cls, items: list[dict]) -> dict | None:
        preferred = ('确定', '确认', '进入游戏', '换线')
        candidates = []
        for item in items:
            text = cls._compact(item.get('text', ''))
            center = cls._item_center(item)
            if not text or not center:
                continue
            for rank, keyword in enumerate(preferred):
                if keyword in text:
                    candidates.append((rank, len(text), item))
                    break
        if not candidates:
            return None
        return min(candidates, key=lambda value: (value[0], value[1]))[2]

    @classmethod
    def _is_switch_blocker(cls, items: list[dict]) -> bool:
        """Detect QQSG's map-restriction dialog.

        When a character is still in a map that disallows server switching,
        the game shows a modal message such as “当前在副本地图中，不能切换
        服务器”.  Esc does not dismiss this modal reliably, so it must be
        acknowledged before another挤线 attempt can start.
        """
        texts = [cls._compact(item.get('text', '')) for item in items]
        blocker = any(
            ('不能切换' in text)
            or ('无法切换' in text)
            or any(word in text for word in ('服务器已满', '线路已满', '人数已满', '换线失败'))
            or ('当前在' in text and ('地图' in text or '服务器' in text))
            or ('副本地图' in text)
            for text in texts
        )
        return blocker

    @classmethod
    def _find_switch_blocker(cls, items: list[dict]) -> dict | None:
        """Return the modal's acknowledgement button, if OCR found it."""
        if not cls._is_switch_blocker(items):
            return None
        # Do not use the generic “换线” match here: the blocked modal can
        # leave the server menu visible behind it. Only click the modal's own
        # acknowledgement label; otherwise the Enter fallback is safer.
        candidates = []
        for item in items:
            text = cls._compact(item.get('text', ''))
            if ('确定' in text or '确认' in text) and cls._item_center(item):
                candidates.append((len(text), item))
        return min(candidates, key=lambda value: value[0])[1] if candidates else None

    def _click_item(self, host: AutomationHost, item: dict):
        center = self._item_center(item)
        if center is None:
            raise RuntimeError('OCR 项目没有可点击坐标')
        host.dispatch('mouse.click', {
            'x': center[0],
            'y': center[1],
            'button': 'left',
            'mode': 'foreground',
            'coordinate_space': 'client',
        })
        # The QQSG cursor is rendered as a large hand and can cover the next
        # line label (especially the 14-line row). Keep it away before OCR.
        host.dispatch('mouse.move', {
            'x': 8, 'y': 8, 'duration': 0,
            'coordinate_space': 'client',
        })

    def _open_server_menu(self, host: AutomationHost, info: dict) -> dict:
        """Bring the system menu to a known state and find its line-switch button."""
        # A previous failed attempt may have left either the line selector or
        # a confirmation panel open.  Inspect first, then use Esc at most
        # three times (selector -> system menu -> game) until the button is
        # visible.  This avoids blind Esc presses on retries.
        host.dispatch('keyboard.press', {'key': 'esc', 'mode': 'foreground'})
        self._wait(self.menu_wait)
        for attempt in range(3):
            menu_items = self._capture_items(host)
            if self._is_switch_blocker(menu_items):
                self._emit_log(info, '检测到换线失败提示，点击确定后继续')
                blocker = self._find_switch_blocker(menu_items)
                if blocker is not None:
                    self._click_item(host, blocker)
                else:
                    # The message text can be recognized while the small
                    # button is missed. The modal owns focus, so Enter is a
                    # safe fallback acknowledgement.
                    host.dispatch('keyboard.press', {'key': 'enter', 'mode': 'foreground'})
                self._wait(self.menu_wait)
                continue
            server_button = self._find_server_button(menu_items)
            if server_button is None:
                menu_items = self._capture_items(host, include_yellow=True)
                server_button = self._find_server_button(menu_items)
            if server_button is not None:
                return server_button
            if attempt < 2:
                host.dispatch('keyboard.press', {'key': 'esc', 'mode': 'foreground'})
                self._wait(self.menu_wait)
        raise RuntimeError('未识别到“服务器选线/选线”按钮')

    def _switch_one_once(self, host: AutomationHost, info: dict):
        title = str(info.get('title') or info.get('id') or '游戏窗口')
        self._emit_log(info, f'{title}：激活窗口并打开系统菜单')
        host.register_window(info)
        host.dispatch('window.activate', {})
        host.dispatch('mouse.move', {
            'x': 8, 'y': 8, 'duration': 0,
            'coordinate_space': 'client',
        })
        server_button = self._open_server_menu(host, info)
        self._emit_log(info, f'点击换线入口：{server_button.get("text", "") or "服务器选线"}')
        self._click_item(host, server_button)
        self._wait(self.selector_wait)
        line_items = self._capture_items(host)
        target = self._find_target_line(line_items, self.target_line)
        if target is None:
            line_items = self._capture_items(host, include_yellow=True)
            target = self._find_target_line(line_items, self.target_line)
        if target is None:
            available = self._available_lines(line_items)
            available_text = '、'.join(f'{line}线' for line in available) if available else '无'
            diagnostics = [f'{item.get("text", "")}@{self._item_center(item)}'
                           for item in line_items if re.search(r'\d\s*线', str(item.get('text', '')))]
            self._emit_log(info, '线路定位诊断：' + ' / '.join(diagnostics[:20]))
            raise RuntimeError(
                f'当前选线窗口没有识别到目标线路：{self.target_line}线；'
                f'当前可见线路：{available_text}。请确认该线路已开放。'
            )
        if target.get('_grid_fallback'):
            self._emit_log(info, f'未直接识别到 {self.target_line} 线，按选线网格定位点击')
        self._emit_log(info, f'点击目标线路：{target.get("text", "") or f"{self.target_line}线"}')
        # Selecting a line does not move the panel or its confirm button.
        # Reuse this observation instead of paying for another full OCR pass.
        confirm = self._find_confirm(line_items)
        self._click_item(host, target)
        self._wait(0.08)
        if confirm is None:
            confirm = self._find_confirm(self._capture_items(host))
        if confirm is not None:
            self._emit_log(info, f'点击确认：{confirm.get("text", "") or "确定"}')
            self._click_item(host, confirm)
        else:
            self._emit_log(info, '未发现确认按钮，按回车提交换线')
            host.dispatch('keyboard.press', {'key': 'enter', 'mode': 'foreground'})
        self._emit_log(info, f'已提交换线到 {self.target_line} 线')

        verified, live_title, live_line = self._wait_for_target_line(info)
        if not verified:
            current = live_title or '标题为空'
            line_text = f'{live_line}线' if live_line is not None else '未读到线路号'
            raise RuntimeError(
                f'提交后窗口标题仍为“{current}”（{line_text}），未确认切换到 {self.target_line}线'
            )
        self._emit_log(info, f'窗口标题已确认：{live_title}，当前为 {self.target_line}线')

    def _switch_one(self, host: AutomationHost, info: dict):
        current_line, current_title = self._window_state(info)
        if current_line == self.target_line:
            self._emit_log(info, f'窗口标题已显示 {self.target_line}线，无需重复换线')
            return

        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            if self.isInterruptionRequested():
                raise InterruptedError('收到停止请求')
            if attempt > 1:
                current_line, current_title = self._window_state(info)
                if current_line == self.target_line:
                    self._emit_log(info, f'窗口标题已确认 {self.target_line}线，结束重试')
                    return
                line_text = f'{current_line}线' if current_line is not None else '未读到线路号'
                self._emit_log(
                    info,
                    f'第 {attempt}/{self.max_attempts} 次重试，标题当前为“{current_title or "空"}”（{line_text}）',
                )
            try:
                self._switch_one_once(host, info)
                return
            except InterruptedError:
                raise
            except Exception as error:
                self._check_stop()
                last_error = error
                if attempt >= self.max_attempts:
                    break
                self._emit_log(info, f'第 {attempt} 次未确认成功：{error}；{self.retry_delay:.2f}s 后重试')
                # Close a possibly leftover selector/confirmation before the
                # next attempt. _open_server_menu will inspect and normalize
                # the state again, so this remains safe for either screen.
                try:
                    host.dispatch('keyboard.press', {'key': 'esc', 'mode': 'foreground'})
                except Exception:
                    pass
                self._wait(self.retry_delay)
        raise RuntimeError(f'{self.max_attempts} 次尝试后仍未确认切换到 {self.target_line}线：{last_error}')

    def run(self):
        if not self.windows:
            self.finished_result.emit(0, 0)
            return
        if self.dry_run:
            for info in self.windows:
                self._emit_log(info, f'模拟运行：将打开服务器选线并切换到 {self.target_line} 线')
            self.finished_result.emit(len(self.windows), 0)
            return

        data_directory = self.manager.plugin_data_directory('com.searchcat.batch-switch-line')
        host = AutomationHost(
            self.manager.plugins_directory,
            data_directory,
            permissions=['window.bind', 'screen.capture', 'mouse.foreground', 'keyboard.foreground'],
            dry_run=False,
            session_id='batch-switch-line',
        )
        dispatch = host.dispatch

        def cancellable_dispatch(method, params):
            self._check_stop()
            result = dispatch(method, params)
            self._check_stop()
            return result

        host.dispatch = cancellable_dispatch
        success = 0
        failed = 0
        for info in self.windows:
            if self.isInterruptionRequested():
                self._emit_log(info, '收到停止请求，后续窗口不再换线')
                break
            try:
                self._switch_one(host, info)
                success += 1
            except InterruptedError:
                self._emit_log(info, '已停止换线，后续窗口不再操作')
                break
            except Exception as error:
                failed += 1
                self._emit_log(info, f'换线失败：{error}')
            finally:
                host.release_all_keys()
                host.clear_frames()
        self.finished_result.emit(success, failed)


class ScriptPlatformFeature:
    """Plugin discovery, configuration, window binding, and runtime UI."""

    def __init__(self, parent):
        self.parent = parent
        self.manager = PluginManager()
        self.manifests: list[PluginManifest] = []
        self.window_handler = WindowHandler()
        self.target_window_info = None
        self.target_windows: list[dict] = []
        self.runners: dict[str, PluginProcess] = {}
        self.session_states: dict[str, str] = {}
        self.session_logs: dict[str, list[str]] = {}
        self.session_frames: dict[str, object] = {}
        self.running = False
        self.switch_line_worker: BatchLineSwitchWorker | None = None
        self.switching_lines = False
        self.current_config: dict = {}

    def create_ui(self):
        self.group_box = QGroupBox('自动化脚本平台')
        self.group_box.setObjectName('scriptPlatformCard')
        self.group_box.setStyleSheet("""
            QGroupBox#scriptPlatformCard QPushButton {
                min-height: 28px;
                max-height: 28px;
                padding: 0 9px;
                border-radius: 4px;
                font-size: 12px;
            }
            QGroupBox#scriptPlatformCard QPushButton#scriptPrimaryButton {
                min-height: 30px;
                max-height: 30px;
                background: #356AE6;
                color: white;
                border: 1px solid #356AE6;
                font-weight: 600;
            }
            QGroupBox#scriptPlatformCard QPushButton#scriptPrimaryButton:hover {
                background: #285ACB;
                border-color: #285ACB;
            }
            QGroupBox#scriptPlatformCard QLabel#scriptStatus {
                min-height: 26px;
                max-height: 26px;
                padding: 0 8px;
                background: #F2F6FC;
                color: #53627A;
                border-radius: 4px;
            }
            QGroupBox#scriptPlatformCard QTextEdit {
                border-radius: 4px;
            }
            QGroupBox#scriptPlatformCard QListWidget::item {
                min-height: 40px;
                padding: 0 6px;
                border-radius: 3px;
            }
        """)
        root = QVBoxLayout(self.group_box)
        root.setContentsMargins(6, 10, 6, 6)
        root.setSpacing(6)

        list_panel = QWidget()
        list_layout = QHBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)
        list_layout.addWidget(QLabel('已安装脚本'))
        self.plugin_list = QListWidget()
        self.plugin_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.plugin_list.currentItemChanged.connect(self._display_selected_plugin)
        # Retain the existing list model/selection contract for plugin lifecycle.
        self.plugin_list.hide()
        self.plugin_combo = QComboBox()
        self.plugin_combo.setMinimumWidth(0)
        self.plugin_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.plugin_combo.setMinimumContentsLength(12)
        self.plugin_combo.setModel(self.plugin_list.model())
        self.plugin_combo.activated[int].connect(self.plugin_list.setCurrentRow)
        self.plugin_list.currentRowChanged.connect(self.plugin_combo.setCurrentIndex)
        list_layout.addWidget(self.plugin_combo, 1)
        install_layout = QHBoxLayout()
        install_directory_btn = QPushButton('目录安装')
        install_directory_btn.clicked.connect(self.install_directory)
        install_zip_btn = QPushButton('ZIP 安装')
        install_zip_btn.clicked.connect(self.install_zip)
        refresh_btn = QPushButton('刷新')
        refresh_btn.clicked.connect(self.refresh_plugins)
        install_layout.addWidget(install_directory_btn)
        install_layout.addWidget(install_zip_btn)
        install_layout.addWidget(refresh_btn)
        list_layout.addLayout(install_layout)
        root.addWidget(list_panel)

        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(6)
        self.plugin_title = QLabel('请选择一个脚本')
        self.plugin_title.setObjectName('sectionTitle')
        self.plugin_description = QLabel('插件将在独立 Python 子进程中运行。')
        self.plugin_description.setWordWrap(True)
        self.plugin_description.setObjectName('sectionHint')
        self.plugin_description.setMaximumHeight(44)
        control_layout.addWidget(self.plugin_title)
        control_layout.addWidget(self.plugin_description)

        self.template_panel = QWidget()
        self.template_layout = QHBoxLayout(self.template_panel)
        self.template_layout.setContentsMargins(0, 0, 0, 0)
        self.template_layout.setSpacing(6)
        self.template_status = QLabel('识别模板：无需配置')
        self.template_layout.addWidget(self.template_status)
        self.template_layout.addStretch(1)
        control_layout.addWidget(self.template_panel)

        self.qqsg_data_panel = QWidget()
        qqsg_data_layout = QVBoxLayout(self.qqsg_data_panel)
        qqsg_data_layout.setContentsMargins(0, 0, 0, 0)
        qqsg_data_layout.setSpacing(4)
        self.qqsg_data_status = QLabel('NPC 路由库：尚未导入')
        self.qqsg_data_status.setWordWrap(True)
        self.qqsg_data_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        qqsg_data_layout.addWidget(self.qqsg_data_status)
        data_buttons = QHBoxLayout()
        data_buttons.setSpacing(4)
        qqsg_data_layout.addLayout(data_buttons)
        import_game_data_btn = QPushButton('导入游戏数据')
        import_game_data_btn.setToolTip('只读解析 QQ 三国 objects.pkg，不修改游戏文件')
        import_game_data_btn.clicked.connect(self.import_qqsg_game_data)
        select_minimap_btn = QPushButton('框选小地图')
        select_minimap_btn.setToolTip('从绑定窗口的后台截图中框选地图名称和坐标')
        select_minimap_btn.clicked.connect(self.select_qqsg_minimap_region)
        select_task_btn = QPushButton('框选任务栏')
        select_task_btn.setToolTip('从绑定窗口的后台截图中框选右侧任务文字区域')
        select_task_btn.clicked.connect(self.select_qqsg_task_region)
        data_buttons.addWidget(select_minimap_btn)
        data_buttons.addWidget(select_task_btn)
        data_buttons.addWidget(import_game_data_btn)
        map_debug_btn = QPushButton('地图调试')
        map_debug_btn.clicked.connect(self.open_map_debug)
        data_buttons.addWidget(map_debug_btn)
        map_list_btn = QPushButton('查看地图数据')
        map_list_btn.setToolTip('显示从 QQ 三国 objects.pkg 解析出的全部地图')
        map_list_btn.clicked.connect(self.show_parsed_maps)
        data_buttons.addWidget(map_list_btn)
        data_buttons.addStretch(1)
        self.qqsg_data_panel.setVisible(False)
        control_layout.addWidget(self.qqsg_data_panel)

        # The question dialog has its own region and must not reuse the task
        # sidebar region. Keep this on a separate row at normal window width.
        self.daily_region_panel = QWidget()
        daily_region_layout = QHBoxLayout(self.daily_region_panel)
        daily_region_layout.setContentsMargins(0, 0, 0, 0)
        daily_region_layout.setSpacing(6)
        daily_region_layout.addWidget(QLabel('举孝廉识别区域：'))
        select_answer_btn = QPushButton('框选答题窗口')
        select_answer_btn.setToolTip('从绑定窗口客户区截图中框选完整的题目、选项和倒计时区域')
        select_answer_btn.clicked.connect(self.select_qqsg_answer_region)
        daily_region_layout.addWidget(select_answer_btn)
        daily_region_layout.addWidget(QLabel('也可在“配置”中编辑 answer_region'))
        daily_region_layout.addStretch(1)
        self.daily_region_panel.setVisible(False)
        control_layout.addWidget(self.daily_region_panel)

        self.mining_region_panel = QWidget()
        mining_region_layout = QHBoxLayout(self.mining_region_panel)
        mining_region_layout.setContentsMargins(0, 0, 0, 0)
        mining_region_layout.setSpacing(6)
        mining_region_layout.addWidget(QLabel('采集管理区域：'))
        for text, key, title, label in (
            ('框选矿锄状态', 'pickaxe_region', 'Select pickaxe status', '矿锄状态'),
            ('框选背包物品', 'pickaxe_inventory_region', 'Select inventory slots', '背包物品'),
            ('框选名称提示', 'pickaxe_tooltip_region', 'Select pickaxe tooltip area', '矿锄名称提示'),
        ):
            button = QPushButton(text)
            button.setToolTip('先在游戏中展示对应区域，再框选客户区截图；区域保存到当前插件配置')
            button.clicked.connect(
                lambda checked=False, k=key, t=title, name=label: self._select_qqsg_region(k, t, name)
            )
            mining_region_layout.addWidget(button)
        mining_region_layout.addWidget(QLabel('疲劳：F1 自动读取，无需框选'))
        mining_region_layout.addStretch(1)
        self.mining_region_panel.setVisible(False)
        control_layout.addWidget(self.mining_region_panel)

        # The daily-task plugin is commonly debugged one activity at a time.
        # Keep this selector next to the QQSG controls so users do not need to
        # edit a long JSON document just to switch between full and single-task
        # runs.
        self.daily_task_panel = QWidget()
        daily_task_layout = QHBoxLayout(self.daily_task_panel)
        daily_task_layout.setContentsMargins(0, 0, 0, 0)
        daily_task_layout.setSpacing(6)
        daily_task_layout.addWidget(QLabel('日常任务调试：'))
        self.daily_task_combo = QComboBox()
        self.daily_task_combo.addItem('完整流程（按任务顺序）', 'sequence')
        self.daily_task_combo.addItem('仅垓下学艺', 'gai_xia_xue_yi')
        self.daily_task_combo.addItem('仅灭鼠靖仓', 'mie_shu_jing_cang')
        self.daily_task_combo.addItem('仅举孝廉答题', 'ju_xiao_lian')
        self.daily_task_combo.addItem('仅运送物资', 'transport')
        self.daily_task_combo.setToolTip(
            '完整流程会按 task_sequence 执行；选择单项后只运行该任务，适合逐项调试。'
        )
        self.daily_task_combo.currentIndexChanged.connect(self._daily_task_selection_changed)
        daily_task_layout.addWidget(self.daily_task_combo, 1)
        self.daily_task_status = QLabel('')
        self.daily_task_status.setObjectName('sectionHint')
        daily_task_layout.addWidget(self.daily_task_status)
        self.daily_task_panel.setVisible(False)
        control_layout.addWidget(self.daily_task_panel)

        self.leveling_panel = QWidget()
        leveling_layout = QHBoxLayout(self.leveling_panel)
        leveling_layout.setContentsMargins(0, 0, 0, 0)
        leveling_layout.setSpacing(6)
        leveling_layout.addWidget(QLabel('小号起号调试：'))
        self.leveling_combo = QComboBox()
        self.leveling_combo.addItem('完整流程（1-50级）', 'full')
        self.leveling_combo.addItem('仅 1-10 级', 'level_1_10')
        self.leveling_combo.addItem('仅 11-20 级', 'level_11_20')
        self.leveling_combo.addItem('仅 21-30 级', 'level_21_30')
        self.leveling_combo.addItem('仅 31-40 级', 'level_31_40')
        self.leveling_combo.addItem('仅 41-50 级', 'level_41_50')
        self.leveling_combo.setToolTip(
            '完整流程从保存的等级继续；单阶段模式只执行选中的等级区间。'
        )
        self.leveling_combo.currentIndexChanged.connect(self._leveling_selection_changed)
        leveling_layout.addWidget(self.leveling_combo, 1)
        self.leveling_status = QLabel('')
        self.leveling_status.setObjectName('sectionHint')
        leveling_layout.addWidget(self.leveling_status)
        self.leveling_panel.setVisible(False)
        control_layout.addWidget(self.leveling_panel)

        self.leveling_region_panel = QWidget()
        leveling_region_layout = QHBoxLayout(self.leveling_region_panel)
        leveling_region_layout.setContentsMargins(0, 0, 0, 0)
        leveling_region_layout.setSpacing(6)
        leveling_region_layout.addWidget(QLabel('起号识别区域：'))
        leveling_task_region_btn = QPushButton('框选任务栏')
        leveling_task_region_btn.clicked.connect(self.select_qqsg_task_region)
        leveling_level_region_btn = QPushButton('框选等级')
        leveling_level_region_btn.clicked.connect(self.select_level_region)
        leveling_region_layout.addWidget(leveling_task_region_btn)
        leveling_region_layout.addWidget(leveling_level_region_btn)
        leveling_region_layout.addStretch(1)
        self.leveling_region_panel.setVisible(False)
        control_layout.addWidget(self.leveling_region_panel)

        window_layout = QHBoxLayout()
        window_layout.setSpacing(6)
        detect_windows_btn = QPushButton('识别全部')
        detect_windows_btn.setFixedWidth(76)
        detect_windows_btn.setToolTip('自动扫描并加入所有 QQ 三国客户端窗口')
        detect_windows_btn.clicked.connect(self.auto_detect_game_windows)
        choose_window_btn = QPushButton('手动添加')
        choose_window_btn.setFixedWidth(76)
        choose_window_btn.clicked.connect(self.choose_window)
        switch_line_btn = QPushButton('批量换线')
        switch_line_btn.setFixedWidth(76)
        switch_line_btn.setToolTip('按目标线路依次切换所有已绑定的 QQ 三国窗口')
        switch_line_btn.clicked.connect(self.open_switch_line_dialog)
        self.switch_line_btn = switch_line_btn
        remove_window_btn = QPushButton('移除')
        remove_window_btn.setFixedWidth(54)
        remove_window_btn.clicked.connect(self.remove_current_window)
        self.window_selector = QComboBox()
        self.window_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.window_selector.setMinimumContentsLength(8)
        self.window_selector.setMinimumWidth(0)
        self.window_selector.setPlaceholderText('尚未添加游戏窗口')
        self.window_selector.currentIndexChanged.connect(self._active_window_changed)
        window_layout.addWidget(detect_windows_btn)
        window_layout.addWidget(choose_window_btn)
        window_layout.addWidget(switch_line_btn)
        window_layout.addWidget(self.window_selector, 1)
        window_layout.addWidget(remove_window_btn)
        control_layout.addLayout(window_layout)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(6)
        self.dry_run_checkbox = QCheckBox('模拟运行（不发送真实键鼠输入）')
        self.dry_run_checkbox.setChecked(True)
        action_layout.addWidget(self.dry_run_checkbox)
        action_layout.addStretch(1)
        config_btn = QPushButton('配置')
        config_btn.setFixedWidth(60)
        config_btn.setToolTip('打开 JSON 运行配置')
        config_btn.clicked.connect(self.edit_config)
        action_layout.addWidget(config_btn)
        self.start_btn = QPushButton('启动  Home')
        self.start_btn.setObjectName('scriptPrimaryButton')
        self.start_btn.setFixedWidth(132)
        self.start_btn.clicked.connect(self.toggle)
        self.start_btn.setEnabled(False)
        action_layout.addWidget(self.start_btn)
        control_layout.addLayout(action_layout)

        self.status_label = QLabel('状态：待机')
        self.status_label.setObjectName('scriptStatus')
        control_layout.addWidget(self.status_label)

        bottom_splitter = QTabWidget()
        bottom_splitter.setMinimumHeight(140)

        log_panel = QWidget()
        log_panel.setMinimumWidth(0)
        log_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(5)
        log_layout.addWidget(QLabel('运行日志'))
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setLineWrapMode(QTextEdit.WidgetWidth)
        self.log_display.setWordWrapMode(QTextOption.WrapAnywhere)
        self.log_display.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log_display.setMinimumSize(0, 100)
        self.log_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.log_display.setStyleSheet('font-family: Consolas, monospace; font-size: 12px;')
        self.log_display.document().setMaximumBlockCount(500)
        log_layout.addWidget(self.log_display, 1)
        bottom_splitter.addTab(log_panel, '运行日志')

        preview_panel = QWidget()
        preview_panel.setMinimumWidth(0)
        preview_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(5)
        preview_layout.addWidget(QLabel('脚本截图预览'))
        self.preview_label = ScalablePreviewLabel('脚本执行截图将在这里显示')
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(0, 100)
        # A QLabel normally uses its pixmap's native width as its size hint.
        # Ignore that hint so a large captured frame cannot squeeze the log
        # panel; _render_frame() already scales the image to this viewport.
        self.preview_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.preview_label.setStyleSheet(
            'background: #F7F9FC; border: 1px solid #E4E9F0; border-radius: 8px;'
        )
        preview_layout.addWidget(self.preview_label, 1)
        bottom_splitter.addTab(preview_panel, '截图预览')
        control_layout.addWidget(bottom_splitter, 1)
        root.addWidget(control_panel, 4)

        # Dynamic descriptions and permission strings must never force the
        # scroll area's contents wider than its viewport.
        for label in (self.plugin_title, self.plugin_description, self.template_status, self.status_label):
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.parent.left_layout.addWidget(self.group_box)
        self.refresh_plugins()

    def open_map_debug(self, map_name=None, map_id=None, terrain_entry=None):
        from feature.map_debug_dialog import MapDebugDialog
        config = self.current_config
        saved = config.get('route_data_source', {}).get('game_directory', '')
        installation = Path(saved) if saved else find_installation()
        if not installation or not (installation / 'data/objects.pkg').is_file():
            selected = QFileDialog.getExistingDirectory(self.group_box, '选择 QQ 三国安装目录')
            if not selected:
                return
            installation = Path(selected)
        try:
            manifest = self.current_manifest()
            npc_file = manifest.directory / 'assets/data/npc_locations.json' if manifest else None
            captured_npcs = []
            captured_maps = config.get('captured_npc_maps', {})
            if isinstance(captured_maps, dict) and captured_maps:
                for map_value in captured_maps.values():
                    if not isinstance(map_value, dict):
                        continue
                    for name, value in map_value.get('npcs', {}).items():
                        if isinstance(value, dict):
                            captured_npcs.append({
                                'name': name,
                                'map': map_value.get('map', ''),
                                'map_id': map_value.get('map_id'),
                                **value,
                            })
            captured_config = config.get('captured_npc_routes', {})
            if not captured_npcs and isinstance(captured_config, dict):
                for name, value in captured_config.items():
                    if isinstance(value, dict):
                        captured_npcs.append({'name': name, **value})
            map_package = installation / 'data/update.pkg'
            if not map_package.is_file():
                map_package = installation / 'data/objects.pkg'
            map_catalog = parse_map_catalog(QQSGPackage(map_package).read('res/Txt/MapData.txt'))
            dialog = MapDebugDialog(
                installation / 'data/objects.pkg',
                npc_file=npc_file,
                captured_npcs=captured_npcs,
                map_catalog=map_catalog,
                window_handler=self.window_handler,
                hwnd=int(self.target_window_info['hwnd']) if self.target_window_info else None,
                parent=self.group_box,
                map_name=map_name,
                map_id=map_id,
                terrain_entry=terrain_entry,
            )
            dialog.plan_selected.connect(self.load_terrain_test)
            dialog.npcs_collected.connect(self.save_captured_npcs)
            self.save_terrain_model(dialog.terrain_model())
            dialog.exec_()
        except Exception as error:
            QMessageBox.warning(self.group_box, '地图加载失败', str(error))

    def save_terrain_model(self, model: dict):
        """Persist reusable terrain independently from optional test routes."""
        manifest = self.current_manifest()
        if not manifest or manifest.id != 'com.searchcat.qqsg.official-task':
            return
        config = self._read_config()
        models = dict(config.get('terrain_models', {})) if isinstance(config.get('terrain_models'), dict) else {}
        models[str(model['map'])] = model
        config['terrain_models'] = models
        self.manager.save_config(manifest, config)
        self.current_config = config
        self._log(f'[地形模型] 已保存 {model["map"]}，正式任务可按实时起点规划')

    def save_captured_npcs(self, records: list):
        """Merge NPC coordinates captured from the game's own navigation panel."""
        manifest = self.current_manifest()
        if not manifest or manifest.id != 'com.searchcat.qqsg.official-task' or not records:
            return
        config = self._read_config()
        routes = config.get('npc_routes', {})
        navigation = config.get('navigation_routes', {})
        captured = config.get('captured_npc_routes', {})
        captured_maps = config.get('captured_npc_maps', {})
        routes = dict(routes) if isinstance(routes, dict) else {}
        navigation = dict(navigation) if isinstance(navigation, dict) else {}
        captured = dict(captured) if isinstance(captured, dict) else {}
        captured_maps = dict(captured_maps) if isinstance(captured_maps, dict) else {}
        for record in records:
            name = str(record['name'])
            route = [int(record['map_id']), int(record['x']), int(record['y'])]
            routes[name] = route
            captured[name] = {
                'map': str(record['map']), 'map_id': route[0],
                'x': route[1], 'y': route[2],
                'ocr_confidence': float(record.get('confidence', 0)),
            }
            map_key = str(route[0])
            map_record = dict(captured_maps.get(map_key, {}))
            map_npcs = dict(map_record.get('npcs', {})) if isinstance(map_record.get('npcs', {}), dict) else {}
            map_npcs[name] = {
                'x': route[1], 'y': route[2],
                'ocr_confidence': float(record.get('confidence', 0)),
            }
            captured_maps[map_key] = {
                'map': str(record['map']), 'map_id': route[0], 'npcs': map_npcs,
            }
            existing_path = navigation.get(name)
            existing_waypoints = existing_path.get('waypoints', []) if isinstance(existing_path, dict) else []
            if not isinstance(existing_waypoints, list) or len(existing_waypoints) <= 1:
                # Replace legacy/imported direct endpoints. Multi-point paths
                # were explicitly calibrated by the user and remain intact.
                navigation[name] = {
                    'map': str(record['map']),
                    'waypoints': [[route[1], route[2]]],
                }
        config['npc_routes'] = routes
        config['navigation_routes'] = navigation
        config['captured_npc_routes'] = captured
        config['captured_npc_maps'] = captured_maps
        self.manager.save_config(manifest, config)
        self.current_config = config
        self._update_qqsg_data_controls(manifest, config)
        self._log(f'[NPC 采集] 已保存 {len(records)} 条游戏寻路窗口坐标')

    def load_terrain_test(self, plan):
        manifest = self.current_manifest()
        if not manifest:
            return
        config = dict(self.current_config)
        config['terrain_test_plan'] = plan
        config['terrain_test_enabled'] = True
        config['terrain_test_pending'] = True
        terrain_models = dict(config.get('terrain_models', {})) if isinstance(config.get('terrain_models'), dict) else {}
        terrain_models[str(plan.get('map', '成都.子城'))] = {
            'map': str(plan.get('map', '成都.子城')),
            'scale': float(plan.get('scale', 100)),
            'terrain_records': plan.get('terrain_records', []),
            'planner': plan.get('planner', {}),
        }
        config['terrain_models'] = terrain_models
        self.manager.save_config(manifest, config)
        self.current_config = config
        QMessageBox.information(self.group_box, '已载入寻路测试',
                                '启动脚本将只测试该路线。请先模拟运行核对日志，再取消模拟进行实测。'
                                '\n恢复官爵任务时，在配置中将 terrain_test_enabled 改为 false。')

    def refresh_plugins(self):
        selected_id = self.current_manifest().id if self.current_manifest() else None
        self.manifests, errors = self.manager.discover()
        self.plugin_list.clear()
        selected_row = 0
        for index, manifest in enumerate(self.manifests):
            item = QListWidgetItem(f'{manifest.name} · {manifest.version}')
            item.setToolTip(f'{manifest.name}\n版本：{manifest.version}\nID：{manifest.id}')
            item.setData(Qt.UserRole, index)
            self.plugin_list.addItem(item)
            if manifest.id == selected_id:
                selected_row = index
        if self.manifests:
            self.plugin_list.setCurrentRow(selected_row)
        else:
            self.plugin_title.setText('尚未安装脚本')
            self.plugin_description.setText('可安装包含 plugin.json 的目录或 ZIP。')
            self.start_btn.setEnabled(False)
        for error in errors:
            self._log(f'[清单错误] {error}')

    def current_manifest(self) -> PluginManifest | None:
        item = self.plugin_list.currentItem() if hasattr(self, 'plugin_list') else None
        if not item:
            return None
        index = item.data(Qt.UserRole)
        return self.manifests[index] if isinstance(index, int) and index < len(self.manifests) else None

    def _display_selected_plugin(self):
        manifest = self.current_manifest()
        if not manifest:
            return
        self.qqsg_data_panel.setVisible(manifest.id in {
            'com.searchcat.qqsg.official-task',
            'com.searchcat.qqsg.daily-tasks',
        })
        self.plugin_title.setText(f'{manifest.name}  {manifest.version}')
        permissions = '、'.join(manifest.permissions) if manifest.permissions else '无额外权限声明'
        description = f'{manifest.description}\n权限：{permissions}'
        self.plugin_description.setText(description)
        self.plugin_description.setToolTip(description)
        try:
            config = self.manager.load_config(manifest)
            if manifest.id == 'com.searchcat.qqsg.official-task' and self._apply_captured_npc_precedence(config):
                self.manager.save_config(manifest, config)
            self.current_config = config
            self._rebuild_template_controls(manifest, config)
            self._update_qqsg_data_controls(manifest, config)
            self._update_daily_task_controls(manifest, config)
            self._update_leveling_controls(manifest, config)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.current_config = {}
            self._rebuild_template_controls(manifest, {})
            self._update_qqsg_data_controls(manifest, {})
            self._update_daily_task_controls(manifest, {})
            self._update_leveling_controls(manifest, {})
            self._log(f'[配置错误] {error}')
        self._update_start_enabled()

    def _update_daily_task_controls(self, manifest: PluginManifest, config: dict):
        """Synchronize the daily-task selector from the saved JSON profile."""
        visible = manifest.id == 'com.searchcat.qqsg.daily-tasks'
        self.daily_task_panel.setVisible(visible)
        if not visible:
            return
        mode = str(config.get('task_mode', 'sequence')).strip().lower()
        selected = str(config.get('single_task', 'gai_xia_xue_yi')).strip()
        value = selected if mode in {'single', 'debug', 'one'} else 'sequence'
        index = self.daily_task_combo.findData(value)
        self.daily_task_combo.blockSignals(True)
        self.daily_task_combo.setCurrentIndex(index if index >= 0 else 0)
        self.daily_task_combo.blockSignals(False)
        self.daily_task_status.setText(
            '单任务模式：便于调试' if value != 'sequence' else '完整流程'
        )

    def _daily_task_selection_changed(self, _index: int):
        """Persist the simple UI choice into the plugin's JSON profile."""
        manifest = self.current_manifest()
        if not manifest or manifest.id != 'com.searchcat.qqsg.daily-tasks':
            return
        value = self.daily_task_combo.currentData()
        if not value:
            return
        config = self._read_config()
        if value == 'sequence':
            config['task_mode'] = 'sequence'
            description = '完整流程'
        else:
            config['task_mode'] = 'single'
            config['single_task'] = str(value)
            description = f'单任务：{self.daily_task_combo.currentText()}'
        try:
            path = self.manager.save_config(manifest, config)
        except OSError as error:
            self._log(f'[日常任务模式保存失败] {error}')
            return
        self.current_config = config
        self.daily_task_status.setText('单任务模式：便于调试' if value != 'sequence' else '完整流程')
        self._log(f'[日常任务模式] 已切换为 {description}，配置已保存：{path}')

    def _update_leveling_controls(self, manifest: PluginManifest, config: dict):
        """Synchronize the level-1-to-50 debug selector."""
        visible = manifest.id == 'com.searchcat.qqsg.alt-leveling'
        self.leveling_panel.setVisible(visible)
        self.leveling_region_panel.setVisible(visible)
        if not visible:
            return
        mode = str(config.get('run_mode', 'full')).strip().lower()
        selected = str(config.get('single_stage', 'level_1_10')).strip()
        value = selected if mode == 'single_stage' else 'full'
        index = self.leveling_combo.findData(value)
        self.leveling_combo.blockSignals(True)
        self.leveling_combo.setCurrentIndex(index if index >= 0 else 0)
        self.leveling_combo.blockSignals(False)
        profile = f'{config.get("country", "蜀国")}·{config.get("role_class", "游侠")}'
        self.leveling_status.setText(
            f'{"单阶段调试" if value != "full" else "完整流程"} · {profile}'
        )

    def _leveling_selection_changed(self, _index: int):
        """Persist the level-stage debug choice in the plugin profile."""
        manifest = self.current_manifest()
        if not manifest or manifest.id != 'com.searchcat.qqsg.alt-leveling':
            return
        value = self.leveling_combo.currentData()
        if not value:
            return
        config = self._read_config()
        if value == 'full':
            config['run_mode'] = 'full'
            description = '完整 1-50 级流程'
        else:
            config['run_mode'] = 'single_stage'
            config['single_stage'] = str(value)
            description = f'单阶段：{self.leveling_combo.currentText()}'
        try:
            path = self.manager.save_config(manifest, config)
        except OSError as error:
            self._log(f'[小号起号模式保存失败] {error}')
            return
        self.current_config = config
        profile = f'{config.get("country", "蜀国")}·{config.get("role_class", "游侠")}'
        self.leveling_status.setText(
            f'{"单阶段调试" if value != "full" else "完整流程"} · {profile}'
        )
        self._log(f'[小号起号模式] 已切换为 {description}，配置已保存：{path}')

    def select_level_region(self):
        self._select_qqsg_region(
            'level_region', 'Select character level region', '等级',
        )

    def _update_qqsg_data_controls(self, manifest: PluginManifest, config: dict):
        visible = manifest.id in {
            'com.searchcat.qqsg.official-task',
            'com.searchcat.qqsg.daily-tasks',
        }
        self.qqsg_data_panel.setVisible(visible)
        self.daily_region_panel.setVisible(manifest.id == 'com.searchcat.qqsg.daily-tasks')
        self.mining_region_panel.setVisible(manifest.id == 'com.searchcat.qqsg.mining')
        if visible:
            route_count = len(config.get('npc_routes', {})) if isinstance(config.get('npc_routes'), dict) else 0
            captured_maps = config.get('captured_npc_maps', {})
            map_count = len(captured_maps) if isinstance(captured_maps, dict) else 0
            captured_count = sum(
                len(value.get('npcs', {}))
                for value in captured_maps.values()
                if isinstance(value, dict) and isinstance(value.get('npcs'), dict)
            ) if isinstance(captured_maps, dict) else 0
            region = config.get('minimap_region')
            region_text = f' · 小地图 {region}' if isinstance(region, list) and len(region) == 4 else ''
            task_region = config.get('task_region')
            task_region_text = (
                f' · 任务栏 {task_region}'
                if isinstance(task_region, list) and len(task_region) == 4 else ''
            )
            answer_region = config.get('answer_region')
            answer_region_text = ' · 答题区已配置' if (
                manifest.id == 'com.searchcat.qqsg.daily-tasks'
                and isinstance(answer_region, list) and len(answer_region) == 4
            ) else ''
            capture_text = f' · 已采集 {map_count} 图/{captured_count} NPC' if map_count else ''
            self.qqsg_data_status.setText(
                f'NPC 路由库：{route_count} 条{capture_text}{region_text}{task_region_text}{answer_region_text}'
            )

    @staticmethod
    def _apply_captured_npc_precedence(config: dict) -> bool:
        """Make captures authoritative and migrate them into the per-map catalog."""
        captured = config.get('captured_npc_routes', {})
        if not isinstance(captured, dict):
            return False
        routes = config.get('npc_routes', {})
        navigation = config.get('navigation_routes', {})
        routes = dict(routes) if isinstance(routes, dict) else {}
        navigation = dict(navigation) if isinstance(navigation, dict) else {}
        captured_maps = dict(config.get('captured_npc_maps', {})) \
            if isinstance(config.get('captured_npc_maps'), dict) else {}
        changed = False
        for name, record in captured.items():
            if not isinstance(record, dict):
                continue
            try:
                endpoint = [int(record['map_id']), int(record['x']), int(record['y'])]
            except (KeyError, TypeError, ValueError):
                continue
            if routes.get(name) != endpoint:
                routes[name] = endpoint
                changed = True
            map_key = str(endpoint[0])
            map_value = dict(captured_maps.get(map_key, {}))
            map_npcs = dict(map_value.get('npcs', {})) if isinstance(map_value.get('npcs'), dict) else {}
            captured_value = {
                'x': endpoint[1], 'y': endpoint[2],
                'ocr_confidence': float(record.get('ocr_confidence', 0)),
            }
            if map_npcs.get(name) != captured_value:
                map_npcs[name] = captured_value
                changed = True
            captured_maps[map_key] = {
                'map': str(record.get('map', map_value.get('map', ''))),
                'map_id': endpoint[0], 'npcs': map_npcs,
            }
            existing_path = navigation.get(name)
            waypoints = existing_path.get('waypoints', []) if isinstance(existing_path, dict) else []
            direct_path = {'map': str(record.get('map', '')), 'waypoints': [[endpoint[1], endpoint[2]]]}
            if (not isinstance(waypoints, list) or len(waypoints) <= 1) and existing_path != direct_path:
                navigation[name] = direct_path
                changed = True
        config['npc_routes'] = routes
        config['navigation_routes'] = navigation
        config['captured_npc_maps'] = captured_maps
        return changed

    def select_qqsg_minimap_region(self):
        self._select_qqsg_region(
            'minimap_region', 'Select minimap name and coordinates', '小地图',
        )

    def select_qqsg_task_region(self):
        self._select_qqsg_region(
            'task_region', 'Select task sidebar text region', '任务栏',
        )

    def select_qqsg_answer_region(self):
        self._select_qqsg_region(
            'answer_region', 'Select answer window', '答题',
        )

    def _select_qqsg_region(self, config_key: str, window_title: str, label: str):
        manifest = self.current_manifest()
        if not manifest or manifest.id not in {
            'com.searchcat.qqsg.official-task',
            'com.searchcat.qqsg.daily-tasks',
            'com.searchcat.qqsg.alt-leveling',
            'com.searchcat.qqsg.mining',
        }:
            return
        if self.running or self.switching_lines:
            QMessageBox.information(self.group_box, '请先停止运行', '框选区域前请停止脚本和批量换线。')
            return
        if not self.target_window_info:
            QMessageBox.information(self.group_box, '请先绑定窗口', '请先绑定要运行脚本的游戏窗口。')
            return
        hwnd = int(self.target_window_info['hwnd'])
        if not win32gui.IsWindow(hwnd):
            QMessageBox.warning(self.group_box, '窗口失效', '绑定的游戏窗口已经关闭，请重新绑定。')
            return
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            image = self.window_handler.capture_window_image(hwnd, right - left, bottom - top)
            client_left, client_top = win32gui.ClientToScreen(hwnd, (0, 0))
            _, _, client_width, client_height = win32gui.GetClientRect(hwnd)
            offset_x, offset_y = client_left - left, client_top - top
            client_image = image[
                offset_y:offset_y + client_height,
                offset_x:offset_x + client_width,
            ].copy()
            preview = cv2.cvtColor(client_image, cv2.COLOR_RGB2BGR)
            region = cv2.selectROI(
                window_title,
                preview,
                showCrosshair=True,
                fromCenter=False,
            )
            cv2.destroyWindow(window_title)
        except Exception as error:
            QMessageBox.warning(self.group_box, '框选失败', str(error))
            self._log(f'[{label}框选失败] {error}')
            return
        if region == (0, 0, 0, 0):
            return
        config = self._read_config()
        config[config_key] = [int(value) for value in region]
        self.manager.save_config(manifest, config)
        self.current_config = config
        self._update_qqsg_data_controls(manifest, config)
        self._log(f'[{label}区域] 已保存客户区相对区域：{config[config_key]}')

    def import_qqsg_game_data(self):
        manifest = self.current_manifest()
        if not manifest or manifest.id != 'com.searchcat.qqsg.official-task':
            return
        install_dir = find_installation()
        if install_dir is None:
            selected = QFileDialog.getExistingDirectory(
                self.group_box, '选择 QQ 三国安装目录（目录内应包含 data/objects.pkg）'
            )
            if not selected:
                return
            install_dir = Path(selected)
        coordinate_file = manifest.directory / 'assets' / 'data' / 'npc_locations.json'
        try:
            routes, report = import_routes(install_dir, coordinate_file)
            if not routes:
                raise ValueError('地图数据已读取，但没有坐标记录能匹配当前客户端地图')
            config = self._read_config()
            existing = config.get('npc_routes', {})
            if not isinstance(existing, dict):
                existing = {}
            # Existing values include coordinates captured from the in-game
            # navigation panel and therefore outrank legacy imported data.
            config['npc_routes'] = {**routes, **existing}
            existing_navigation = config.get('navigation_routes', {})
            if not isinstance(existing_navigation, dict):
                existing_navigation = {}
            config['navigation_routes'] = {
                **report.get('navigation_routes', {}),
                **existing_navigation,
            }
            config['route_data_source'] = {
                'game_directory': str(install_dir),
                'map_count': report['maps'],
                'coordinate_count': report['locations'],
            }
            self.manager.save_config(manifest, config)
            self.current_config = config
            self._update_qqsg_data_controls(manifest, config)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self.group_box, '游戏数据导入失败', str(error))
            self._log(f'[游戏数据导入失败] {error}')
            return
        conflict_count = len(report['conflicts'])
        unmatched_count = len(report['unmatched'])
        summary = (
            f"已从当前客户端解析 {report['maps']} 张地图，生成 {report['routes']} 条 NPC 路由；"
            f"地图未匹配 {unmatched_count} 条，重名冲突 {conflict_count} 条。"
        )
        self._log(f'[游戏数据] {summary} 来源：{install_dir}')
        QMessageBox.information(self.group_box, '游戏数据导入完成', summary)

    def _rebuild_template_controls(self, manifest: PluginManifest, config: dict | None = None):
        while self.template_layout.count() > 2:
            item = self.template_layout.takeAt(1)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        templates = manifest.templates or []
        if (manifest.id == 'com.searchcat.qqsg.official-task'
                and (config or {}).get('accept_mode', 'enter_spam') != 'guided_click'):
            self.template_panel.setVisible(False)
            return
        self.template_panel.setVisible(bool(templates))
        if not templates:
            self.template_status.setText('识别模板：无需配置')
            return
        available = sum(
            (manifest.directory / 'assets' / definition['path']).is_file()
            for definition in templates
        )
        self.template_status.setText(f'识别模板：已配置 {available}/{len(templates)}')
        for definition in templates:
            path = manifest.directory / 'assets' / definition['path']
            button = QPushButton(('替换' if path.is_file() else '导入') + definition['name'])
            button.setToolTip(str(path))
            button.clicked.connect(
                lambda _checked=False, item=definition: self._import_template(item)
            )
            self.template_layout.insertWidget(self.template_layout.count() - 1, button)

    def _import_template(self, definition: dict[str, str]):
        manifest = self.current_manifest()
        if not manifest:
            return
        source, _ = QFileDialog.getOpenFileName(
            self.group_box,
            f"选择{definition['name']}截图",
            '',
            '图片文件 (*.png *.jpg *.jpeg *.bmp)',
        )
        if not source:
            return
        destination = manifest.directory / 'assets' / definition['path']
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as error:
            QMessageBox.warning(self.group_box, '模板导入失败', str(error))
            return
        self._log(f"已导入{definition['name']}：{destination}")
        self._rebuild_template_controls(manifest, self.current_config)

    @staticmethod
    def _missing_templates(manifest: PluginManifest) -> list[str]:
        return [
            definition['name']
            for definition in (manifest.templates or [])
            if not (manifest.directory / 'assets' / definition['path']).is_file()
        ]

    def _install(self, path: str):
        if not path:
            return
        try:
            manifest = self.manager.install(Path(path))
            self._log(f'已安装插件：{manifest.name} {manifest.version}')
            self.refresh_plugins()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self.group_box, '安装失败', str(error))

    def install_directory(self):
        self._install(QFileDialog.getExistingDirectory(self.group_box, '选择插件目录'))

    def install_zip(self):
        path, _ = QFileDialog.getOpenFileName(self.group_box, '选择插件 ZIP', '', 'ZIP 文件 (*.zip)')
        self._install(path)

    def open_switch_line_dialog(self):
        """Open the batch line-switch dialog for all currently bound windows."""
        if self.switching_lines:
            self.stop()
            return
        if self.running or self.switching_lines:
            QMessageBox.information(
                self.group_box, '操作进行中', '请先停止当前脚本或等待本次批量换线完成。'
            )
            return
        if not self.target_windows:
            QMessageBox.information(
                self.group_box, '未绑定窗口', '请先添加需要换线的 QQ 三国游戏窗口。'
            )
            return

        dialog = QDialog(self.group_box)
        dialog.setWindowTitle('批量换线')
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        hint = QLabel(
            '将按顺序处理全部已绑定窗口：激活窗口 → Esc → 识别“服务器选线” → '
            '点击目标线路 → 确认 → 读取窗口标题确认线路。未成功时会自动快速重试，适合挤线。'
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(QLabel('目标线路：'))
        line_input = QSpinBox()
        line_input.setRange(1, 16)
        line_input.setValue(1)
        line_input.setSuffix(' 线')
        row.addWidget(line_input)
        row.addStretch(1)
        layout.addLayout(row)
        retry_row = QHBoxLayout()
        retry_row.addWidget(QLabel('每个窗口最多重试：'))
        retry_input = QSpinBox()
        retry_input.setRange(1, 100)
        retry_input.setValue(20)
        retry_input.setSuffix(' 次')
        retry_row.addWidget(retry_input)
        retry_row.addWidget(QLabel('（点击成功但标题未变更时继续尝试）'))
        retry_row.addStretch(1)
        layout.addLayout(retry_row)
        layout.addWidget(QLabel(
            f'当前绑定窗口：{len(self.target_windows)} 个；前台操作会逐个执行，避免窗口抢焦点。'
        ))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('开始换线')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != QDialog.Accepted:
            return

        self._start_batch_line_switch(line_input.value(), retry_input.value())

    def _start_batch_line_switch(self, target_line: int, max_attempts: int = 20):
        if self.switching_lines or self.running:
            return
        windows = [dict(info) for info in self.target_windows]
        self.switching_lines = True
        self._log(
            f'[批量换线] 开始处理 {len(windows)} 个窗口，目标：{target_line} 线；'
            f'每个窗口最多尝试 {max_attempts} 次'
        )
        worker = BatchLineSwitchWorker(
            self.manager,
            windows,
            target_line,
            self.dry_run_checkbox.isChecked(),
            max_attempts=max_attempts,
            parent=self.group_box,
        )
        worker.log_received.connect(lambda sid, message: self._log(message, sid))
        worker.finished_result.connect(self._on_batch_line_switch_finished)
        worker.finished.connect(worker.deleteLater)
        self.switch_line_worker = worker
        self._sync_running_ui()
        worker.start()

    def _on_batch_line_switch_finished(self, success: int, failed: int):
        stopped = bool(self.switch_line_worker and self.switch_line_worker.isInterruptionRequested())
        self.switching_lines = False
        self.switch_line_worker = None
        result = '已停止' if stopped else '完成'
        self._log(f'[批量换线] {result}：成功 {success} 个，失败 {failed} 个')
        self._sync_running_ui()

    def choose_window(self):
        self.window_handler.choose_window()
        if not self.window_handler.window:
            return
        window = self.window_handler.window
        info = self.window_handler.window_info or {}
        title = repair_utf8_gbk_mojibake(str(info.get('title') or window.title))
        selected = {
            'id': f"hwnd-{int(getattr(window, '_hWnd', 0))}",
            'hwnd': int(getattr(window, '_hWnd', 0)),
            'pid': int(info.get('pid', 0)),
            'title': title,
            'number': int(info.get('number', 1)),
            'left': int(window.left),
            'top': int(window.top),
            'width': int(window.right - window.left),
            'height': int(window.bottom - window.top),
            'source': 'manual',
        }
        existing_index = next(
            (index for index, item in enumerate(self.target_windows)
             if item['id'] == selected['id']),
            None,
        )
        if existing_index is None:
            self.target_windows.append(selected)
            self.session_states[selected['id']] = 'ready'
            self.session_logs.setdefault(selected['id'], [])
            self._refresh_window_selector(selected['id'])
            self._log(
                f"[多窗口] 已添加 {title} #{selected['number']} · PID {selected['pid']}",
                selected['id'],
            )
        else:
            self.target_windows[existing_index] = selected
            self._refresh_window_selector(selected['id'])
        self._update_start_enabled()

    @staticmethod
    def _candidate_window_info(candidate: dict, number: int) -> dict:
        hwnd = int(candidate.get('hwnd', 0))
        return {
            'id': f'hwnd-{hwnd}',
            'hwnd': hwnd,
            'pid': int(candidate.get('pid', 0)),
            'title': repair_utf8_gbk_mojibake(str(candidate.get('title', ''))),
            'number': int(number),
            'left': int(candidate.get('left', 0)),
            'top': int(candidate.get('top', 0)),
            'width': int(candidate.get('width', 0)),
            'height': int(candidate.get('height', 0)),
            'source': 'auto',
        }

    @staticmethod
    def _is_live_window_info(info: dict) -> bool:
        hwnd = int(info.get('hwnd', 0))
        if not hwnd or not win32gui.IsWindow(hwnd):
            return False
        try:
            _, live_pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return False
        expected_pid = int(info.get('pid', 0))
        return not expected_pid or int(live_pid) == expected_pid

    def auto_detect_game_windows(self, _checked=False, silent=False):
        """Replace bindings with every currently visible QQSG client window."""
        if self.running:
            if not silent:
                QMessageBox.information(
                    self.group_box, '脚本正在运行',
                    '请先停止全部窗口，再重新扫描游戏窗口。',
                )
            return 0
        candidates = [
            item for item in self.window_handler.list_window_candidates()
            if is_qqsg_game_window_title(item.get('title', ''))
        ]
        candidates.sort(key=lambda item: (item.get('top', 0), item.get('left', 0), item.get('pid', 0)))
        auto_detected = [
            self._candidate_window_info(candidate, index)
            for index, candidate in enumerate(candidates, 1)
        ]
        detected_ids = {item['id'] for item in auto_detected}
        manual_windows = [
            dict(item)
            for item in self.target_windows
            if item.get('source') == 'manual'
            and item.get('id') not in detected_ids
            and self._is_live_window_info(item)
        ]
        detected = auto_detected + manual_windows
        for index, info in enumerate(detected, 1):
            info['number'] = index
        previous_ids = {item['id'] for item in self.target_windows}
        detected_ids = {item['id'] for item in detected}
        selected_id = (
            self.target_window_info.get('id')
            if self.target_window_info and self.target_window_info.get('id') in detected_ids
            else (detected[0]['id'] if detected else None)
        )
        self.target_windows = detected
        for info in detected:
            self.session_states.setdefault(info['id'], 'ready')
            if self.session_states[info['id']] == 'invalid':
                self.session_states[info['id']] = 'ready'
            self.session_logs.setdefault(info['id'], [])
        for stale_id in previous_ids - detected_ids:
            self.session_states.pop(stale_id, None)
            self.session_logs.pop(stale_id, None)
            self.session_frames.pop(stale_id, None)
        self.target_window_info = None
        self._refresh_window_selector(selected_id)
        self._update_start_enabled()
        if detected:
            manual_note = f'，保留 {len(manual_windows)} 个手动窗口' if manual_windows else ''
            self._log(
                f'[多窗口] 自动识别到 {len(auto_detected)} 个 QQ 三国客户端窗口'
                f'{manual_note}；本次共绑定 {len(detected)} 个窗口'
            )
        elif not silent:
            QMessageBox.information(
                self.group_box, '未找到游戏窗口',
                '没有找到标题以“QQ三国 + 版本数字”开头的可见客户端窗口。\n'
                '如果游戏标题特殊，可使用“手动添加”。',
            )
        return len(detected)

    @staticmethod
    def _window_session_label(info: dict, state: str = '') -> str:
        suffix = f' · {state}' if state else ''
        return (
            f"{info.get('title', '未知窗口')} #{info.get('number', 1)} "
            f"· PID {info.get('pid', 0)}{suffix}"
        )

    def _refresh_window_selector(self, selected_id: str | None = None):
        if not hasattr(self, 'window_selector'):
            return
        selected_id = selected_id or (
            self.target_window_info.get('id') if self.target_window_info else None
        )
        self.window_selector.blockSignals(True)
        self.window_selector.clear()
        selected_index = -1
        for index, info in enumerate(self.target_windows):
            session_id = info['id']
            state = self.session_states.get(session_id, 'ready')
            self.window_selector.addItem(
                self._window_session_label(info, self._state_name(state)),
                session_id,
            )
            if session_id == selected_id:
                selected_index = index
        self.window_selector.blockSignals(False)
        if self.target_windows:
            self.window_selector.setCurrentIndex(
                selected_index if selected_index >= 0 else 0
            )
            self._active_window_changed(self.window_selector.currentIndex())
        else:
            self.target_window_info = None
            self.log_display.clear()
            self.preview_label.clear_image('脚本执行截图将在这里显示')

    def _active_window_changed(self, index: int):
        if index < 0 or index >= len(self.target_windows):
            self.target_window_info = None
            return
        self.target_window_info = self.target_windows[index]
        session_id = self.target_window_info['id']
        self.log_display.setPlainText('\n'.join(self.session_logs.get(session_id, [])))
        self._scroll_log_to_end()
        frame = self.session_frames.get(session_id)
        if frame is not None:
            self._render_frame(frame)
        else:
            self.preview_label.clear_image('该窗口尚无脚本截图')
        self._update_status_label()

    def remove_current_window(self):
        if not self.target_window_info:
            return
        session_id = self.target_window_info['id']
        if session_id in self.runners:
            QMessageBox.information(
                self.group_box, '窗口正在运行',
                '请先停止全部脚本，再移除该窗口。',
            )
            return
        self.target_windows = [
            item for item in self.target_windows if item['id'] != session_id
        ]
        self.session_states.pop(session_id, None)
        self.session_logs.pop(session_id, None)
        self.session_frames.pop(session_id, None)
        self.target_window_info = None
        self._refresh_window_selector()
        self._update_start_enabled()

    def _update_start_enabled(self):
        manifest = self.current_manifest()
        self.start_btn.setEnabled(
            (bool(manifest and self.target_windows) and not self.switching_lines) or self.running or self.switching_lines
        )

    def _read_config(self) -> dict:
        if not isinstance(self.current_config, dict):
            raise ValueError('插件配置必须是 JSON 对象')
        return dict(self.current_config)

    def edit_config(self):
        manifest = self.current_manifest()
        if not manifest:
            return
        dialog = QDialog(self.group_box)
        dialog.setWindowTitle(f'{manifest.name} · 运行配置')
        dialog.resize(680, 560)
        layout = QVBoxLayout(dialog)
        hint = QLabel('修改 JSON 配置。保存后将在下次启动脚本时生效。')
        hint.setObjectName('sectionHint')
        layout.addWidget(hint)
        editor = QTextEdit()
        editor.setPlainText(json.dumps(self.current_config, ensure_ascii=False, indent=2))
        editor.setPlaceholderText('{}')
        layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存配置')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        layout.addWidget(buttons)

        def save_and_close():
            try:
                value = json.loads(editor.toPlainText().strip() or '{}')
                if not isinstance(value, dict):
                    raise ValueError('插件配置必须是 JSON 对象')
                path = self.manager.save_config(manifest, value)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                QMessageBox.warning(dialog, '配置错误', str(error))
                return
            self.current_config = value
            self._rebuild_template_controls(manifest, value)
            self._update_qqsg_data_controls(manifest, value)
            self._update_daily_task_controls(manifest, value)
            self._update_leveling_controls(manifest, value)
            self._log(f'配置已保存：{path}')
            dialog.accept()

        buttons.accepted.connect(save_and_close)
        buttons.rejected.connect(dialog.reject)
        dialog.exec_()

    def show_parsed_maps(self):
        """Display every map record parsed from the installed client package."""
        saved = self.current_config.get('route_data_source', {}).get('game_directory', '')
        installation = Path(saved) if saved else find_installation()
        if not installation or not (installation / 'data' / 'objects.pkg').is_file():
            selected = QFileDialog.getExistingDirectory(self.group_box, '选择 QQ 三国安装目录')
            if not selected:
                return
            installation = Path(selected)
        try:
            package = QQSGPackage(installation / 'data' / 'objects.pkg')
            catalog = parse_map_catalog(package.read('res/Txt/MapData.txt'))
            terrain_entries = [name.replace('\\', '/').casefold()
                               for name in package.list_entries('map/')
                               if name.casefold().endswith('.map.srv')]
            connection_candidates = package.connection_candidates()
        except (OSError, ValueError, FileNotFoundError) as error:
            QMessageBox.warning(self.group_box, '地图数据读取失败', str(error))
            return
        from feature.map_debug_dialog import MapDebugDialog

        dialog = QDialog(self.group_box)
        dialog.setWindowTitle(f'已解析地图数据 · {len(catalog)} 张')
        dialog.resize(620, 560)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            f'来源：{installation / "data" / "objects.pkg"}\n'
            f'已从客户端 MapData.txt 解析 {len(catalog)} 张地图；名称和 ID 以当前客户端为准。\n'
            '可查看地形文件中的出口名称、原始坐标和候选目标地图；冲突记录不用于自动导航。\n'
            f'其他连接候选资源：{len(connection_candidates)} 个（仅按文件名筛选）。'
        ))
        search = QLineEdit()
        search.setPlaceholderText('筛选地图名称或 ID')
        layout.addWidget(search)
        listing = QListWidget()
        rows = sorted(catalog.values(), key=lambda item: (int(item['id']), str(item['name'])))

        def terrain_candidates(item):
            normalized_name = str(item.get('name', '')).replace('·', '.')
            override = MapDebugDialog.TERRAIN_ENTRY_OVERRIDES.get(normalized_name)
            resource = str(item.get('resource', '')).replace('\\', '/').casefold()
            resource_name = resource.rsplit('/', 1)[-1]
            # MapData normally stores the render resource as ``NN-N.map`` while
            # the walkable geometry is the sibling ``NN-N.map.srv``.  Resolve
            # that exact basename and verify it exists in the package; never
            # infer a terrain file from the numeric catalog ID alone.
            candidates = []
            if override:
                candidates.append(override.casefold())
            if resource_name.endswith('.map'):
                candidates.append(f'{resource_name}.srv')
            elif resource_name.endswith('.map.srv'):
                candidates.append(resource_name)
            if not candidates:
                return []
            return [entry for entry in terrain_entries
                    if entry.rsplit('/', 1)[-1] in set(candidates)]

        for item in rows:
            terrain = terrain_candidates(item)
            state = '可读取地形' if terrain else '仅目录记录'
            row = QListWidgetItem(f"ID {item['id']:>4}  ·  {item['name']}  ·  {state}")
            row.setData(Qt.UserRole, {**item, 'terrain_entries': terrain})
            row.setToolTip('\n'.join(terrain[:8]) if terrain else '未找到对应 .map.srv 文件')
            listing.addItem(row)
        layout.addWidget(listing, 1)

        def filter_rows(value):
            query = str(value or '').strip().casefold()
            for index in range(listing.count()):
                item = listing.item(index)
                data = item.data(Qt.UserRole) or {}
                haystack = f"{data.get('id', '')} {data.get('name', '')}".casefold()
                item.setHidden(bool(query and query not in haystack))

        search.textChanged.connect(filter_rows)
        def open_selected(item):
            data = item.data(Qt.UserRole) or {}
            entries = data.get('terrain_entries', [])
            if not entries:
                QMessageBox.information(dialog, '没有地形文件', '该地图只有目录记录，未找到可打开的 .map.srv 文件。')
                return
            dialog.accept()
            self.open_map_debug(data.get('name'), data.get('id'), entries[0])

        listing.itemDoubleClicked.connect(open_selected)
        portals_btn = QPushButton('查看所选地图出口 / 连接')

        def show_portals():
            from plugin_platform.qqsg_portals import parse_portals

            selected = listing.currentItem()
            data = selected.data(Qt.UserRole) if selected else None
            if not data or not data.get('terrain_entries'):
                QMessageBox.information(dialog, '地图出口', '请选择一张可读取地形的地图。')
                return
            try:
                by_id = {row['id']: row for row in rows}
                portals = parse_portals(package.read(data['terrain_entries'][0]), data['id'], by_id)
            except (OSError, ValueError) as error:
                QMessageBox.warning(dialog, '出口读取失败', str(error))
                return
            states = {'consistent': '名称与候选 ID 一致', 'label_id_conflict': '名称与 ID 冲突',
                      'unknown_target': '目标 ID 未知', 'ambiguous_label': '名称对应多张地图',
                      'invalid': '记录异常'}
            lines = [f"{data['name']} · ID {data['id']} · {len(portals)} 个出口",
                     '坐标为地形原始单位，不能直接当鼠标坐标；实际过图尚未验证。', '']
            for portal in portals:
                lines.extend([
                    f"{portal['label']} · 原始位置 {portal['position_raw']}",
                    f"候选目标：{portal['target_name_candidate']}（ID {portal['target_id_candidate']}）",
                    f"检查：{states[portal['evidence']]}；文字匹配 ID：{portal['label_target_ids']}", '',
                ])
            QMessageBox.information(dialog, '地图出口 / 连接候选', '\n'.join(lines))

        portals_btn.clicked.connect(show_portals)
        layout.addWidget(portals_btn)
        export_btn = QPushButton('导出地图清单')

        def export_maps():
            path, _ = QFileDialog.getSaveFileName(
                dialog, '导出地图清单', 'qqsg_maps.json', 'JSON 文件 (*.json)'
            )
            if not path:
                return
            payload = []
            for item in rows:
                terrain = terrain_candidates(item)
                payload.append({
                    'id': item['id'],
                    'name': item['name'],
                    'terrain_available': bool(terrain),
                    'terrain_entries': terrain,
                })
            payload = {
                'maps': payload,
                'connection_candidate_entries': connection_candidates,
            }
            try:
                Path(path).write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8'
                )
                QMessageBox.information(dialog, '导出完成', f'已导出 {len(payload["maps"])} 张地图。')
            except OSError as error:
                QMessageBox.warning(dialog, '导出失败', str(error))

        export_btn.clicked.connect(export_maps)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(export_btn)
        layout.addWidget(buttons)
        dialog.exec_()

    def toggle(self):
        self.stop() if self.running or self.switching_lines else self.start()

    def start(self):
        manifest = self.current_manifest()
        if not manifest:
            return
        if not self.target_windows:
            QMessageBox.information(
                self.group_box, '未找到游戏窗口',
                '请先启动 QQ 三国客户端，或使用“手动添加”。',
            )
            return
        try:
            config = self._read_config()
            if (manifest.id == 'com.searchcat.qqsg.official-task'
                    and config.get('terrain_test_enabled', False)
                    and not config.get('terrain_test_pending', False)):
                config['terrain_test_enabled'] = False
                self.current_config = config
                self._log('[地图测试] 已清除旧测试标志，本次启动进入官爵任务流程')
            self.manager.save_config(manifest, config)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self.group_box, '配置错误', str(error))
            return
        if config.get('use_templates', False):
            missing = self._missing_templates(manifest)
            if missing:
                QMessageBox.warning(
                    self.group_box,
                    '识别模板未配置',
                    '请先导入以下模板：' + '、'.join(missing),
                )
                return
        valid_windows = []
        for info in self.target_windows:
            hwnd = int(info['hwnd'])
            if not win32gui.IsWindow(hwnd):
                self.session_states[info['id']] = 'invalid'
                self._log('[多窗口] 目标窗口已关闭，本次跳过', info['id'])
                continue
            _, live_pid = win32process.GetWindowThreadProcessId(hwnd)
            if info.get('pid') and int(live_pid) != int(info['pid']):
                self.session_states[info['id']] = 'invalid'
                self._log('[多窗口] HWND 已被其他进程复用，本次跳过', info['id'])
                continue
            valid_windows.append(info)
        if not valid_windows:
            QMessageBox.warning(self.group_box, '无可用窗口', '所有绑定窗口均已失效，请重新添加。')
            self._refresh_window_selector()
            return

        if manifest.id == 'com.searchcat.qqsg.mining' and config.get('pickaxe_auto_buy_enabled', False) \
                and len(valid_windows) != 1:
            QMessageBox.warning(self.group_box, '自动购买暂限单窗口',
                                '当前角色购买配置是共享的。请仅绑定一个窗口调试自动购买，避免预算记账冲突。')
            return
        purchase_session = None
        if manifest.id == 'com.searchcat.qqsg.mining' and config.get('pickaxe_auto_buy_enabled', False):
            try:
                purchase_session = purchase_session_key(config.get('pickaxe_character_id', ''))
            except ValueError as error:
                QMessageBox.warning(self.group_box, '购买配置不完整', str(error))
                return

        for info in valid_windows:
            session_id = info['id']
            if session_id in self.runners:
                continue
            self.session_logs[session_id] = []
            if self.target_window_info and self.target_window_info['id'] == session_id:
                self.log_display.clear()
            runner = PluginProcess(
                self.manager,
                manifest,
                deepcopy(config),
                info,
                dry_run=self.dry_run_checkbox.isChecked(),
                session_key=purchase_session or session_id,
                parent=self.group_box,
            )
            runner.log_received.connect(
                lambda message, sid=session_id: self._log(message, sid)
            )
            runner.event_received.connect(
                lambda event, data, sid=session_id: self._on_event(sid, event, data)
            )
            runner.frame_captured.connect(
                lambda image, sid=session_id: self._show_frame(sid, image)
            )
            runner.state_changed.connect(
                lambda state, sid=session_id: self._set_state(sid, state)
            )
            runner.finished.connect(
                lambda code, sid=session_id, instance=runner:
                self._on_finished(sid, instance, code)
            )
            self.runners[session_id] = runner
            self.session_states[session_id] = 'starting'
            runner.start()
        self._sync_running_ui()

    def stop(self):
        if self.switch_line_worker and self.switch_line_worker.isRunning():
            self.switch_line_worker.requestInterruption()
            self._log('[批量换线] 正在停止；当前识别返回后不再执行点击或重试')
        for session_id, runner in list(self.runners.items()):
            self.session_states[session_id] = 'stopping'
            runner.stop()
        self._sync_running_ui()

    @staticmethod
    def _state_name(state: str) -> str:
        names = {
            'starting': '正在启动', 'running': '运行中', 'completed': '已完成',
            'failed': '失败', 'stopping': '正在停止', 'stopped': '已停止',
            'ready': '待机', 'invalid': '窗口失效',
        }
        return names.get(state, state)

    def _set_state(self, session_id: str, state: str):
        self.session_states[session_id] = state
        self._refresh_window_selector(session_id if self.target_window_info and
                                      self.target_window_info['id'] == session_id else None)
        self._sync_running_ui()

    def _on_finished(self, session_id: str, runner: PluginProcess, exit_code: int):
        if self.runners.get(session_id) is not runner:
            return
        completed_test = bool(
            exit_code == 0
            and runner.manifest.id == 'com.searchcat.qqsg.official-task'
            and runner.config.get('terrain_test_pending', False)
        )
        if completed_test:
            manifest = runner.manifest
            config = self.manager.load_config(manifest)
            config['terrain_test_enabled'] = False
            config['terrain_test_pending'] = False
            self.manager.save_config(manifest, config)
            self.current_config = config
        self.runners.pop(session_id, None)
        self.session_states[session_id] = 'completed' if exit_code == 0 else 'failed'
        self._log(f'插件进程已结束，退出码 {exit_code}', session_id)
        if completed_test:
            self._log('[地图测试] 本次测试已完成并自动退出测试模式；下次启动将执行官爵任务', session_id)
        active_id = self.target_window_info.get('id') if self.target_window_info else None
        self._refresh_window_selector(active_id)
        self._sync_running_ui()

    def _log(self, message: str, session_id: str | None = None):
        if session_id:
            logs = self.session_logs.setdefault(session_id, [])
            logs.append(str(message))
            if len(logs) > 500:
                del logs[:-500]
            active_id = self.target_window_info.get('id') if self.target_window_info else None
            if active_id != session_id:
                return
        self.log_display.append(str(message))
        # QTextEdit.append() updates the document but does not reliably keep
        # the viewport at the latest block, especially while many SDK events
        # arrive in quick succession. Move both the cursor and scrollbar now,
        # then repeat after Qt has recalculated the document layout.
        self.log_display.moveCursor(QTextCursor.End)
        self.log_display.ensureCursorVisible()
        self._scroll_log_to_end()
        QTimer.singleShot(0, self._scroll_log_to_end)

    def _scroll_log_to_end(self):
        if not hasattr(self, 'log_display'):
            return
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.log_display.viewport().update()

    def _on_event(self, session_id: str, event: str, data: dict):
        if event == 'watch':
            self._log(f"[变量] {data.get('name')} = {data.get('value')}", session_id)
        elif event == 'rpc_completed':
            error = f"，错误：{data['error']}" if data.get('error') else ''
            self._log(
                f"[SDK] {data.get('method')} · {data.get('duration_ms')} ms{error}",
                session_id,
            )

    def _show_frame(self, session_id: str, image):
        height, width, channels = image.shape
        qt_image = QImage(
            image.data, width, height, channels * width, QImage.Format_RGB888,
        ).copy()
        self.session_frames[session_id] = qt_image
        active_id = self.target_window_info.get('id') if self.target_window_info else None
        if active_id != session_id:
            return
        self._render_frame(qt_image)

    def _render_frame(self, qt_image: QImage):
        self.preview_label.show_image(qt_image)

    def _update_status_label(self):
        if self.switching_lines and self.switch_line_worker:
            state = ('正在停止换线' if self.switch_line_worker.isInterruptionRequested() else '批量换线中')
            self.status_label.setText(
                f'状态：{state} · 目标 {self.switch_line_worker.target_line} 线 · '
                f'{len(self.switch_line_worker.windows)} 个窗口'
            )
            return
        active_id = self.target_window_info.get('id') if self.target_window_info else None
        active_state = self._state_name(self.session_states.get(active_id, 'ready')) if active_id else '未绑定'
        running_count = len(self.runners)
        self.status_label.setText(
            f'状态：{active_state} · 运行 {running_count}/{len(self.target_windows)} 窗口'
        )

    def _sync_running_ui(self):
        self.running = bool(self.runners)
        self.start_btn.setText('停止换线  Home' if self.switching_lines else
                               ('停止全部  Home' if self.running else '启动全部  Home'))
        self.plugin_list.setEnabled(not self.running and not self.switching_lines)
        self.plugin_combo.setEnabled(not self.running and not self.switching_lines)
        self.dry_run_checkbox.setEnabled(not self.running and not self.switching_lines)
        if hasattr(self, 'switch_line_btn'):
            self.switch_line_btn.setText('停止换线' if self.switching_lines else '批量换线')
            self.switch_line_btn.setEnabled(self.switching_lines or (bool(self.target_windows) and not self.running))
        self._update_status_label()
        self._update_start_enabled()
