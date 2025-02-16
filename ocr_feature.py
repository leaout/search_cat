from PyQt5.QtWidgets import (QPushButton, QLabel, QVBoxLayout,
                            QHBoxLayout, QTextEdit, QWidget)
from PyQt5.QtCore import Qt,QTimer
import os
import keyboard
from main import WindowHandler, Ocr, WinOperator, find_best_match, parse_json_lines
import threading
from PyQt5.QtCore import pyqtSignal

class FloatingWindow(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OCR结果")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setGeometry(100, 100, 400, 300)
        
        layout = QVBoxLayout()
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)
        
        self.setLayout(layout)
        

class OCRFeature:
    def __init__(self, parent):
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
        
    def load_answers(self):
        for root, dirs, files in os.walk("data"):
            for file in files:
                if not file.endswith(".txt"):
                    continue
                file_path = os.path.join(root, file)
                result = parse_json_lines(file_path)
                self.answer_set.extend(result)
                
    def init_ui(self):
        # OCR specific UI components
        btn_layout = QHBoxLayout()
        
        self.window_btn = QPushButton('选择窗口')
        self.window_btn.clicked.connect(self.choose_window)
        btn_layout.addWidget(self.window_btn)
        
        self.window_label = QLabel('未选择窗口')
        btn_layout.addWidget(self.window_label)
        
        self.start_btn = QPushButton('开始/F1')
        self.start_btn.clicked.connect(self.toggle_process)
        self.start_btn.setEnabled(False)
        btn_layout.addWidget(self.start_btn)
        
        self.status_label = QLabel('状态: 停止')
        btn_layout.addWidget(self.status_label)
        
        self.parent.ocr_layout.addLayout(btn_layout)
        
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        self.parent.ocr_layout.addWidget(self.result_display)
        
        keyboard.add_hotkey('F1', self.toggle_process)
        

    def choose_window(self):
        try:
            self.handler.choose_window()
            self.handler.move_and_resize_window(1390, 10, 527, 970)
            self.window_label.setText("已选择窗口")
            self.start_btn.setEnabled(True)
            self.operator = WinOperator(self.handler.window)
        except Exception as e:
            self.start_btn.setEnabled(True)
            self.window_label.setText("窗口选择失败")
            self.result_display.append(f"窗口选择错误: {str(e)}\n")

    def repeat_function(self, interval):
        if self.is_running:
            self.process_screenshot()
            threading.Timer(interval, self.repeat_function, [interval]).start()
        
    def toggle_process(self):
        if self.is_running:
            self.timer.stop()
            self.start_btn.setText('开始/F1')
            self.status_label.setText('状态: 停止')
            self.is_running = False
            if self.floating_window:
                self.floating_window.close()
        else:
            self.is_running = True
            self.floating_window = FloatingWindow()
            self.floating_window.show()
            # self.repeat_function(0.5)
            self.timer.start(500)
            self.start_btn.setText('停止/F1')
            self.status_label.setText('状态: 运行中')


    def process_screenshot(self):
        if self.operator is None:
            self.result_display.append("请先选择目标窗口\n")
            self.toggle_process()
            return
            
        screenshot_data = self.handler.capture_question_screenshot()
        question = ''.join(self.ocr.do_ocr_ext(screenshot_data, simple=True))
        question = question.replace("咸鱼游戏", "")
        
        if len(question) == 0:
            return
            
        answer = find_best_match(self.answer_set, question)
        if answer is not None:
            result_text = f"{answer['q']} ---> {answer['ans']}\n"
            self.result_display.append(result_text)
            self.result_display.setFocus()
            if self.floating_window:
                self.floating_window.text_edit.append(result_text)
                self.floating_window.text_edit.setFocus()
            self.operator.click_trueorfalse(answer['ans'])
        else:
            error_text = "未找到匹配答案\n"
            self.result_display.append(error_text)
            if self.floating_window:
                self.floating_window.text_edit.append(error_text)
                self.floating_window.text_edit.setFocus()
                pass
