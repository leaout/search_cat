import math
import os
import time

import cv2
from PyQt5.QtCore import QMutex, QMutexLocker, QThread, Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QTextCursor
from PyQt5.QtWidgets import (QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel,
                             QPushButton, QSpinBox, QTextEdit, QVBoxLayout)

from core.winhandler import WindowHandler


class TravelWorker(QThread):
    """Port of the travel-hole state machine published by sg1.zhy1024.com."""

    status_updated = pyqtSignal(str)
    hole_detected = pyqtSignal(int, str)
    diagnostic_updated = pyqtSignal(str, object)
    error_occurred = pyqtSignal(str)

    NO_GAME_WINDOW = 0
    GAME_WINDOW_FOUND = 1
    ANALYZE_STEP1 = 2
    ANALYZE_STEP2 = 3
    ORIGINAL_TEMPLATE_POINT = (41, 92)
    POINTS = {
        'p1': (583, 509),
        'p2': (220, 405),
        'p3': (172, 155),
        'p4': (488, 587),
        'p5': (588, 509),
    }
    COLORS = {
        'p1': (44, 28, 49),
        'p2': (68, 37, 29),
        'p3': (33, 24, 16),
        'p4': (250, 226, 153),
        'p5': (50, 27, 53),
    }

    def __init__(self, window, threshold=0.9, color_threshold=50, interval=1.0):
        super().__init__()
        self.window = window
        self.threshold = threshold
        self.color_threshold = color_threshold
        self.interval = interval
        self._mutex = QMutex()
        self._stop_flag = False
        self.handler = WindowHandler()
        template_dir = os.path.join('data', 'templates', 'travel')
        self.templates = {
            name: cv2.imread(os.path.join(template_dir, f'{name}.png'), cv2.IMREAD_GRAYSCALE)
            for name in ('xx', 'xj1', 'xj2', 'a')
        }
        self.current_state = self.NO_GAME_WINDOW
        self.current_hole = 0
        self.game_window_lost_count = 0
        self.template_check_skip = 0
        self.xj2_detection_counter = 0
        self.anchor_location = None
        self.calculated_offset = (0, 0)
        self.calculated_points = {}

    def stop_worker(self):
        with QMutexLocker(self._mutex):
            self._stop_flag = True
        self.wait(2500)

    def _stopped(self):
        with QMutexLocker(self._mutex):
            return self._stop_flag

    @staticmethod
    def _template_score(gray_image, template):
        if template is None:
            return 0.0, None
        if template.shape[0] > gray_image.shape[0] or template.shape[1] > gray_image.shape[1]:
            return 0.0, None
        result = cv2.matchTemplate(gray_image, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        return float(score), location

    def _calculate_points(self, anchor_location):
        offset_x = anchor_location[0] - self.ORIGINAL_TEMPLATE_POINT[0]
        offset_y = anchor_location[1] - self.ORIGINAL_TEMPLATE_POINT[1]
        self.calculated_offset = (offset_x, offset_y)
        self.calculated_points = {
            name: (point[0] + offset_x, point[1] + offset_y)
            for name, point in self.POINTS.items()
        }

    def _color_matches(self, image, point_name):
        height, width = image.shape[:2]
        x, y = self.calculated_points.get(point_name, (-1, -1))
        if x < 0 or y < 0 or x >= width or y >= height:
            return False, (0, 0, 0), float('inf'), (x, y)
        red, green, blue = (int(value) for value in image[y, x])
        # The website deliberately reads canvas bytes in B, G, R order.
        actual = (blue, green, red)
        target = self.COLORS[point_name]
        difference = math.sqrt(sum((actual[index] - target[index]) ** 2 for index in range(3)))
        return difference <= self.color_threshold, actual, difference, (x, y)

    def _process_frame(self, image, gray_image):
        results = {name: (0.0, None) for name in self.templates}
        details = []
        results['xx'] = self._template_score(gray_image, self.templates['xx'])
        xx_score, xx_location = results['xx']
        if xx_score > self.threshold:
            self.game_window_lost_count = 0
            self.anchor_location = xx_location
            self._calculate_points(xx_location)
            if self.current_state == self.NO_GAME_WINDOW:
                self.current_state = self.GAME_WINDOW_FOUND
                details.append('找到 xx.png，状态 0 → 1')
        else:
            self.game_window_lost_count += 1
            if self.game_window_lost_count >= 3 and self.current_state != self.NO_GAME_WINDOW:
                self.current_state = self.NO_GAME_WINDOW
                self.current_hole = 0
                details.append('连续 3 帧未找到 xx.png，状态回退为 0')

        if self.current_state == self.GAME_WINDOW_FOUND:
            self.template_check_skip += 1
            if self.template_check_skip >= 3:
                self.template_check_skip = 0
                results['xj1'] = self._template_score(gray_image, self.templates['xj1'])
                if results['xj1'][0] > self.threshold:
                    self.current_state = self.ANALYZE_STEP1
                    details.append('检测到 xj1.png，状态 1 → 2')
                else:
                    results['a'] = self._template_score(gray_image, self.templates['a'])
                    if results['a'][0] > self.threshold:
                        details.append('检测到 a.png；答题识别由 OCR 功能处理')

        if self.current_state == self.ANALYZE_STEP1:
            results['xj1'] = self._template_score(gray_image, self.templates['xj1'])
            if results['xj1'][0] > self.threshold:
                p1 = self._color_matches(image, 'p1')[0]
                if p1:
                    p2 = self._color_matches(image, 'p2')[0]
                    if p2:
                        self.current_state = self.ANALYZE_STEP2
                        self.xj2_detection_counter = 0
                        details.append('p1、p2 匹配，状态 2 → 3，等待 xj2.png')
                    else:
                        self.current_hole = 5
                        details.append('p1 匹配、p2 不匹配 → 洞口 5')
                elif self._color_matches(image, 'p5')[0]:
                    self.current_hole = 3
                    details.append('p1 不匹配、p5 匹配 → 洞口 3')
                else:
                    self.current_hole = 2
                    details.append('p1、p5 均不匹配 → 洞口 2')

        if self.current_state == self.ANALYZE_STEP2:
            results['xj2'] = self._template_score(gray_image, self.templates['xj2'])
            if results['xj2'][0] > self.threshold:
                self.xj2_detection_counter = 0
                if self._color_matches(image, 'p3')[0]:
                    if self._color_matches(image, 'p4')[0]:
                        self.current_hole = 4
                        details.append('xj2、p3、p4 匹配 → 洞口 4')
                    else:
                        self.current_hole = 1
                        details.append('xj2、p3 匹配，p4 不匹配 → 洞口 1')
                else:
                    self.current_hole = 6
                    details.append('xj2 匹配，p3 不匹配 → 洞口 6')
                self.current_state = self.GAME_WINDOW_FOUND
                details.append('第二阶段完成，状态 3 → 1')
            else:
                self.xj2_detection_counter += 1
                details.append(f'等待 xj2.png（{self.xj2_detection_counter}/10）')
                if self.xj2_detection_counter >= 10:
                    self.current_state = self.ANALYZE_STEP1
                    self.xj2_detection_counter = 0
                    details.append('连续 10 次未找到 xj2.png，状态 3 → 2')

        return results, '；'.join(details) or '本轮状态保持不变'

    def _build_diagnostic(self, image, capture_method, results, detail):
        """Build one complete, human-readable recognition trace and annotated frame."""
        height, width = image.shape[:2]
        state_names = {0: '0 未找到游戏窗口', 1: '1 找到游戏窗口', 2: '2 行脚第一步', 3: '3 行脚第二步'}
        lines = [
            time.strftime('%H:%M:%S') + f'  捕获方式：{capture_method}',
            f'识别图片：{width} × {height}；状态：{state_names[self.current_state]}',
            f'xx 锚点：{self.anchor_location}；原始锚点：{self.ORIGINAL_TEMPLATE_POINT}；'
            f'偏移：{self.calculated_offset}',
        ]
        annotated = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        template_colors = {'xx': (0, 165, 255), 'xj1': (0, 210, 60), 'xj2': (255, 190, 0), 'a': (40, 40, 230)}
        for name in ('xx', 'xj1', 'xj2', 'a'):
            score, location = results[name]
            template = self.templates[name]
            lines.append(f'{name}.png：分数 {score:.4f}，位置 {location}，阈值 {self.threshold:.2f}')
            if location is not None:
                x, y = location
                template_height, template_width = template.shape[:2]
                cv2.rectangle(
                    annotated, (x, y), (x + template_width, y + template_height), template_colors[name], 2,
                )
        for point_name in ('p1', 'p2', 'p3', 'p4', 'p5'):
            matched, actual, difference, (x, y) = self._color_matches(image, point_name)
            target = self.COLORS[point_name]
            difference_text = '越界' if math.isinf(difference) else f'{difference:.1f}/{self.color_threshold}'
            lines.append(
                f'{point_name} @ ({x}, {y})：网站取色(B,G,R) {actual}，目标 {target}，'
                f'色差 {difference_text}，'
                f'{"匹配" if matched else "不匹配"}'
            )
            if 0 <= x < width and 0 <= y < height:
                color = (55, 180, 75) if matched else (55, 55, 230)
                cv2.circle(annotated, (x, y), 7, color, 2)
                cv2.putText(annotated, point_name, (x + 9, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        lines.append(f'本轮处理：{detail}')
        lines.append(f'当前结果：{"洞口 " + str(self.current_hole) if self.current_hole else "未确定"}')
        return '\n'.join(lines), cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)

    def run(self):
        missing_templates = [name for name, template in self.templates.items() if template is None]
        if missing_templates:
            self.error_occurred.emit(f'行脚模板文件缺失或无法读取: {", ".join(missing_templates)}')
            return
        self.status_updated.emit('正在监控所选游戏窗口...')
        last_hole = None
        while not self._stopped():
            try:
                hwnd = int(getattr(self.window, '_hWnd', 0))
                width = self.window.right - self.window.left
                height = self.window.bottom - self.window.top
                try:
                    image = self.handler.capture_window_image(hwnd, width, height)
                    if image.mean() < 1 or image.std() < 1:
                        raise RuntimeError('后台截图为空白，游戏可能不支持 PrintWindow')
                    capture_method = '窗口句柄后台截图（不受遮挡影响）'
                except Exception as capture_error:
                    image = self.handler.capture_screenshot_ext(
                        self.window.left, self.window.top,
                        self.window.right, self.window.bottom,
                    )
                    capture_method = f'屏幕截图回退（可能被遮挡；后台截图失败：{capture_error}）'
                gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
                results, detail = self._process_frame(image, gray)
                diagnostic, annotated = self._build_diagnostic(image, capture_method, results, detail)
                self.diagnostic_updated.emit(diagnostic, annotated)
                if self.current_hole != last_hole or self.current_hole == 0:
                    self.hole_detected.emit(self.current_hole, detail)
                    last_hole = self.current_hole
            except Exception as error:
                self.error_occurred.emit(str(error))
            end_time = time.monotonic() + self.interval
            while time.monotonic() < end_time and not self._stopped():
                self.msleep(50)
        self.status_updated.emit('已停止')


class TravelFeature:
    def __init__(self, parent):
        self.parent = parent
        self.window_handler = WindowHandler()
        self.target_window = None
        self.worker = None
        self.running = False

    def create_ui(self):
        self.group_box = QGroupBox('行脚洞口助手')
        layout = QVBoxLayout(self.group_box)
        layout.setSpacing(12)

        window_layout = QHBoxLayout()
        self.window_btn = QPushButton('选择游戏窗口')
        self.window_btn.clicked.connect(self.choose_window)
        self.window_label = QLabel('未选择窗口')
        window_layout.addWidget(self.window_btn)
        window_layout.addWidget(self.window_label, 1)
        layout.addLayout(window_layout)

        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel('模板阈值:'))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.5, 1.0)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(0.9)
        settings_layout.addWidget(self.threshold_spin)
        settings_layout.addWidget(QLabel('颜色阈值:'))
        self.color_threshold_spin = QSpinBox()
        self.color_threshold_spin.setRange(1, 150)
        self.color_threshold_spin.setValue(50)
        settings_layout.addWidget(self.color_threshold_spin)
        layout.addLayout(settings_layout)

        self.start_btn = QPushButton('开始检测  (Home)')
        self.start_btn.setObjectName('primaryButton')
        self.start_btn.clicked.connect(self.toggle)
        self.start_btn.setEnabled(False)
        layout.addWidget(self.start_btn)

        self.hole_label = QLabel('尚未检测到洞口')
        self.hole_label.setObjectName('sectionTitle')
        self.detail_label = QLabel('选择窗口后启动，只读取画面，不执行鼠标或键盘操作。')
        self.detail_label.setWordWrap(True)
        self.detail_label.setObjectName('modeHint')
        layout.addWidget(self.hole_label)
        layout.addWidget(self.detail_label)

        self.preview_label = QLabel('启动后在这里显示本轮实际识别的图片')
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(180)
        self.preview_label.setStyleSheet('background: #F7F9FC; border: 1px solid #E4E9F0; border-radius: 8px;')
        layout.addWidget(self.preview_label)

        self.diagnostic_display = QTextEdit()
        self.diagnostic_display.setReadOnly(True)
        self.diagnostic_display.setMinimumHeight(210)
        self.diagnostic_display.setPlainText(
            '原网站识别规则：\n'
            '1. 每轮先用 xx.png 定位锚点，以 (41,92) 为基准计算五个取色点偏移。\n'
            '2. 状态1每三轮检测 xj1.png；识别后进入状态2并判断 p1、p2、p5。\n'
            '3. p1、p2都匹配后进入状态3，最多等待 xj2.png 十轮，再判断 p3、p4。\n'
            '4. 模板和坐标均不缩放；绿色点表示颜色匹配，红色点表示不匹配。\n'
            + ('─' * 36)
        )
        self.diagnostic_display.document().setMaximumBlockCount(300)
        layout.addWidget(self.diagnostic_display)

        self.parent.left_layout.addWidget(self.group_box)

    def choose_window(self):
        self.window_handler.choose_window()
        if not self.window_handler.window:
            return
        self.target_window = self.window_handler.window
        info = self.window_handler.window_info or {}
        title = str(info.get('title') or self.target_window.title)
        self.window_label.setText(
            f"{title} #{info.get('number', 1)} · PID {info.get('pid', 0)}"
        )
        self.start_btn.setEnabled(True)

    def toggle(self):
        self.stop() if self.running else self.start()

    def start(self):
        if not self.target_window:
            return
        self.worker = TravelWorker(
            self.target_window,
            threshold=self.threshold_spin.value(),
            color_threshold=self.color_threshold_spin.value(),
        )
        self.worker.status_updated.connect(self.detail_label.setText)
        self.worker.hole_detected.connect(self.on_hole_detected)
        self.worker.diagnostic_updated.connect(self.on_diagnostic_updated)
        self.worker.error_occurred.connect(lambda error: self.detail_label.setText(f'检测错误: {error}'))
        self.worker.start()
        self.running = True
        self.start_btn.setText('停止检测  (Home)')

    def stop(self):
        if self.worker:
            self.worker.stop_worker()
            self.worker = None
        self.running = False
        self.start_btn.setText('开始检测  (Home)')

    def on_hole_detected(self, hole, detail):
        self.hole_label.setText(f'洞口 {hole}' if hole else '正在等待目标画面')
        self.detail_label.setText(detail)

    def on_diagnostic_updated(self, diagnostic, image):
        """Display the exact frame and all intermediate recognition values."""
        height, width, channels = image.shape
        qt_image = QImage(image.data, width, height, channels * width, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qt_image).scaled(
            self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(pixmap)
        self.diagnostic_display.append(diagnostic + '\n' + ('─' * 36))
        self.diagnostic_display.moveCursor(QTextCursor.End)
