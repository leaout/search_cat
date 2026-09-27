import json
import re
import time
from pathlib import Path

import win32gui
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (QPushButton, QLabel, QVBoxLayout,
                            QHBoxLayout, QGroupBox, QLineEdit,
                            QDoubleSpinBox, QTextEdit, QCheckBox,
                            QComboBox, QInputDialog, QMessageBox)

from core.winhandler import WindowHandler
from core.winoperator import Win32Keyboard


CONFIG_FILE = Path('data/window_key_config.json')

DEFAULT_PROFILE_NAME = '默认方案'
DEFAULT_PROFILE = {
    'key_combination': 'space',
    'delay_between_keys': 0.1,
    'loop_interval': 5.0,
    'background_mode': False,
}


def _profile_values(value):
    """Return a validated profile, filling fields missing from old configs."""
    source = value if isinstance(value, dict) else {}
    result = dict(DEFAULT_PROFILE)
    result['key_combination'] = str(source.get('key_combination', DEFAULT_PROFILE['key_combination']) or 'space')
    try:
        result['delay_between_keys'] = min(5.0, max(0.0, float(source.get('delay_between_keys', 0.1))))
    except (TypeError, ValueError):
        result['delay_between_keys'] = DEFAULT_PROFILE['delay_between_keys']
    try:
        result['loop_interval'] = min(300.0, max(0.1, float(source.get('loop_interval', 5.0))))
    except (TypeError, ValueError):
        result['loop_interval'] = DEFAULT_PROFILE['loop_interval']
    result['background_mode'] = bool(source.get('background_mode', False))
    return result


def _parse_repeat_suffix(text):
    """Parse ``q*3``/``q x3``/``q×3`` and return ``(key_text, repeat)``."""
    match = re.match(r'^(.+?)\s*(?:\*|[xX×]|重复)\s*(\d+)\s*$', text)
    if not match:
        return text, 1
    key_text, repeat_text = match.groups()
    repeat = max(1, min(99, int(repeat_text)))
    return key_text.strip(), repeat

class WindowKeyWorker(QThread):
    """工作线程：遍历窗口并按键"""
    status_updated = pyqtSignal(str)  # 状态更新信号
    progress_updated = pyqtSignal(str)  # 进度更新信号
    error_occurred = pyqtSignal(str)  # 错误信号
    finished_signal = pyqtSignal()  # 完成信号

    def __init__(self, key_combination, target_hwnd, delay_between_keys=0.1, loop_interval=10, background_mode=False):
        super().__init__()
        self.key_combination = key_combination
        self.target_hwnd = target_hwnd
        self.delay_between_keys = delay_between_keys
        self.loop_interval = loop_interval
        self.is_running = False
        self.key_sequence = self._parse_key_combination(key_combination)
        self.background_mode = background_mode

    def _parse_key_combination(self, combination):
        """解析按键组合字符串"""
        if not combination:
            return [{'keys': ['space'], 'repeat': 1}]  # 默认按键

        # 分割按键序列
        sequence = []
        parts = combination.split('->')

        for part in parts:
            part = part.strip()
            if not part:
                continue

            part, repeat = _parse_repeat_suffix(part)
            # 同时兼容 ctrl+a 和 ctrl-a，-> 只负责分隔按键序列。
            keys = [key.strip() for key in re.split(r'[+-]', part) if key.strip()]
            if keys:
                sequence.append({'keys': keys, 'repeat': repeat})

        return sequence if sequence else [{'keys': ['space'], 'repeat': 1}]

    @staticmethod
    def _normalise_group(group):
        """Support the old list representation as well as repeat-aware groups."""
        if isinstance(group, dict):
            keys = group.get('keys') or ['space']
            repeat = max(1, min(99, int(group.get('repeat', 1))))
            return keys, repeat
        if isinstance(group, (list, tuple)):
            return list(group) or ['space'], 1
        return [str(group)], 1

    def _press_group(self, win32_keyboard, group, background=False):
        keys, repeat = self._normalise_group(group)
        for _ in range(repeat):
            if background:
                if len(keys) > 1:
                    win32_keyboard.background_press_combination(self.target_hwnd, *keys)
                else:
                    win32_keyboard.background_press(self.target_hwnd, keys[0])
            else:
                if len(keys) > 1:
                    win32_keyboard.press_combination(*keys)
                else:
                    win32_keyboard.press(keys[0])
            if self.delay_between_keys > 0:
                time.sleep(self.delay_between_keys)

    def run(self):
        """线程主循环 - 对单个目标窗口循环按键"""
        try:
            self.is_running = True
            loop_count = 0
            win32_keyboard = Win32Keyboard()

            while self.is_running:
                loop_count += 1
                self.status_updated.emit(f"开始第 {loop_count} 轮按键...")

                try:
                    if self.background_mode:
                        for key_group in self.key_sequence:
                            self._press_group(win32_keyboard, key_group, background=True)
                    else:
                        win32gui.SetForegroundWindow(self.target_hwnd)
                        time.sleep(self.delay_between_keys)
                        for key_group in self.key_sequence:
                            self._press_group(win32_keyboard, key_group)

                except Exception as e:
                    self.error_occurred.emit(f"按键失败: {str(e)}")
                    # 目标窗口失效或输入失败时停止当前线程，避免错误被无限重复刷屏。
                    self.is_running = False
                    break

                if not self.is_running:
                    break

                self.status_updated.emit(f"第 {loop_count} 轮完成，等待 {self.loop_interval} 秒后下一轮...")
                remaining_time = self.loop_interval
                while remaining_time > 0 and self.is_running:
                    time.sleep(min(1, remaining_time))
                    remaining_time -= 1

            self.status_updated.emit("执行已停止")

        except Exception as e:
            self.error_occurred.emit(f"执行出错: {str(e)}")
        finally:
            self.is_running = False

    def stop(self):
        """停止执行"""
        self.is_running = False

class WindowKeyFeature:
    def __init__(self, parent):
        self.parent = parent
        self.worker = None
        self.is_running = False
        self.selected_hwnd = None
        self.saved_config = self._load_config()

    def create_ui(self):
        self.group_box = QGroupBox("窗口按键")
        window_key_layout = QVBoxLayout(self.group_box)

        # 方案栏：每套方案保存一组按键和循环参数，切换时立即恢复。
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel('方案:'))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(150)
        self.profile_combo.addItems(list(self.saved_config['profiles'].keys()))
        self.profile_combo.setCurrentText(self.saved_config['active_profile'])
        profile_layout.addWidget(self.profile_combo)
        self.save_profile_btn = QPushButton('保存')
        self.save_profile_btn.setToolTip('保存当前方案')
        self.save_profile_btn.clicked.connect(self.save_current_profile)
        profile_layout.addWidget(self.save_profile_btn)
        self.save_as_profile_btn = QPushButton('另存为')
        self.save_as_profile_btn.clicked.connect(self.save_as_profile)
        profile_layout.addWidget(self.save_as_profile_btn)
        self.delete_profile_btn = QPushButton('删除')
        self.delete_profile_btn.clicked.connect(self.delete_profile)
        profile_layout.addWidget(self.delete_profile_btn)
        profile_layout.addStretch()
        window_key_layout.addLayout(profile_layout)

        self._loading_profile = False
        self.profile_combo.currentTextChanged.connect(self.switch_profile)

        # 第一行：选择窗口
        window_layout = QHBoxLayout()
        self.choose_btn = QPushButton('选择窗口')
        self.choose_btn.clicked.connect(self.choose_window)
        window_layout.addWidget(self.choose_btn)
        self.window_label = QLabel('未选择窗口')
        window_layout.addWidget(self.window_label)
        window_layout.addStretch()
        window_key_layout.addLayout(window_layout)

        # 说明文本
        info_label = QLabel('按键用 -> 连接；重复写法：q*3、q×3 或 ctrl+a*2（每个链条项最多 99 次）')
        info_label.setStyleSheet("color: gray; font-size: 11px;")
        window_key_layout.addWidget(info_label)

        # 第二行：按键设置
        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel('按键组合:'))
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText('如: q*3->space->ctrl+a*2')
        key_layout.addWidget(self.key_input)
        key_layout.addWidget(QLabel('间隔(秒):'))
        self.delay_input = QDoubleSpinBox()
        self.delay_input.setRange(0, 5)
        self.delay_input.setValue(0.1)
        self.delay_input.setSingleStep(0.1)
        self.delay_input.setDecimals(1)
        key_layout.addWidget(self.delay_input)
        window_key_layout.addLayout(key_layout)

        # 第三行：循环设置
        loop_layout = QHBoxLayout()
        loop_layout.addWidget(QLabel('循环间隔(秒):'))
        self.loop_interval_input = QDoubleSpinBox()
        self.loop_interval_input.setRange(0.1, 300)
        self.loop_interval_input.setValue(5.0)
        self.loop_interval_input.setSingleStep(0.5)
        self.loop_interval_input.setDecimals(1)
        loop_layout.addWidget(self.loop_interval_input)

        self.background_cb = QCheckBox('后台模式')
        self.background_cb.setToolTip('启用后不激活窗口，直接向后台发送按键')
        self.background_cb.setChecked(False)
        loop_layout.addWidget(self.background_cb)

        loop_layout.addWidget(QLabel('说明: 每次循环完成后等待此时间再重新开始'))
        window_key_layout.addLayout(loop_layout)

        # 第三行：控制按钮
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton('启动 (Home)')
        self.start_btn.clicked.connect(self.toggle)
        control_layout.addWidget(self.start_btn)

        self.status_label = QLabel('状态: 就绪')
        control_layout.addWidget(self.status_label)

        window_key_layout.addLayout(control_layout)

        # 第四行：进度显示
        progress_layout = QVBoxLayout()
        self.progress_display = QTextEdit()
        self.progress_display.setMaximumHeight(100)
        self.progress_display.setReadOnly(True)
        self.progress_display.setPlaceholderText("执行进度将显示在这里...")
        self.progress_display.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 2px solid #dee2e6;
                padding: 5px;
                font-size: 12px;
                border-radius: 3px;
            }
        """)
        progress_layout.addWidget(QLabel('执行进度:'))
        progress_layout.addWidget(self.progress_display)
        window_key_layout.addLayout(progress_layout)

        self.key_input.textChanged.connect(self.save_config)
        self.delay_input.valueChanged.connect(self.save_config)
        self.loop_interval_input.valueChanged.connect(self.save_config)
        self.background_cb.toggled.connect(self.save_config)

        self._load_active_profile()

        last_window = self.saved_config.get('last_window')
        if isinstance(last_window, dict) and last_window.get('title'):
            self.window_label.setText(
                f"上次：{last_window['title']}"
                f" #{last_window.get('number', 1)} · PID {last_window.get('pid', 0)}（请重新选择）"
            )

        # 添加到左侧布局
        self.parent.left_layout.addWidget(self.group_box)

    @staticmethod
    def _load_config():
        try:
            value = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            if not isinstance(value, dict):
                value = {}
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            value = {}

        # Migrate the original flat config into the profile format without
        # losing the user's existing key chain or selected window metadata.
        raw_profiles = value.get('profiles')
        if isinstance(raw_profiles, dict) and raw_profiles:
            profiles = {
                str(name): _profile_values(profile)
                for name, profile in raw_profiles.items()
                if str(name).strip()
            }
        else:
            legacy = {key: value[key] for key in DEFAULT_PROFILE if key in value}
            profiles = {DEFAULT_PROFILE_NAME: _profile_values(legacy)}

        if not profiles:
            profiles = {DEFAULT_PROFILE_NAME: dict(DEFAULT_PROFILE)}
        active = str(value.get('active_profile') or next(iter(profiles)))
        if active not in profiles:
            active = next(iter(profiles))
        return {
            'profiles': profiles,
            'active_profile': active,
            'last_window': value.get('last_window') if isinstance(value.get('last_window'), dict) else None,
        }

    def _active_profile(self):
        name = self.saved_config.get('active_profile', DEFAULT_PROFILE_NAME)
        return self.saved_config['profiles'].setdefault(name, dict(DEFAULT_PROFILE))

    def _load_active_profile(self):
        profile = _profile_values(self._active_profile())
        self._loading_profile = True
        try:
            self.key_input.setText(str(profile['key_combination']))
            self.delay_input.setValue(float(profile['delay_between_keys']))
            self.loop_interval_input.setValue(float(profile['loop_interval']))
            self.background_cb.setChecked(bool(profile['background_mode']))
        finally:
            self._loading_profile = False

    def _capture_active_profile(self):
        profile = self._active_profile()
        profile.update({
            'key_combination': self.key_input.text().strip(),
            'delay_between_keys': self.delay_input.value(),
            'loop_interval': self.loop_interval_input.value(),
            'background_mode': self.background_cb.isChecked(),
        })
        return profile

    def _write_config(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(self.saved_config, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    def switch_profile(self, name):
        if self._loading_profile or not name or name not in self.saved_config['profiles']:
            return
        self._capture_active_profile()
        self.saved_config['active_profile'] = name
        self._load_active_profile()
        self.save_config()
        self.status_label.setText(f'状态: 已切换到「{name}」')

    def save_current_profile(self):
        self._capture_active_profile()
        self.save_config()
        self.status_label.setText(f'状态: 方案「{self.saved_config["active_profile"]}」已保存')

    def save_as_profile(self):
        name, accepted = QInputDialog.getText(self.group_box, '另存为方案', '方案名称:')
        name = name.strip()
        if not accepted or not name:
            return
        if name in self.saved_config['profiles']:
            answer = QMessageBox.question(
                self.group_box, '覆盖方案', f'方案「{name}」已存在，是否覆盖？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self._capture_active_profile()
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

    def delete_profile(self):
        if len(self.saved_config['profiles']) <= 1:
            self.status_label.setText('状态: 至少保留一套方案')
            return
        name = self.saved_config['active_profile']
        answer = QMessageBox.question(
            self.group_box, '删除方案', f'确定删除方案「{name}」吗？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
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

    def save_config(self, *_args):
        if self._loading_profile:
            return
        self._capture_active_profile()
        try:
            self._write_config()
        except OSError as error:
            self.status_label.setText(f'状态: 配置保存失败：{error}')
    
    def choose_window(self):
        handler = WindowHandler()
        handler.choose_window()
        if handler.window:
            self.selected_hwnd = handler.window._hWnd
            info = handler.window_info or {}
            alias = f"〔{info.get('alias')}〕 " if info.get('alias') else ''
            number = f" #{info.get('number')}" if info.get('number') else ''
            pid = f" · PID {info.get('pid')}" if info.get('pid') else ''
            title = str(info.get('title') or handler.window.title)
            self.window_label.setText(f"{alias}{title}{number}{pid}")
            self.status_label.setText('状态: 已选择窗口')
            self.saved_config['last_window'] = {
                'title': title,
                'number': int(info.get('number') or 1),
                'pid': int(info.get('pid') or 0),
            }
            self.save_config()

    def toggle(self):
        if self.is_running:
            self.stop()
        else:
            self.start()
    
    def start(self):
        if self.is_running:
            return
        if not self.selected_hwnd:
            self.status_label.setText('状态: 请先选择窗口')
            return
        key_combination = self.key_input.text().strip()
        if not key_combination:
            self.status_label.setText('状态: 请先输入按键')
            return
        delay = self.delay_input.value()
        loop_interval = self.loop_interval_input.value()
        self.save_config()
        self.worker = WindowKeyWorker(key_combination, self.selected_hwnd, delay, loop_interval, self.background_cb.isChecked())
        self.worker.status_updated.connect(self.on_status_updated)
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.error_occurred.connect(self.on_error_occurred)
        self.worker.start()
        self.is_running = True
        self.start_btn.setText('停止 (Home)')
        self.status_label.setText('状态: 执行中...')
        if hasattr(self.parent, 'hotkey_status_label'):
            self.parent.hotkey_status_label.setText("▶ 窗口按键 - 运行中")
    
    def stop(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait(2000)
        self.is_running = False
        self.start_btn.setText('启动 (Home)')
        self.status_label.setText('状态: 已停止')
        if hasattr(self.parent, 'hotkey_status_label'):
            self.parent.hotkey_status_label.setText("○ 窗口按键 - 停止")

    def on_status_updated(self, status):
        """状态更新"""
        self.status_label.setText(f'状态: {status}')

    def on_progress_updated(self, progress):
        """进度更新"""
        current_text = self.progress_display.toPlainText()
        new_text = current_text + progress + '\n'
        self.progress_display.setText(new_text)
        # 自动滚动到底部
        self.progress_display.verticalScrollBar().setValue(
            self.progress_display.verticalScrollBar().maximum()
        )

    def on_error_occurred(self, error):
        """错误处理"""
        self.on_progress_updated(f"错误: {error}")
        self.status_label.setText('状态: 执行出错')
