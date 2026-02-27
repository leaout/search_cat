from PyQt5.QtWidgets import (QPushButton, QLabel, QVBoxLayout,
                            QHBoxLayout, QTextEdit, QWidget, QLineEdit, QGroupBox)
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
            best_prop = prop
    
    return best_prop

def parse_json_lines(file_path):
    """解析JSON文件（兼容单行/数组格式）"""
    json_list = []
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            file.seek(0)
            for line in file:
                try:
                    json_data = json.loads(line)
                    json_list.append(json_data)
                except json.JSONDecodeError as e:
                    print(f"解析JSON行错误: {line} | {e}")
    return json_list

# ========== 重构后的OCR Worker（全流程在线程内执行） ==========
class OCRWorker(QThread):
    # 信号定义：向外传递结果/状态
    result_ready = pyqtSignal(str, object)  # 识别结果+匹配答案
    error_occurred = pyqtSignal(str)        # 错误信息
    status_updated = pyqtSignal(str)        # 状态更新（如"截图中"）
    
    def __init__(self, answer_set, selected_region=None, interval=1.0):
        super().__init__()
        # 配置参数
        self.answer_set = answer_set
        self.selected_region = selected_region
        self.interval = interval  # 线程内处理间隔（秒）
        
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

    def set_selected_region(self, region):
        """更新截图区域（线程安全）"""
        with QMutexLocker(self._mutex):
            self.selected_region = region

    def run(self):
        """线程主循环（全流程在线程内执行）"""
        # 线程内初始化工具（避免跨线程创建Qt/系统资源）
        self.ocr = Ocr()
        self.handler = WindowHandler()
        self.operator = WinOperator()

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
                if answer:
                    self._auto_click_answer(answer)

                # 更新时间戳
                self.last_process_time = current_time

            except Exception as e:
                self.error_occurred.emit(f"处理错误: {str(e)}")
                self.last_process_time = current_time

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
            region = self.selected_region

        if region:
            x1, y1, x2, y2 = region
            return self.handler.capture_screenshot_ext(x1, y1, x2, y2)
        else:
            return self.handler.capture_question_screenshot()

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
            answer = find_best_match_simple(self.answer_set, question)
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
                self.operator.click_trueorfalse(answer['ans'])
                self.status_updated.emit(f"已自动点击答案: {answer['ans']}")
        except Exception as e:
            self.error_occurred.emit(f"自动点击失败: {str(e)}")

# ========== 悬浮窗（无修改） ==========
class FloatingWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OCR结果")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setGeometry(100, 100, 400, 150)
        
        layout = QVBoxLayout()
        self.result_display = QLineEdit()
        self.result_display.setReadOnly(True)
        self.result_display.setStyleSheet("QLineEdit { background-color: white; border: 1px solid gray; padding: 5px; }")
        layout.addWidget(self.result_display)
        self.setLayout(layout)
        
    def update_result(self, text):
        self.result_display.setText(text)

# ========== 主控类（外部控制层） ==========
class OCRFeature(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.answer_set = []
        self.floating_window = None
        self.unmatched_file = "data/unmatched_questions.txt"
        self.running = False
        
        self.load_answers()
        
        self.ocr_worker = OCRWorker(
            answer_set=self.answer_set,
            interval=1.0
        )
        self.ocr_worker.result_ready.connect(self.on_result_ready)
        self.ocr_worker.error_occurred.connect(self.on_error_occurred)
        self.ocr_worker.status_updated.connect(self.on_status_updated)
        
        self.selected_region = None
        self.floating_window = FloatingWindow()
        
    def create_ui(self):
        from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout
        
        self.group_box = QGroupBox("OCR 识图搜索")
        layout = QVBoxLayout(self.group_box)
        
        window_layout = QHBoxLayout()
        self.window_btn = QPushButton('选择窗口')
        self.window_btn.clicked.connect(self.choose_window)
        self.window_label = QLabel('未选择窗口')
        window_layout.addWidget(self.window_btn)
        window_layout.addWidget(self.window_label)
        layout.addLayout(window_layout)
        
        region_layout = QHBoxLayout()
        self.region_btn = QPushButton('选择区域')
        self.region_btn.clicked.connect(self.choose_region)
        self.region_label = QLabel('未选择区域')
        region_layout.addWidget(self.region_btn)
        region_layout.addWidget(self.region_label)
        layout.addLayout(region_layout)
        
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton('启动 (Home)')
        self.start_btn.clicked.connect(self.toggle)
        self.status_label = QLabel('状态: 停止')
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.status_label)
        layout.addLayout(control_layout)
        
        self.parent.left_layout.addWidget(self.group_box)
        self.parent.left_layout.addStretch()
        
    def load_answers(self):
        """加载答案库（主线程执行一次）"""
        print("正在加载答案数据...")
        start_time = time.time()
        for root, dirs, files in os.walk("data"):
            for file in files:
                if file.endswith(".txt"):
                    file_path = os.path.join(root, file)
                    self.answer_set.extend(parse_json_lines(file_path))
        load_time = time.time() - start_time
        print(f"答案数据加载完成，共{len(self.answer_set)}条，耗时: {load_time:.3f}秒")
        if hasattr(self.parent, 'update_question_count'):
            self.parent.update_question_count(len(self.answer_set))

    def choose_window(self):
        try:
            handler = WindowHandler()
            handler.choose_window()
            handler.move_and_resize_window(1390, 10, 527, 970)
            self.window_label.setText("已选择窗口")
            self.start_btn.setEnabled(True)
        except Exception as e:
            self.window_label.setText("窗口选择失败")
            if hasattr(self, 'result_display') and self.result_display:
                self.result_display.setText(f"窗口选择错误: {str(e)}")

    def choose_region(self):
        operator = WinOperator()
        self.selected_region = operator.select_screen_region()
        if self.selected_region:
            self.region_label.setText(f"已选择区域: {self.selected_region}")
            self.start_btn.setEnabled(True)
            self.ocr_worker.set_selected_region(self.selected_region)
        else:
            self.region_label.setText("未选择区域")

    def toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        if self.selected_region:
            self.ocr_worker.set_selected_region(self.selected_region)
        self.ocr_worker.start_worker()
        self.running = True
        self.start_btn.setText('停止 (Home)')
        self.status_label.setText('状态: 运行中')
        if hasattr(self.parent, 'hotkey_status_label'):
            self.parent.hotkey_status_label.setText("▶ OCR识别 - 运行中")

    def stop(self):
        self.ocr_worker.stop_worker()
        self.running = False
        self.start_btn.setText('启动 (Home)')
        self.status_label.setText('状态: 停止')
        if hasattr(self.parent, 'hotkey_status_label'):
            self.parent.hotkey_status_label.setText("○ OCR识别 - 停止")

    # ========== 主线程槽函数（接收Worker信号） ==========
    def on_result_ready(self, question, answer):
        """接收识别结果（主线程更新界面）"""
        if not question:
            return
        # 更新主界面
        if answer:
            result_text = f"{answer['q']} ---> {answer['ans']}"
        else:
            result_text = f"{question} ---> 未找到匹配答案"
            self.record_unmatched_question(question)
        if hasattr(self, 'result_display') and self.result_display:
            self.result_display.setText(result_text)
        # 更新悬浮窗
        if self.floating_window:
            self.floating_window.update_result(result_text)

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
        self.stop_worker()
        if self.floating_window:
            self.floating_window.close()
        keyboard.remove_hotkey('F1')