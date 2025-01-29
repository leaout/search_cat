from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, 
                            QTextEdit, QLabel, QVBoxLayout, QWidget,
                            QHBoxLayout,QShortcut)
from PyQt5.QtCore import Qt,QTimer
from PyQt5.QtGui import QKeySequence
import sys
from main import WindowHandler, Ocr, WinOperator, find_best_match, parse_json_lines
from winoperator import MouseClicker
import os
import keyboard  

# class QSearchApp(QMainWindow):
#     def __init__(self):
#         super().__init__()
        
#         # 初始化组件
#         self.handler = WindowHandler()
#         self.ocr = Ocr()
#         self.operator = None
        
#         # 加载答案数据
#         self.answer_set = []
#         for root, dirs, files in os.walk("data"):
#             for file in files:
#                 file_path = os.path.join(root, file)
#                 result = parse_json_lines(file_path)
#                 self.answer_set.extend(result)
        
#         self.init_ui()
#         self.timer = QTimer()
#         self.timer.timeout.connect(self.process_screenshot)
#         self.is_running = False

#     def init_ui(self):
#         self.setWindowTitle('QSearch - 自动答题助手')
#         self.setGeometry(100, 100, 800, 600)
        
#         # 主布局
#         main_layout = QVBoxLayout()
        
#         # 控制按钮
#         btn_layout = QHBoxLayout()
        
#         # 窗口选择
#         self.window_btn = QPushButton('选择窗口')
#         self.window_btn.clicked.connect(self.choose_window)
#         btn_layout.addWidget(self.window_btn)
        
#         # 窗口信息显示
#         self.window_label = QLabel('未选择窗口')
#         btn_layout.addWidget(self.window_label)
        
#         # 开始/停止按钮
#         self.start_btn = QPushButton('开始')
#         self.start_btn.clicked.connect(self.toggle_process)
#         self.start_btn.setEnabled(False)  # 未选择窗口时禁用
#         btn_layout.addWidget(self.start_btn)
        
#         # 状态显示
#         self.status_label = QLabel('状态: 停止')
#         btn_layout.addWidget(self.status_label)
        
#         main_layout.addLayout(btn_layout)
        
#         # 结果显示
#         self.result_display = QTextEdit()
#         self.result_display.setReadOnly(True)
#         main_layout.addWidget(self.result_display)
        
#         # 设置主窗口布局
#         container = QWidget()
#         container.setLayout(main_layout)
#         self.setCentralWidget(container)

#     def toggle_process(self):
#         if self.is_running:
#             self.timer.stop()
#             self.start_btn.setText('开始')
#             self.status_label.setText('状态: 停止')
#         else:
#             self.timer.start(500)  # 每500ms处理一次
#             self.start_btn.setText('停止')
#             self.status_label.setText('状态: 运行中')
#         self.is_running = not self.is_running

#     def choose_window(self):
#         """处理窗口选择"""
#         try:
#             self.handler.choose_window()
#             self.handler.move_and_resize_window(1390, 10, 527, 970)
#             self.window_label.setText("已选择窗口")
#             self.start_btn.setEnabled(True)
#             self.operator = WinOperator(self.handler.window)
#         except Exception as e:
#             self.start_btn.setEnabled(True)
#             self.window_label.setText("窗口选择失败")
#             self.result_display.append(f"窗口选择错误: {str(e)}\n")

#     def process_screenshot(self):
#         if self.operator is None:
#             self.result_display.append("请先选择目标窗口\n")
#             self.toggle_process()  # 自动停止
#             return
            
#         screenshot_data = self.handler.capture_question_screenshot()
#         question = ''.join(self.ocr.do_ocr_ext(screenshot_data, simple=True))
#         #移除：咸鱼游戏
#         question = question.replace("咸鱼游戏", "")
        
#         if len(question) == 0:
#             return
            
#         answer = find_best_match(self.answer_set, question)
#         if answer is not None:
#             result_text = f"{answer['q']} ---> {answer['ans']}\n"
#             self.result_display.append(result_text)
#             self.operator.click_trueorfalse(answer['ans'])
#         else:
#             self.result_display.append("未找到匹配答案\n")

# if __name__ == '__main__':
#     app = QApplication(sys.argv)
#     window = QSearchApp()
#     window.show()
#     sys.exit(app.exec_())
    
    
class QSearchApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 初始化组件
        self.handler = WindowHandler()
        self.ocr = Ocr()
        self.operator = None
        
        # 加载答案数据
        self.answer_set = []
        for root, dirs, files in os.walk("data"):
            for file in files:
                file_path = os.path.join(root, file)
                result = parse_json_lines(file_path)
                self.answer_set.extend(result)
        
        # 初始化鼠标连点器
        self.mouse_clicker = MouseClicker()
        
        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_screenshot)
        self.is_running = False
        # 注册全局快捷键
        keyboard.add_hotkey('ctrl+q', self.toggle_clicker)

    def init_ui(self):
        self.setWindowTitle('QSearch - 自动答题助手')
        self.setGeometry(100, 100, 800, 600)
        
        # 主布局
        main_layout = QVBoxLayout()
        
        # 控制按钮
        btn_layout = QHBoxLayout()
        
        # 窗口选择
        self.window_btn = QPushButton('选择窗口')
        self.window_btn.clicked.connect(self.choose_window)
        btn_layout.addWidget(self.window_btn)
        
        # 窗口信息显示
        self.window_label = QLabel('未选择窗口')
        btn_layout.addWidget(self.window_label)
        
        # 开始/停止按钮
        self.start_btn = QPushButton('开始')
        self.start_btn.clicked.connect(self.toggle_process)
        self.start_btn.setEnabled(False)  # 未选择窗口时禁用
        btn_layout.addWidget(self.start_btn)
        
        # 状态显示
        self.status_label = QLabel('状态: 停止')
        btn_layout.addWidget(self.status_label)
        
        main_layout.addLayout(btn_layout)
        
        # 鼠标连点器控制
        self.clicker_btn = QPushButton('ctrl+q 启动')
        self.clicker_btn.clicked.connect(self.toggle_clicker)
        main_layout.addWidget(self.clicker_btn)
        
        self.clicker_status_label = QLabel('鼠标连点器: 关闭')
        main_layout.addWidget(self.clicker_status_label)
        
        # 结果显示
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        main_layout.addWidget(self.result_display)
        
        # 设置主窗口布局
        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)
        
        # 添加快捷键
        # keyboard.add_hotkey('ctrl+q', self.toggle_clicker)

    def toggle_process(self):
        if self.is_running:
            self.timer.stop()
            self.start_btn.setText('开始')
            self.status_label.setText('状态: 停止')
        else:
            self.timer.start(500)  # 每500ms处理一次
            self.start_btn.setText('停止')
            self.status_label.setText('状态: 运行中')
        self.is_running = not self.is_running

    def choose_window(self):
        """处理窗口选择"""
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

    def process_screenshot(self):
        if self.operator is None:
            self.result_display.append("请先选择目标窗口\n")
            self.toggle_process()  # 自动停止
            return
            
        screenshot_data = self.handler.capture_question_screenshot()
        question = ''.join(self.ocr.do_ocr_ext(screenshot_data, simple=True))
        #移除：咸鱼游戏
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

    def toggle_clicker(self):
        if self.mouse_clicker.is_clicking:
            self.mouse_clicker.stop_clicking()
            self.clicker_btn.setText('ctrl+q 启动')
            self.clicker_status_label.setText('鼠标连点器: 关闭')
        else:
            self.mouse_clicker.start_clicking()
            self.clicker_btn.setText('ctrl+q 停止')
            self.clicker_status_label.setText('鼠标连点器: 运行中')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = QSearchApp()
    window.show()
    sys.exit(app.exec_())
