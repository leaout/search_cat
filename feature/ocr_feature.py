from PyQt5.QtWidgets import (QPushButton, QLabel, QVBoxLayout,
                            QHBoxLayout, QTextEdit, QWidget, QLineEdit)
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal, QThread, pyqtSlot  
import os
import keyboard
import threading
from core.ocr import Ocr
from core.winoperator import WinOperator
from core.winhandler import WindowHandler
from fuzzywuzzy import process
import json
import time

def find_best_match(properties, query):
    names =[prop['q'] for prop in properties]
    best_match = process.extractOne(query,names)
    if best_match:
        similarity = best_match[1]
        if similarity < 40:
            return None
        best_name = best_match[0]
        for prop in properties:
            if prop['q'] == best_name:
                return prop
    return None

def parse_json_lines(file_path):
    """Parse JSON file that may be either:
    1. One JSON object per line (old format)
    2. A single JSON array containing all questions (new format)
    """
    json_list = []
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        try:
            # First try parsing as single JSON array
            data = json.loads(content)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            # Fall back to line-by-line parsing
            file.seek(0)
            for line in file:
                try:
                    json_data = json.loads(line)
                    json_list.append(json_data)
                except json.JSONDecodeError as e:
                    print(f"Error parsing JSON on line: {line}")
                    print(e)
    return json_list

# 创建OCR工作线程
class OCRWorker(QThread):
    finished = pyqtSignal(str, object)  # 发送识别结果和匹配答案
    error = pyqtSignal(str)
    
    def __init__(self, ocr, screenshot_data, answer_set, question_cache):
        super().__init__()
        self.ocr = ocr
        self.screenshot_data = screenshot_data
        self.answer_set = answer_set
        self.question_cache = question_cache
        self._is_running = True
        
    def stop(self):
        self._is_running = False
        self.quit()
        self.wait(1000)
        
    def run(self):
        if not self._is_running:
            return
            
        try:
            # OCR识别
            start_time = time.time()
            question = ''.join(self.ocr.do_ocr_ext(self.screenshot_data, simple=True))
            question = question.replace("咸鱼游戏", "").strip()
            ocr_time = time.time() - start_time
            print(f"OCR耗时: {ocr_time:.3f}秒")
            
            if not question or len(question) == 0:
                return
                
            # 检查缓存
            cache_key = question[:50]  # 使用前50个字符作为缓存键
            if cache_key in self.question_cache:
                cached_result = self.question_cache[cache_key]
                self.finished.emit(question, cached_result)
                return
                
            # 查找匹配答案
            match_start = time.time()
            answer = find_best_match(self.answer_set, question)
            match_time = time.time() - match_start
            print(f"匹配耗时: {match_time:.3f}秒")
            
            # 缓存结果
            if cache_key not in self.question_cache and answer is not None:
                self.question_cache[cache_key] = answer
                # 限制缓存大小
                if len(self.question_cache) > 100:
                    # 移除最旧的条目
                    oldest_key = next(iter(self.question_cache))
                    del self.question_cache[oldest_key]
                    
            self.finished.emit(question, answer)
            
        except Exception as e:
            # self.error.emit(f"OCR处理错误: {str(e)}")
            print(f"OCR处理错误: {str(e)}")

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

class OCRFeature(QObject):
    hotkey_triggered = pyqtSignal()
    
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.handler = WindowHandler()
        self.operator = None
        self.answer_set = []
        self.floating_window = None
        self.load_answers()
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_screenshot)
        self.is_running = False
        self.ocr = Ocr()
        self.selected_region = None
        
        # 性能优化相关
        self.ocr_worker = None
        self.processing = False  # 防止重复处理
        self.question_cache = {}  # 问题缓存
        self.last_question = ""  # 上一次的问题，用于去重
        self.last_process_time = 0  # 上次处理时间
        self.min_interval = 0.3  # 最小处理间隔(秒)
        
        self.hotkey_triggered.connect(self.toggle_process)
        
    def load_answers(self):
        """预加载答案数据，优化匹配速度"""
        print("正在加载答案数据...")
        start_time = time.time()
        
        for root, dirs, files in os.walk("data"):
            for file in files:
                if not file.endswith(".txt"):
                    continue
                file_path = os.path.join(root, file)
                result = parse_json_lines(file_path)
                self.answer_set.extend(result)
                
        load_time = time.time() - start_time
        print(f"答案数据加载完成，共{len(self.answer_set)}条，耗时: {load_time:.3f}秒")
                
    def init_ui(self):
        self.parent.window_btn.clicked.connect(self.choose_window)
        self.parent.region_btn.clicked.connect(self.choose_region)
        self.parent.start_btn.clicked.connect(self.toggle_process)
        
        self.result_display = self.parent.current_result
        self.parent.start_btn.setEnabled(False)

        keyboard.add_hotkey('F1', self.emit_hotkey_signal)

    def choose_region(self):
        if self.operator is None:
            self.operator = WinOperator()
        self.selected_region = self.operator.select_screen_region()
        if self.selected_region:
            self.parent.region_label.setText(f"已选择区域: {self.selected_region}")
            self.parent.start_btn.setEnabled(True)
        else:
            self.parent.region_label.setText("未选择区域")
        
    def emit_hotkey_signal(self):
        self.hotkey_triggered.emit()
        
    def choose_window(self):
        try:
            self.handler.choose_window()
            self.handler.move_and_resize_window(1390, 10, 527, 970)
            self.parent.window_label.setText("已选择窗口")
            self.parent.start_btn.setEnabled(True)
            self.operator = WinOperator(self.handler.window)
        except Exception as e:
            self.parent.start_btn.setEnabled(True)
            self.parent.window_label.setText("窗口选择失败")
            self.result_display.setText(f"窗口选择错误: {str(e)}")

    def toggle_process(self):
        if self.is_running:
            self.stop_ocr_worker()
            self.timer.stop()
            self.parent.start_btn.setText('开始 OCR (F1)')
            self.parent.status_label.setText('状态: 停止')
            self.is_running = False
        else:
            self.is_running = True
            self.timer.start(1000)  # 界面刷新间隔保持1000ms，但实际处理有间隔控制
            self.parent.start_btn.setText('停止 OCR (F1)')
            self.parent.status_label.setText('状态: 运行中')

    def stop_ocr_worker(self):
        """停止OCR工作线程"""
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.ocr_worker.stop()
            self.ocr_worker.wait(1000)

    def on_ocr_finished(self, question, answer):
        """OCR处理完成回调"""
        self.processing = False
        
        if len(question) == 0:
            return
            
        # 直接设置文本，覆盖之前的内容
        self.result_display.setText(f"识别问题: {question}")
        
        if answer is not None:
            result_text = f"{answer['q']} ---> {answer['ans']}"
            self.result_display.setText(result_text)
            if self.floating_window:
                self.floating_window.update_result(result_text)
            self.operator.click_trueorfalse(answer['ans'])
        else:
            error_text = "未找到匹配答案"
            self.result_display.setText(error_text)
            if self.floating_window:
                self.floating_window.update_result(error_text)
                
    def on_ocr_error(self, error_msg):
        """OCR错误处理"""
        self.processing = False
        self.result_display.setText(error_msg)

    def process_screenshot(self):
        """优化的截图处理流程"""
        # 检查基本条件
        if (not self.is_running ):
            return
            
        # 控制处理频率
        current_time = time.time()
        if current_time - self.last_process_time < self.min_interval:
            return
            
        # 使用选定的区域进行截图
        try:
            if self.selected_region:
                x1, y1, x2, y2 = self.selected_region
                screenshot_data = self.handler.capture_screenshot_ext(x1, y1, x2, y2)
            else:
                screenshot_data = self.handler.capture_question_screenshot()
        except Exception as e:
            self.result_display.setText(f"截图失败: {str(e)}")
            return
            
        # 停止之前的工作线程（如果有）
        self.stop_ocr_worker()
        
        # 创建新的OCR工作线程
        self.processing = True
        self.last_process_time = current_time
        
        self.ocr_worker = OCRWorker(
            self.ocr, 
            screenshot_data, 
            self.answer_set,
            self.question_cache
        )
        self.ocr_worker.finished.connect(self.on_ocr_finished)
        self.ocr_worker.error.connect(self.on_ocr_error)
        self.ocr_worker.start()