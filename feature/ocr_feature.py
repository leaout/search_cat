from PyQt5.QtWidgets import (QPushButton, QLabel, QVBoxLayout,
                            QHBoxLayout, QTextEdit, QWidget, QLineEdit, QGroupBox,
                            QSpinBox, QComboBox)
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal, QThread, pyqtSlot, QMutex, QMutexLocker  
import os
import keyboard
import time
# import psutil
from core.ocr import Ocr
from core.winoperator import WinOperator
from core.winhandler import WindowHandler
from rapidfuzz import fuzz, utils
import json

# ========== 简化版匹配函数 ==========
def find_best_match_simple(properties, query, threshold=40):
    if not query or len(query.strip()) < 2:
        return None
    
    query_clean = utils.default_process(query).replace("咸鱼游戏", "").strip()
    if not query_clean:
        return None
    
    best_score = 0
    best_prop = None
    
    for prop in properties:
        q_clean = utils.default_process(prop['q'])
        score = fuzz.QRatio(query_clean, q_clean)
        
        if score >= threshold and score > best_score:
            best_score = score
            best_prop = dict(prop)
            best_prop['_score'] = round(score, 1)
    
    return best_prop

def parse_json_lines(file_path):
    """解析JSON文件（兼容单行/数组格式/BOM）"""
    json_list = []
    with open(file_path, 'r', encoding='utf-8-sig') as file:
        content = file.read()
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and 'q' in item:
                        json_list.append(item)
                return json_list
        except json.JSONDecodeError:
            pass
        file.seek(0)
        for line in file:
            line = line.strip()
            if not line or line == '[':
                continue
            if line.endswith(','):
                line = line[:-1]
            if line == ']':
                break
            try:
                json_data = json.loads(line)
                if isinstance(json_data, dict) and 'q' in json_data:
                    json_list.append(json_data)
            except json.JSONDecodeError:
                pass
    return json_list

# ========== 重构后的OCR Worker（全流程在线程内执行） ==========
class OCRWorker(QThread):
    # 信号定义：向外传递结果/状态
    result_ready = pyqtSignal(str, object)  # 识别结果+匹配答案
    error_occurred = pyqtSignal(str)        # 错误信息
    status_updated = pyqtSignal(str)        # 状态更新（如"截图中"）
    
    def __init__(self, answer_set, target_window=None, relative_region=None,
                 absolute_region=None,
                 threshold=40, auto_click=False, interval=1.0, single_run=False):
        super().__init__()
        # 配置参数
        self.answer_set = answer_set
        self.target_window = target_window
        self.relative_region = relative_region
        self.absolute_region = absolute_region
        self.threshold = threshold
        self.auto_click = auto_click
        self.interval = interval  # 线程内处理间隔（秒）
        self.single_run = single_run
        
        # 控制状态
        self._is_running = False
        self._mutex = QMutex()  # 线程安全锁
        self._stop_flag = False
        
        # 初始化工具（线程内初始化，避免跨线程引用）
        self.ocr = None
        self.handler = None
        self.operator = None
        
        # 性能优化
        self.last_question = ""
        self.min_interval = 0.3
        self.last_process_time = 0

    def start_worker(self):
        """启动线程（外部调用）"""
        with QMutexLocker(self._mutex):
            self._stop_flag = False
            self._is_running = True
            self.last_question = ""
        if not self.isRunning():
            self.start()

    def stop_worker(self):
        """停止线程（外部调用）"""
        with QMutexLocker(self._mutex):
            self._stop_flag = True
            self._is_running = False
        # 安全停止线程
        if self.isRunning():
            self.quit()
            self.wait(1000)

    def update_config(self, target_window, relative_region, absolute_region,
                      threshold, auto_click):
        """更新运行配置（线程安全）。"""
        with QMutexLocker(self._mutex):
            self.target_window = target_window
            self.relative_region = relative_region
            self.absolute_region = absolute_region
            self.threshold = threshold
            self.auto_click = auto_click

    def run(self):
        """线程主循环（全流程在线程内执行）"""
        # 线程内初始化工具（避免跨线程创建Qt/系统资源）
        self.ocr = Ocr()
        self.handler = WindowHandler()
        self.operator = WinOperator(self.target_window)

        self.status_updated.emit("线程已启动，开始监控...")
        
        while True:
            # 检查停止标志
            with QMutexLocker(self._mutex):
                if self._stop_flag or not self._is_running:
                    break

            # 控制处理频率
            current_time = time.time()
            if current_time - self.last_process_time < self.min_interval:
                time.sleep(0.05)  # 小幅休眠，减少CPU占用
                continue

            try:
                # 步骤1：截图（线程内执行）
                self.status_updated.emit("正在截图...")
                screenshot_data = self._capture_screenshot()
                # if not screenshot_data:
                #     self.last_process_time = current_time
                #     time.sleep(self.interval)
                #     continue

                # 步骤2：OCR识别（线程内执行）
                self.status_updated.emit("正在OCR识别...")
                question = self._do_ocr(screenshot_data)
                if not question:
                    self.last_process_time = current_time
                    if self.single_run:
                        self.result_ready.emit("", None)
                        break
                    time.sleep(self.interval)
                    continue

                # 去重：跳过重复问题
                if question == self.last_question:
                    self.last_process_time = current_time
                    time.sleep(self.interval)
                    continue
                self.last_question = question

                # 步骤3：答案匹配（线程内执行）
                self.status_updated.emit("正在匹配答案...")
                answer = self._match_answer(question)

                # 步骤4：发送结果（通过信号传递到主线程）
                self.result_ready.emit(question, answer)

                # 步骤5：自动点击（可选，线程内执行）
                if answer and self.auto_click:
                    self._auto_click_answer(answer)

                # 更新时间戳
                self.last_process_time = current_time
                if self.single_run:
                    break

            except Exception as e:
                self.error_occurred.emit(f"处理错误: {str(e)}")
                self.last_process_time = current_time
                if self.single_run:
                    break

            # 线程循环间隔
            time.sleep(self.interval)

        # 线程结束清理
        self.status_updated.emit("线程已停止")
        self.ocr = None
        self.handler = None
        self.operator = None

    def _capture_screenshot(self):
        """线程内截图逻辑"""
        with QMutexLocker(self._mutex):
            window = self.target_window
            region = dict(self.relative_region) if self.relative_region else None
            absolute_region = self.absolute_region

        if absolute_region:
            x1, y1, x2, y2 = absolute_region
            return self.handler.capture_screenshot_ext(x1, y1, x2, y2)
        if not window or not region:
            raise RuntimeError("未配置有效的窗口区域或屏幕区域")

        current_width = max(1, window.right - window.left)
        current_height = max(1, window.bottom - window.top)
        reference_width = max(1, region['reference_width'])
        reference_height = max(1, region['reference_height'])
        scale_x = current_width / reference_width
        scale_y = current_height / reference_height
        x1 = window.left + round(region['x'] * scale_x)
        y1 = window.top + round(region['y'] * scale_y)
        x2 = x1 + round(region['width'] * scale_x)
        y2 = y1 + round(region['height'] * scale_y)
        return self.handler.capture_screenshot_ext(x1, y1, x2, y2)

    def _do_ocr(self, screenshot_data):
        """线程内OCR识别"""
        try:
            start_time = time.time()
            question = ''.join(self.ocr.do_ocr_ext(screenshot_data, simple=True))
            question = question.replace("咸鱼游戏", "").strip()
            ocr_time = time.time() - start_time
            self.status_updated.emit(f"OCR耗时: {ocr_time:.3f}秒")
            return question
        except Exception as e:
            self.error_occurred.emit(f"OCR识别失败: {str(e)}")
            return ""

    def _match_answer(self, question):
        """线程内答案匹配"""
        try:
            start_time = time.time()
            answer = find_best_match_simple(self.answer_set, question, self.threshold)
            # answer = {"q": question, "ans": "三国演义"}  # 测试用固定值
            match_time = time.time() - start_time
            self.status_updated.emit(f"匹配耗时: {match_time:.3f}秒")
            return answer
        except Exception as e:
            self.error_occurred.emit(f"答案匹配失败: {str(e)}")
            return None

    def _auto_click_answer(self, answer):
        """线程内自动点击答案"""
        try:
            if isinstance(answer, dict) and 'ans' in answer:
                answer_value = str(answer['ans']).strip().upper()
                if answer_value not in {'A', 'B'}:
                    self.status_updated.emit(f"文本答案仅提示，不自动点击: {answer['ans']}")
                    return
                self.operator.click_trueorfalse(answer_value)
                self.status_updated.emit(f"已自动点击答案: {answer_value}")
        except Exception as e:
            self.error_occurred.emit(f"自动点击失败: {str(e)}")

# ========== 主控类（外部控制层） ==========
class OCRFeature(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.answer_set = []
        self.unmatched_file = "data/unmatched_questions.txt"
        self.running = False
        self.window_handler = WindowHandler()
        self.target_window = None
        self.relative_region = None
        self.screen_region = None
        self.test_worker = None
        
        self.load_answers()
        
        self.ocr_worker = OCRWorker(
            answer_set=self.answer_set,
            interval=1.0
        )
        self.ocr_worker.result_ready.connect(self.on_result_ready)
        self.ocr_worker.error_occurred.connect(self.on_error_occurred)
        self.ocr_worker.status_updated.connect(self.on_status_updated)
        
        self.selected_region = None
        
    def create_ui(self):
        from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout
        
        self.group_box = QGroupBox("OCR 识图搜索")
        layout = QVBoxLayout(self.group_box)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(12)

        target_step = QLabel('1  选择识别目标')
        target_step.setObjectName('stepTitle')
        layout.addWidget(target_step)
        
        window_layout = QHBoxLayout()
        self.window_btn = QPushButton('选择窗口')
        self.window_btn.clicked.connect(self.choose_window)
        self.screen_mode_btn = QPushButton('全屏框选模式')
        self.screen_mode_btn.clicked.connect(self.use_screen_mode)
        self.window_label = QLabel('未选择窗口')
        self.window_label.setWordWrap(True)
        window_layout.addWidget(self.window_btn)
        window_layout.addWidget(self.screen_mode_btn)
        window_layout.addWidget(self.window_label, 1)
        layout.addLayout(window_layout)
        
        region_layout = QHBoxLayout()
        self.region_btn = QPushButton('选择区域')
        self.region_btn.clicked.connect(self.choose_region)
        self.region_label = QLabel('未选择区域')
        self.region_label.setWordWrap(True)
        region_layout.addWidget(self.region_btn)
        region_layout.addWidget(self.region_label, 1)
        layout.addLayout(region_layout)

        verify_step = QLabel('2  验证识别效果')
        verify_step.setObjectName('stepTitle')
        layout.addWidget(verify_step)

        test_layout = QHBoxLayout()
        self.test_btn = QPushButton('测试识别')
        self.test_btn.clicked.connect(self.test_recognition)
        self.test_btn.setEnabled(False)
        test_layout.addWidget(self.test_btn)
        test_layout.addWidget(QLabel('匹配阈值:'))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 100)
        self.threshold_spin.setValue(40)
        self.threshold_spin.setSuffix('%')
        test_layout.addWidget(self.threshold_spin)
        layout.addLayout(test_layout)

        run_step = QLabel('3  选择运行方式')
        run_step.setObjectName('stepTitle')
        layout.addWidget(run_step)

        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel('运行模式:'))
        self.run_mode_combo = QComboBox()
        self.run_mode_combo.addItems(['仅提示答案', '自动点击答案'])
        self.run_mode_combo.setToolTip('建议先使用仅提示答案确认识别和匹配效果')
        self.run_mode_combo.currentTextChanged.connect(self.on_run_mode_changed)
        mode_layout.addWidget(self.run_mode_combo)
        layout.addLayout(mode_layout)

        self.mode_hint = QLabel('安全模式：持续识别并显示答案，不执行鼠标点击。')
        self.mode_hint.setObjectName('modeHint')
        self.mode_hint.setWordWrap(True)
        layout.addWidget(self.mode_hint)

        search_step = QLabel('题库快速查询')
        search_step.setObjectName('stepTitle')
        layout.addWidget(search_step)
        search_layout = QHBoxLayout()
        self.manual_search_input = QLineEdit()
        self.manual_search_input.setPlaceholderText('输入题目关键字或拼音首字母')
        self.manual_search_input.returnPressed.connect(self.search_question_bank)
        search_layout.addWidget(self.manual_search_input, 1)
        self.manual_search_btn = QPushButton('查询')
        self.manual_search_btn.clicked.connect(self.search_question_bank)
        search_layout.addWidget(self.manual_search_btn)
        layout.addLayout(search_layout)
        
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton('开始连续识别  (Home)')
        self.start_btn.setObjectName('primaryButton')
        self.start_btn.clicked.connect(self.toggle)
        self.status_label = QLabel('状态: 停止')
        self.status_label.setObjectName('featureStatus')
        self.status_label.setWordWrap(True)
        control_layout.addWidget(self.start_btn, 1)
        control_layout.addWidget(self.status_label, 1)
        layout.addLayout(control_layout)
        
        if hasattr(self.parent, 'current_result'):
            self.result_display = self.parent.current_result
        
        self.parent.left_layout.addWidget(self.group_box)
        self._update_controls()

    def on_run_mode_changed(self, mode):
        if mode == '自动点击答案':
            self.mode_hint.setText('谨慎模式：匹配成功后会操作鼠标，请先完成测试识别。')
            self.mode_hint.setProperty('warning', True)
        else:
            self.mode_hint.setText('安全模式：持续识别并显示答案，不执行鼠标点击。')
            self.mode_hint.setProperty('warning', False)
        self.mode_hint.style().unpolish(self.mode_hint)
        self.mode_hint.style().polish(self.mode_hint)

    def search_question_bank(self):
        """手动查询本地题库，支持导入题库的拼音首字母索引。"""
        query = self.manual_search_input.text().strip()
        if not query:
            return
        is_pinyin = query.isascii() and query.isalpha()
        normalized_query = utils.default_process(query) or ''
        ranked = []
        for item in self.answer_set:
            if is_pinyin and query.lower() in str(item.get('idx', '')).lower():
                score = 100.0
            else:
                question = utils.default_process(str(item.get('q', ''))) or ''
                score = max(
                    fuzz.WRatio(normalized_query, question),
                    100.0 if normalized_query and normalized_query in question else 0.0,
                )
            if score >= 40:
                ranked.append((score, item))
        ranked.sort(key=lambda value: value[0], reverse=True)
        if not ranked:
            result_text = f'题库查询：{query}\n未找到相关题目。'
        else:
            lines = [f'题库查询：{query}', '']
            for index, (score, item) in enumerate(ranked[:10], 1):
                lines.append(f"{index}. {item['q']}")
                lines.append(f"   答案：{item.get('ans', '')}    匹配度：{score:.1f}%")
            result_text = '\n'.join(lines)
        if hasattr(self, 'result_display') and self.result_display:
            self.result_display.setText(result_text)
        
    def load_answers(self):
        """加载答案库；同题冲突时网站题库具有更高优先级。"""
        print("正在加载答案数据...")
        start_time = time.time()
        selected_answers = {}
        selected_priorities = {}
        website_override_count = 0
        for root, dirs, files in os.walk("data"):
            dirs.sort()
            for file in sorted(files):
                if file.endswith(".txt"):
                    file_path = os.path.join(root, file)
                    for item in parse_json_lines(file_path):
                        question_key = ''.join(
                            character.lower()
                            for character in str(item.get('q', ''))
                            if character.isalnum()
                        )
                        if not question_key:
                            continue
                        priority = 10 if item.get('source') == (
                            'https://sg1.zhy1024.com/questionBank.js'
                        ) else 0
                        previous_priority = selected_priorities.get(question_key, -1)
                        if priority < previous_priority:
                            continue
                        if priority > previous_priority >= 0:
                            website_override_count += 1
                        selected_answers[question_key] = item
                        selected_priorities[question_key] = priority
        self.answer_set = list(selected_answers.values())
        load_time = time.time() - start_time
        print(
            f"答案数据加载完成，共{len(self.answer_set)}条，"
            f"网站优先覆盖{website_override_count}条，耗时: {load_time:.3f}秒"
        )
        if hasattr(self.parent, 'update_question_count'):
            self.parent.update_question_count(len(self.answer_set))

    def choose_window(self):
        try:
            self.window_handler.choose_window()
            if not self.window_handler.window:
                self.window_label.setText("未选择窗口")
                return
            self.target_window = self.window_handler.window
            self.screen_region = None
            info = self.window_handler.window_info or {}
            alias = f"〔{info.get('alias')}〕 " if info.get('alias') else ''
            number = f" #{info.get('number')}" if info.get('number') else ''
            pid = f" · PID {info.get('pid')}" if info.get('pid') else ''
            self.window_label.setText(
                f"{alias}{self.target_window.title or '已选择窗口'}{number}{pid}"
            )
            if self.relative_region:
                self.region_label.setText("已复用上次的相对识别区域")
            else:
                self.region_label.setText("请框选题目区域")
            self._update_controls()
        except Exception as e:
            self.window_label.setText("窗口选择失败")
            if hasattr(self, 'result_display') and self.result_display:
                self.result_display.setText(f"窗口选择错误: {str(e)}")

    def use_screen_mode(self):
        """清除目标窗口，切换为整个屏幕框选模式。"""
        if self.running:
            self.status_label.setText('状态: 请先停止识别再切换模式')
            return
        self.target_window = None
        self.window_label.setText('屏幕模式 · 不绑定窗口')
        self.region_label.setText('请在整个屏幕中框选识别区域')
        self.run_mode_combo.setCurrentText('仅提示答案')
        self.status_label.setText('状态: 已切换到全屏框选模式')
        self._update_controls()

    def choose_region(self):
        operator = WinOperator(self.target_window)
        if not self.target_window:
            selected_region = operator.select_screen_region()
            if selected_region:
                self.screen_region = selected_region
                self.region_label.setText(
                    f"屏幕区域: ({selected_region[0]}, {selected_region[1]}) - "
                    f"({selected_region[2]}, {selected_region[3]})"
                )
                self.status_label.setText('状态: 已记录屏幕绝对区域，可测试识别')
                self._update_controls()
            else:
                self.region_label.setText('未选择屏幕区域')
            return

        try:
            selected_region = operator.select_window_region(self.target_window)
        except Exception as e:
            self.status_label.setText(f'状态: 区域选择失败: {e}')
            return
        if selected_region:
            self.screen_region = None
            relative_x, relative_y, region_width, region_height = selected_region
            window_width = max(1, self.target_window.right - self.target_window.left)
            window_height = max(1, self.target_window.bottom - self.target_window.top)
            self.relative_region = {
                'x': relative_x,
                'y': relative_y,
                'width': region_width,
                'height': region_height,
                'reference_width': window_width,
                'reference_height': window_height,
            }
            self.selected_region = (
                self.target_window.left + relative_x,
                self.target_window.top + relative_y,
                self.target_window.left + relative_x + region_width,
                self.target_window.top + relative_y + region_height,
            )
            self.region_label.setText(
                f"相对区域: ({self.relative_region['x']}, {self.relative_region['y']}, "
                f"{self.relative_region['width']}×{self.relative_region['height']})"
            )
            self.status_label.setText('状态: 已记录窗口相对区域，可测试识别')
            self._update_controls()
        else:
            self.region_label.setText("未选择区域")

    def _update_controls(self):
        ready = bool(
            (self.target_window and self.relative_region) or self.screen_region
        )
        self.test_btn.setEnabled(ready and not self.running)
        self.start_btn.setEnabled(ready or self.running)

    def test_recognition(self):
        """执行一次截图、OCR 和匹配，不执行自动点击。"""
        if not ((self.target_window and self.relative_region) or self.screen_region):
            self.status_label.setText('状态: 请先配置窗口区域或屏幕区域')
            return
        if self.test_worker and self.test_worker.isRunning():
            return
        self.test_btn.setEnabled(False)
        self.status_label.setText('状态: 正在测试识别...')
        self.test_worker = OCRWorker(
            answer_set=self.answer_set,
            target_window=self.target_window,
            relative_region=self.relative_region,
            absolute_region=self.screen_region,
            threshold=self.threshold_spin.value(),
            auto_click=False,
            interval=0,
            single_run=True,
        )
        self.test_worker.result_ready.connect(self.on_test_result)
        self.test_worker.error_occurred.connect(self.on_error_occurred)
        self.test_worker.finished.connect(self.on_test_finished)
        self.test_worker.start_worker()

    def on_test_result(self, question, answer):
        if not question:
            result_text = "测试结果：未识别到文字，请检查题目区域。"
        elif answer:
            result_text = (
                f"测试识别：{question}\n"
                f"匹配题目：{answer['q']}\n"
                f"答案：{answer['ans']}\n"
                f"匹配度：{answer.get('_score', 0):.1f}%\n"
                "测试模式不会自动点击。"
            )
        else:
            result_text = f"测试识别：{question}\n未找到达到当前阈值的答案。"
        if hasattr(self, 'result_display') and self.result_display:
            self.result_display.setText(result_text)

    def on_test_finished(self):
        self.test_worker = None
        self.status_label.setText('状态: 测试完成')
        self._update_controls()

    def toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        if not ((self.target_window and self.relative_region) or self.screen_region):
            self.status_label.setText('状态: 请先配置窗口区域或屏幕区域')
            return
        auto_click = self.run_mode_combo.currentText() == '自动点击答案'
        if auto_click and not self.target_window:
            self.status_label.setText('状态: 自动点击需要先选择目标窗口')
            return
        self.ocr_worker.update_config(
            self.target_window,
            self.relative_region,
            self.screen_region,
            self.threshold_spin.value(),
            auto_click,
        )
        self.ocr_worker.start_worker()
        self.running = True
        self.start_btn.setText('停止识别  (Home)')
        self.status_label.setText('状态: 运行中')
        self.test_btn.setEnabled(False)
        if hasattr(self.parent, 'hotkey_status_label'):
            self.parent.hotkey_status_label.setText("▶ OCR识别 - 运行中")

    def stop(self):
        self.ocr_worker.stop_worker()
        self.running = False
        self.start_btn.setText('开始连续识别  (Home)')
        self.status_label.setText('状态: 停止')
        self._update_controls()
        if hasattr(self.parent, 'hotkey_status_label'):
            self.parent.hotkey_status_label.setText("○ OCR识别 - 停止")

    # ========== 主线程槽函数（接收Worker信号） ==========
    def on_result_ready(self, question, answer):
        """接收识别结果（主线程更新界面）"""
        if not question:
            return
        # 更新主界面
        if answer:
            result_text = (
                f"识别：{question}\n匹配：{answer['q']}\n"
                f"答案：{answer['ans']}\n匹配度：{answer.get('_score', 0):.1f}%"
            )
        else:
            result_text = f"{question} ---> 未找到匹配答案"
            self.record_unmatched_question(question)
        if hasattr(self, 'result_display') and self.result_display:
            self.result_display.setText(result_text)

    def on_error_occurred(self, error_msg):
        """接收错误信息（主线程显示）"""
        if hasattr(self, 'result_display') and self.result_display:
            self.result_display.setText(error_msg)
        print(f"Worker错误: {error_msg}")

    def on_status_updated(self, status):
        """接收状态更新（主线程显示）"""
        self.status_label.setText(f'状态: {status}')
        print(f"Worker状态: {status}")

    def record_unmatched_question(self, question):
        """记录未匹配问题（主线程执行）"""
        if not question:
            return
        try:
            os.makedirs("data", exist_ok=True)
            with open(self.unmatched_file, 'a', encoding='utf-8') as f:
                f.write(question + '\n')
            print(f"已记录未匹配问题: {question}")
        except Exception as e:
            print(f"记录未匹配问题失败: {e}")

    def __del__(self):
        """析构：确保线程停止"""
        if self.ocr_worker:
            self.ocr_worker.stop_worker()
