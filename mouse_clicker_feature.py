from PyQt5.QtWidgets import (QPushButton, QLabel, QHBoxLayout, QComboBox)
import keyboard
from winoperator import MouseClicker

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
        
        self.parent.clicker_layout.addLayout(clicker_control_layout)
        
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
