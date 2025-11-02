from PyQt5.QtWidgets import (QPushButton, QLabel, QHBoxLayout, QComboBox, 
                            QLineEdit, QDoubleSpinBox, QVBoxLayout, QGroupBox)
import keyboard
from core.winoperator import MouseClicker, KeyPresser

class MouseClickerFeature:
    def __init__(self, parent):
        self.parent = parent
        self.mouse_clicker = MouseClicker()
        self.key_presser = KeyPresser()
        self.current_mode = 'mouse'  # 'mouse' or 'keyboard'
        
    def init_ui(self):
        # 创建一个新的组框来容纳原有的控件
        clicker_group = QGroupBox("高级连点器")
        clicker_control_layout = QVBoxLayout(clicker_group)
        
        # 第一行布局
        first_row_layout = QHBoxLayout()
        
        # Mode selection
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['鼠标模式', '键盘模式'])
        self.mode_combo.currentTextChanged.connect(self.change_mode)
        first_row_layout.addWidget(QLabel('模式:'))
        first_row_layout.addWidget(self.mode_combo)
        
        # Mouse click type
        self.click_type_combo = QComboBox()
        self.click_type_combo.addItems(['左键', '右键'])
        self.click_type_combo.currentTextChanged.connect(self.change_click_type)
        first_row_layout.addWidget(QLabel('点击类型:'))
        first_row_layout.addWidget(self.click_type_combo)
        
        # 第二行布局
        second_row_layout = QHBoxLayout()
        
        # Key selection - replaced with text input for key combinations
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText('输入按键组合，如: a->b-c ->space')
        self.key_input.textChanged.connect(self.change_key)
        second_row_layout.addWidget(QLabel('按键组合:'))
        second_row_layout.addWidget(self.key_input)
        self.key_input.setVisible(False)
        
        # 第三行布局
        third_row_layout = QHBoxLayout()
        
        # Sequence delay input
        self.sequence_delay_input = QDoubleSpinBox()
        self.sequence_delay_input.setRange(0.01, 2.0)
        self.sequence_delay_input.setValue(0.1)
        self.sequence_delay_input.setSingleStep(0.05)
        self.sequence_delay_input.valueChanged.connect(self.change_sequence_delay)
        third_row_layout.addWidget(QLabel('序列延时(秒):'))
        third_row_layout.addWidget(self.sequence_delay_input)
        self.sequence_delay_input.setVisible(False)
        
        # Interval input
        self.interval_input = QDoubleSpinBox()
        self.interval_input.setRange(0.01, 10.0)
        self.interval_input.setValue(0.1)
        self.interval_input.setSingleStep(0.1)
        self.interval_input.valueChanged.connect(self.change_interval)
        third_row_layout.addWidget(QLabel('循环延时(秒):'))
        third_row_layout.addWidget(self.interval_input)
        
        # 第四行布局
        fourth_row_layout = QHBoxLayout()
        
        # Control button
        self.clicker_btn = QPushButton('ctrl+q 启动')
        self.clicker_btn.clicked.connect(self.toggle_clicker)
        fourth_row_layout.addWidget(self.clicker_btn)
        
        # Status label
        self.clicker_status_label = QLabel('连点器: 关闭')
        fourth_row_layout.addWidget(self.clicker_status_label)
        
        # 将所有行布局添加到主布局
        clicker_control_layout.addLayout(first_row_layout)
        clicker_control_layout.addLayout(second_row_layout)
        clicker_control_layout.addLayout(third_row_layout)
        clicker_control_layout.addLayout(fourth_row_layout)
        
        # 将组框添加到父布局中
        self.parent.left_layout.addWidget(clicker_group)
        
        # 设置热键
        keyboard.add_hotkey('ctrl+q', self.toggle_clicker)

    def change_mode(self, text):
        self.current_mode = 'mouse' if text == '鼠标模式' else 'keyboard'
        self.click_type_combo.setVisible(self.current_mode == 'mouse')
        self.key_input.setVisible(self.current_mode == 'keyboard')
        self.sequence_delay_input.setVisible(self.current_mode == 'keyboard')
        
    def change_click_type(self, text):
        click_type = 'left' if text == '左键' else 'right'
        self.mouse_clicker.set_click_type(click_type)

    def change_key(self, key):
        self.key_presser.set_key(key)

    def change_sequence_delay(self, delay):
        self.key_presser.set_sequence_delay(delay)

    def change_interval(self, interval):
        self.mouse_clicker.interval = interval
        self.key_presser.interval = interval

    def toggle_clicker(self):
        if self.current_mode == 'mouse':
            controller = self.mouse_clicker
        else:
            controller = self.key_presser
            
        if controller.is_clicking:
            controller.stop_clicking()
            self.clicker_btn.setText('ctrl+q 启动')
            self.clicker_status_label.setText('连点器: 关闭')
        else:
            controller.start_clicking()
            self.clicker_btn.setText('ctrl+q 停止')
            self.clicker_status_label.setText('连点器: 运行中')