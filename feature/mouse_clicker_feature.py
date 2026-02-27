from PyQt5.QtWidgets import (QPushButton, QLabel, QHBoxLayout, QComboBox, 
                            QLineEdit, QDoubleSpinBox, QVBoxLayout, QGroupBox,
                            QSpinBox, QCheckBox, QWidget, QListWidget, QDialog,
                            QGridLayout, QMessageBox, QInputDialog)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
import keyboard
from core.winoperator import MouseClicker, KeyPresser, PositionPreset, ScriptRecorder, Win32Mouse

class MouseClickerFeature:
    def __init__(self, parent):
        self.parent = parent
        self.mouse_clicker = MouseClicker()
        self.key_presser = KeyPresser()
        self.current_mode = 'mouse'
        self.position_preset = PositionPreset()
        self.script_recorder = ScriptRecorder()
        self.recording = False
        
    def init_ui(self):
        clicker_group = QGroupBox("高级连点器")
        clicker_control_layout = QVBoxLayout(clicker_group)
        
        first_row_layout = QHBoxLayout()
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['鼠标模式', '键盘模式', '位置预设', '脚本回放'])
        self.mode_combo.currentTextChanged.connect(self.change_mode)
        first_row_layout.addWidget(QLabel('模式:'))
        first_row_layout.addWidget(self.mode_combo)
        
        self.click_type_combo = QComboBox()
        self.click_type_combo.addItems(['左键', '右键', '中键', '双击', '三连击'])
        self.click_type_combo.currentTextChanged.connect(self.change_click_type)
        first_row_layout.addWidget(QLabel('点击类型:'))
        first_row_layout.addWidget(self.click_type_combo)
        
        clicker_control_layout.addLayout(first_row_layout)
        
        second_row_layout = QHBoxLayout()
        
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText('输入按键组合，如: a->b-c ->space')
        self.key_input.textChanged.connect(self.change_key)
        second_row_layout.addWidget(QLabel('按键组合:'))
        second_row_layout.addWidget(self.key_input)
        self.key_input.setVisible(False)
        
        clicker_control_layout.addLayout(second_row_layout)
        
        third_row_layout = QHBoxLayout()
        
        self.sequence_delay_input = QDoubleSpinBox()
        self.sequence_delay_input.setRange(0.01, 2.0)
        self.sequence_delay_input.setValue(0.1)
        self.sequence_delay_input.setSingleStep(0.05)
        self.sequence_delay_input.valueChanged.connect(self.change_sequence_delay)
        third_row_layout.addWidget(QLabel('序列延时:'))
        third_row_layout.addWidget(self.sequence_delay_input)
        self.sequence_delay_input.setVisible(False)
        
        self.interval_input = QDoubleSpinBox()
        self.interval_input.setRange(0.001, 10.0)
        self.interval_input.setValue(0.1)
        self.interval_input.setSingleStep(0.01)
        self.interval_input.valueChanged.connect(self.change_interval)
        third_row_layout.addWidget(QLabel('循环延时:'))
        third_row_layout.addWidget(self.interval_input)
        
        clicker_control_layout.addLayout(third_row_layout)
        
        fourth_row_layout = QHBoxLayout()
        
        self.random_offset_input = QSpinBox()
        self.random_offset_input.setRange(0, 50)
        self.random_offset_input.setValue(0)
        self.random_offset_input.setPrefix("±")
        self.random_offset_input.setSuffix("像素")
        self.random_offset_input.valueChanged.connect(self.change_random_offset)
        fourth_row_layout.addWidget(QLabel('随机偏移:'))
        fourth_row_layout.addWidget(self.random_offset_input)
        
        self.max_clicks_input = QSpinBox()
        self.max_clicks_input.setRange(0, 99999)
        self.max_clicks_input.setValue(0)
        self.max_clicks_input.setPrefix("最多 ")
        self.max_clicks_input.setSuffix(" 次 (0=无限)")
        self.max_clicks_input.valueChanged.connect(self.change_max_clicks)
        fourth_row_layout.addWidget(QLabel('点击次数:'))
        fourth_row_layout.addWidget(self.max_clicks_input)
        
        clicker_control_layout.addLayout(fourth_row_layout)
        
        position_row = QHBoxLayout()
        
        self.pos_x_input = QSpinBox()
        self.pos_x_input.setRange(0, 9999)
        self.pos_x_input.setValue(0)
        self.pos_x_input.setPrefix("X: ")
        position_row.addWidget(self.pos_x_input)
        
        self.pos_y_input = QSpinBox()
        self.pos_y_input.setRange(0, 9999)
        self.pos_y_input.setValue(0)
        self.pos_y_input.setPrefix("Y: ")
        position_row.addWidget(self.pos_y_input)
        
        self.get_pos_btn = QPushButton('获取当前位置')
        self.get_pos_btn.clicked.connect(self.get_current_position)
        position_row.addWidget(self.get_pos_btn)
        
        self.apply_pos_btn = QPushButton('应用坐标')
        self.apply_pos_btn.clicked.connect(self.apply_position)
        position_row.addWidget(self.apply_pos_btn)
        
        clicker_control_layout.addLayout(position_row)
        
        preset_row = QHBoxLayout()
        
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(['(无)'] + list(self.position_preset.get_all_presets().keys()))
        preset_row.addWidget(QLabel('位置预设:'))
        preset_row.addWidget(self.preset_combo)
        
        self.save_preset_btn = QPushButton('保存预设')
        self.save_preset_btn.clicked.connect(self.save_preset)
        preset_row.addWidget(self.save_preset_btn)
        
        self.load_preset_btn = QPushButton('加载预设')
        self.load_preset_btn.clicked.connect(self.load_preset)
        preset_row.addWidget(self.load_preset_btn)
        
        clicker_control_layout.addLayout(preset_row)
        
        control_row = QHBoxLayout()
        
        self.clicker_btn = QPushButton('启动连点 (F3)')
        self.clicker_btn.clicked.connect(self.toggle_clicker)
        control_row.addWidget(self.clicker_btn)
        
        self.record_btn = QPushButton('录制脚本 (F4)')
        self.record_btn.clicked.connect(self.toggle_recording)
        control_row.addWidget(self.record_btn)
        
        self.status_label = QLabel('状态: 停止')
        control_row.addWidget(self.status_label)
        
        clicker_control_layout.addLayout(control_row)
        
        self.parent.left_layout.addWidget(clicker_group)
        
        keyboard.add_hotkey('F3', self.toggle_clicker)
        keyboard.add_hotkey('F4', self.toggle_recording)
        
        self.update_ui_state()
    
    def change_mode(self, text):
        if text == '鼠标模式':
            self.current_mode = 'mouse'
        elif text == '键盘模式':
            self.current_mode = 'keyboard'
        elif text == '位置预设':
            self.current_mode = 'preset'
        elif text == '脚本回放':
            self.current_mode = 'script'
        self.update_ui_state()
    
    def update_ui_state(self):
        is_mouse = self.current_mode == 'mouse'
        is_keyboard = self.current_mode == 'keyboard'
        
        self.click_type_combo.setVisible(is_mouse)
        self.key_input.setVisible(is_keyboard)
        self.sequence_delay_input.setVisible(is_keyboard)
        self.random_offset_input.setEnabled(is_mouse)
    
    def change_click_type(self, text):
        click_type_map = {
            '左键': 'left', '右键': 'right', '中键': 'middle',
            '双击': 'double', '三连击': 'triple'
        }
        click_type = click_type_map.get(text, 'left')
        self.mouse_clicker.set_click_type(click_type)
    
    def change_key(self, key):
        self.key_presser.set_key(key)
    
    def change_sequence_delay(self, delay):
        self.key_presser.set_sequence_delay(delay)
    
    def change_interval(self, interval):
        self.mouse_clicker.interval = interval
        self.key_presser.interval = interval
    
    def change_random_offset(self, offset):
        self.mouse_clicker.set_random_offset(offset)
    
    def change_max_clicks(self, max_clicks):
        self.mouse_clicker.set_max_clicks(max_clicks)
    
    def get_current_position(self):
        x, y = Win32Mouse().get_cursor_pos()
        self.pos_x_input.setValue(x)
        self.pos_y_input.setValue(y)
    
    def apply_position(self):
        x = self.pos_x_input.value()
        y = self.pos_y_input.value()
        self.mouse_clicker.set_position(x, y)
    
    def save_preset(self):
        name, ok = QInputDialog.getText(self.parent, '保存预设', '请输入预设名称:')
        if ok and name:
            x = self.pos_x_input.value()
            y = self.pos_y_input.value()
            self.position_preset.add_preset(name, x, y)
            self.preset_combo.addItem(name)
            QMessageBox.information(self.parent, '成功', f'预设 "{name}" 已保存')
    
    def load_preset(self):
        name = self.preset_combo.currentText()
        if name and name != '(无)':
            x, y = self.position_preset.get_preset(name)
            if x is not None:
                self.pos_x_input.setValue(x)
                self.pos_y_input.setValue(y)
                self.apply_position()
    
    def toggle_clicker(self):
        if self.current_mode == 'mouse':
            controller = self.mouse_clicker
        elif self.current_mode == 'keyboard':
            controller = self.key_presser
        else:
            return
            
        if controller.is_clicking:
            controller.stop_clicking()
            self.clicker_btn.setText('启动连点 (F3)')
            self.status_label.setText('状态: 停止')
        else:
            controller.start_clicking()
            self.clicker_btn.setText('停止连点 (F3)')
            self.status_label.setText('状态: 运行中')
    
    def toggle_recording(self):
        if not self.recording:
            self.script_recorder.start_recording()
            self.recording = True
            self.record_btn.setText('停止录制 (F4)')
            self.status_label.setText('状态: 录制中')
        else:
            self.script_recorder.stop_recording()
            self.recording = False
            name, ok = QInputDialog.getText(self.parent, '保存脚本', '请输入脚本名称:')
            if ok and name:
                self.script_recorder.save_script(name)
                QMessageBox.information(self.parent, '成功', f'脚本 "{name}" 已保存')
            self.record_btn.setText('录制脚本 (F4)')
            self.status_label.setText('状态: 停止')
    
    def record_current_action(self, action_type, **kwargs):
        if self.recording:
            self.script_recorder.record_action(action_type, **kwargs)
