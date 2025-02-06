from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, 
                            QTextEdit, QLabel, QVBoxLayout, QWidget,
                            QHBoxLayout,QComboBox)
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QIcon
import sys
import os
import keyboard
from main import WindowHandler, Ocr, WinOperator, find_best_match, parse_json_lines
from winoperator import MouseClicker

class BaseGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('Search Cat')
        self.setGeometry(100, 100, 800, 600)
        self.setWindowIcon(QIcon('icon/icon.png'))
        
        # Main layout
        self.main_layout = QVBoxLayout()
        
        # Container widget
        container = QWidget()
        container.setLayout(self.main_layout)
        self.setCentralWidget(container)

class OCRFeature:
    def __init__(self, parent):
        self.parent = parent
        self.handler = WindowHandler()
        self.operator = None
        self.answer_set = []
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
        
        self.start_btn = QPushButton('开始')
        self.start_btn.clicked.connect(self.toggle_process)
        self.start_btn.setEnabled(False)
        btn_layout.addWidget(self.start_btn)
        
        self.status_label = QLabel('状态: 停止')
        btn_layout.addWidget(self.status_label)
        
        self.parent.main_layout.addLayout(btn_layout)
        
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        self.parent.main_layout.addWidget(self.result_display)

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

    def toggle_process(self):
        if self.is_running:
            self.timer.stop()
            self.start_btn.setText('开始')
            self.status_label.setText('状态: 停止')
        else:
            self.timer.start(500)
            self.start_btn.setText('停止')
            self.status_label.setText('状态: 运行中')
        self.is_running = not self.is_running

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
            self.operator.click_trueorfalse(answer['ans'])
        else:
            self.result_display.append("未找到匹配答案\n")

class MouseClickerFeature:
    def __init__(self, parent):
        self.parent = parent
        self.mouse_clicker = MouseClicker()
        
    def init_ui(self):
        clicker_control_layout = QHBoxLayout()
        
        self.click_type_combo = QComboBox()
        self.click_type_combo.addItems(['左键', '右键'])
        self.click_type_combo.currentTextChanged.connect(self.change_click_type)
        clicker_control_layout.addWidget(QLabel('点击类型:'))
        clicker_control_layout.addWidget(self.click_type_combo)
        
        self.clicker_btn = QPushButton('ctrl+q 启动')
        self.clicker_btn.clicked.connect(self.toggle_clicker)
        clicker_control_layout.addWidget(self.clicker_btn)
        
        self.clicker_status_label = QLabel('鼠标连点器: 关闭')
        clicker_control_layout.addWidget(self.clicker_status_label)
        
        self.parent.main_layout.addLayout(clicker_control_layout)
        
        keyboard.add_hotkey('ctrl+q', self.toggle_clicker)

    def change_click_type(self, text):
        click_type = 'left' if text == '左键' else 'right'
        self.mouse_clicker.set_click_type(click_type)

    def toggle_clicker(self):
        if self.mouse_clicker.is_clicking:
            self.mouse_clicker.stop_clicking()
            self.clicker_btn.setText('ctrl+q 启动')
            self.clicker_status_label.setText('鼠标连点器: 关闭')
        else:
            self.mouse_clicker.start_clicking()
            self.clicker_btn.setText('ctrl+q 停止')
            self.clicker_status_label.setText('鼠标连点器: 运行中')

class QSearchApp(BaseGUI):
    def __init__(self):
        super().__init__()
        self.ocr_feature = OCRFeature(self)
        self.clicker_feature = MouseClickerFeature(self)
        self.ocr_feature.init_ui()
        self.clicker_feature.init_ui()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = QSearchApp()
    window.show()
    sys.exit(app.exec_())
