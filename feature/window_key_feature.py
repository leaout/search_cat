from PyQt5.QtWidgets import (QPushButton, QLabel, QVBoxLayout,
                            QHBoxLayout, QGroupBox, QLineEdit,
                            QSpinBox, QTextEdit, QCheckBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import keyboard
import time
import win32gui
from core.winhandler import WindowHandler
from core.winoperator import Win32Keyboard

class WindowKeyWorker(QThread):
    """工作线程：遍历窗口并按键"""
    status_updated = pyqtSignal(str)  # 状态更新信号
    progress_updated = pyqtSignal(str)  # 进度更新信号
    error_occurred = pyqtSignal(str)  # 错误信号
    finished_signal = pyqtSignal()  # 完成信号

    def __init__(self, key_combination, target_hwnd, delay_between_windows=0.5, loop_interval=10, background_mode=False):
        super().__init__()
        self.key_combination = key_combination
        self.target_hwnd = target_hwnd
        self.delay_between_windows = delay_between_windows
        self.loop_interval = loop_interval
        self.is_running = False
        self.key_sequence = self._parse_key_combination(key_combination)
        self.background_mode = background_mode

    def _parse_key_combination(self, combination):
        """解析按键组合字符串"""
        if not combination:
            return [['space']]  # 默认按键

        # 分割按键序列
        sequence = []
        parts = combination.split('->')

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # 处理组合键 (如 'ctrl+a', 'shift+b-c')
            if '-' in part:
                # 分割组合键中的各个按键
                keys = [k.strip() for k in part.split('-') if k.strip()]
                if keys:
                    sequence.append(keys)
            else:
                # 单个按键
                sequence.append([part])

        return sequence if sequence else [['space']]

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
                        hwnd = self.target_hwnd
                        for key_group in self.key_sequence:
                            if isinstance(key_group, list) and len(key_group) > 1:
                                win32_keyboard.background_press_combination(hwnd, *key_group)
                            else:
                                key = key_group[0] if isinstance(key_group, list) else key_group
                                win32_keyboard.background_press(hwnd, key)
                            time.sleep(0.1)
                    else:
                        win32gui.SetForegroundWindow(self.target_hwnd)
                        time.sleep(0.2)
                        for key_group in self.key_sequence:
                            if isinstance(key_group, list) and len(key_group) > 1:
                                win32_keyboard.press_combination(*key_group)
                            else:
                                key = key_group[0] if isinstance(key_group, list) else key_group
                                win32_keyboard.press(key)
                            time.sleep(0.1)

                except Exception as e:
                    self.error_occurred.emit(f"按键失败: {str(e)}")
                    if not self.is_running:
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

    def create_ui(self):
        self.group_box = QGroupBox("窗口按键")
        window_key_layout = QVBoxLayout(self.group_box)

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
        info_label = QLabel('支持按键组合，如 "space" 或 "ctrl+a->b" 或 "f5"')
        info_label.setStyleSheet("color: gray; font-size: 11px;")
        window_key_layout.addWidget(info_label)

        # 第二行：按键设置
        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel('按键组合:'))
        self.key_input = QLineEdit()
        self.key_input.setText('space')
        self.key_input.setPlaceholderText('如: a->b-c->space')
        key_layout.addWidget(self.key_input)
        key_layout.addWidget(QLabel('间隔(秒):'))
        self.delay_input = QSpinBox()
        self.delay_input.setRange(0, 5)
        self.delay_input.setValue(1)
        self.delay_input.setSingleStep(1)
        key_layout.addWidget(self.delay_input)
        window_key_layout.addLayout(key_layout)

        # 第三行：循环设置
        loop_layout = QHBoxLayout()
        loop_layout.addWidget(QLabel('循环间隔(秒):'))
        self.loop_interval_input = QSpinBox()
        self.loop_interval_input.setRange(5, 300)
        self.loop_interval_input.setValue(30)
        self.loop_interval_input.setSingleStep(5)
        loop_layout.addWidget(self.loop_interval_input)

        self.background_cb = QCheckBox('后台模式')
        self.background_cb.setToolTip('启用后不激活窗口，直接向后台发送按键')
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

        # 添加到左侧布局
        self.parent.left_layout.addWidget(self.group_box)
        self.parent.left_layout.addStretch()
    
    def choose_window(self):
        handler = WindowHandler()
        handler.choose_window()
        if handler.window:
            self.selected_hwnd = handler.window._hWnd
            self.window_label.setText(handler.window.title)
            self.status_label.setText('状态: 已选择窗口')

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
