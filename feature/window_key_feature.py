from PyQt5.QtWidgets import (QPushButton, QLabel, QVBoxLayout,
                            QHBoxLayout, QGroupBox, QLineEdit, QComboBox,
                            QSpinBox, QTextEdit)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
import pygetwindow as gw
import keyboard
import time
from core.winhandler import WindowHandler
from core.winoperator import Win32Keyboard

class WindowKeyWorker(QThread):
    """工作线程：遍历窗口并按键"""
    status_updated = pyqtSignal(str)  # 状态更新信号
    progress_updated = pyqtSignal(str)  # 进度更新信号
    error_occurred = pyqtSignal(str)  # 错误信号
    finished_signal = pyqtSignal()  # 完成信号

    def __init__(self, key_combination, delay_between_windows=0.5, window_filter="QQ三国", loop_interval=10):
        super().__init__()
        self.key_combination = key_combination
        self.delay_between_windows = delay_between_windows
        self.window_filter = window_filter
        self.loop_interval = loop_interval  # 循环间隔（秒）
        self.is_running = False
        self.key_sequence = self._parse_key_combination(key_combination)

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
        """线程主循环 - 支持循环执行"""
        try:
            self.is_running = True
            loop_count = 0
            win32_keyboard = Win32Keyboard()

            while self.is_running:
                loop_count += 1
                self.status_updated.emit(f"开始第 {loop_count} 轮扫描...")

                all_windows = gw.getAllWindows()
                target_windows = []

                for win in all_windows:
                    if win.title and self.window_filter.lower() in win.title.lower():
                        target_windows.append(win)

                if not target_windows:
                    self.error_occurred.emit(f"未找到包含 '{self.window_filter}' 的窗口")
                    break

                self.status_updated.emit(f"第 {loop_count} 轮: 找到 {len(target_windows)} 个目标窗口，开始处理...")

                for i, win in enumerate(target_windows):
                    if not self.is_running:
                        break

                    try:
                        self.progress_updated.emit(f"第 {loop_count} 轮 - 处理窗口 {i+1}/{len(target_windows)}: {win.title}")

                        win.activate()
                        time.sleep(0.2)

                        for key_group in self.key_sequence:
                            if isinstance(key_group, list) and len(key_group) > 1:
                                win32_keyboard.press_combination(*key_group)
                            else:
                                key = key_group[0] if isinstance(key_group, list) else key_group
                                win32_keyboard.press(key)

                            time.sleep(0.1)

                        if i < len(target_windows) - 1:
                            time.sleep(self.delay_between_windows)

                    except Exception as e:
                        self.error_occurred.emit(f"处理窗口 '{win.title}' 时出错: {str(e)}")
                        continue

                # 检查是否继续循环
                if not self.is_running:
                    break

                self.status_updated.emit(f"第 {loop_count} 轮处理完成，等待 {self.loop_interval} 秒后开始下一轮...")

                # 等待循环间隔
                remaining_time = self.loop_interval
                while remaining_time > 0 and self.is_running:
                    time.sleep(min(1, remaining_time))  # 每秒检查一次停止状态
                    remaining_time -= 1

            if self.is_running:
                self.status_updated.emit("执行已停止")
            else:
                self.status_updated.emit("执行完成")

        except Exception as e:
            self.error_occurred.emit(f"执行过程中出错: {str(e)}")
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

    def init_ui(self):
        """初始化UI界面"""
        # 创建窗口按键功能组
        window_key_group = QGroupBox("窗口批量按键")
        window_key_layout = QVBoxLayout(window_key_group)

        # 第一行：窗口过滤器
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel('窗口过滤:'))
        self.window_filter_input = QLineEdit()
        self.window_filter_input.setText('QQ三国')
        self.window_filter_input.setPlaceholderText('输入窗口标题关键词，如: QQ三国')
        filter_layout.addWidget(self.window_filter_input)

        # 扫描窗口按钮
        self.scan_btn = QPushButton('扫描窗口')
        self.scan_btn.clicked.connect(self.scan_windows)
        filter_layout.addWidget(self.scan_btn)

        window_key_layout.addLayout(filter_layout)

        # 说明文本
        info_label = QLabel('说明: 支持按键组合，如 "space" 或 "ctrl+a->b" 或 "f5"')
        info_label.setStyleSheet("color: gray; font-size: 11px;")
        window_key_layout.addWidget(info_label)

        # 第二行：按键设置
        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel('按键组合:'))
        self.key_input = QLineEdit()
        self.key_input.setText('space')
        self.key_input.setPlaceholderText('输入按键组合，如: a->b-c ->space')
        key_layout.addWidget(self.key_input)

        key_layout.addWidget(QLabel('窗口间隔(秒):'))
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

        loop_layout.addWidget(QLabel('说明: 每次循环完成后等待此时间再重新开始'))
        window_key_layout.addLayout(loop_layout)

        # 第三行：控制按钮
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton('开始执行 (F2)')
        self.start_btn.clicked.connect(self.toggle_execution)
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
        self.parent.left_layout.addWidget(window_key_group)

        # 设置热键
        keyboard.add_hotkey('F2', self.toggle_execution)

    def toggle_execution(self):
        """切换执行状态"""
        if self.is_running:
            self.stop_execution()
        else:
            self.start_execution()

    def start_execution(self):
        """开始执行"""
        if self.is_running:
            return

        key_combination = self.key_input.text().strip()
        if not key_combination:
            self.status_label.setText('状态: 请先输入按键')
            return

        window_filter = self.window_filter_input.text().strip()
        if not window_filter:
            self.status_label.setText('状态: 请先输入窗口过滤关键词')
            return

        delay = self.delay_input.value()
        loop_interval = self.loop_interval_input.value()

        # 创建工作线程
        self.worker = WindowKeyWorker(key_combination, delay, window_filter, loop_interval)

        # 连接信号
        self.worker.status_updated.connect(self.on_status_updated)
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.error_occurred.connect(self.on_error_occurred)
        # 注意：循环执行不会发出finished_signal，除非出错停止

        # 清空进度显示
        self.progress_display.clear()

        # 启动线程
        self.worker.start()
        self.is_running = True
        self.start_btn.setText('停止执行 (F2)')
        self.status_label.setText('状态: 执行中...')

    def stop_execution(self):
        """停止执行"""
        if not self.is_running:
            return

        if self.worker:
            self.worker.stop()
            self.worker.wait(2000)  # 等待线程结束

        self.is_running = False
        self.start_btn.setText('开始执行 (F2)')
        self.status_label.setText('状态: 已停止')

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

    def scan_windows(self):
        """扫描并显示匹配的窗口"""
        window_filter = self.window_filter_input.text().strip()
        if not window_filter:
            self.progress_display.setText("请先输入窗口过滤关键词")
            return

        # 获取所有窗口
        all_windows = gw.getAllWindows()
        target_windows = []

        # 过滤出目标窗口
        for win in all_windows:
            if win.title and window_filter.lower() in win.title.lower():
                target_windows.append(win)

        # 显示结果
        if not target_windows:
            self.progress_display.setText(f"未找到包含 '{window_filter}' 的窗口")
        else:
            result_text = f"找到 {len(target_windows)} 个匹配窗口:\n"
            for i, win in enumerate(target_windows, 1):
                result_text += f"{i}. {win.title}\n"
            self.progress_display.setText(result_text)

    def on_finished(self):
        """执行完成"""
        self.is_running = False
        self.start_btn.setText('开始执行 (F2)')
        self.status_label.setText('状态: 执行完成')
        self.on_progress_updated("✓ 所有窗口处理完成")

    def __del__(self):
        """析构函数"""
        self.stop_execution()
        keyboard.remove_hotkey('F2')
