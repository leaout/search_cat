from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                            QWidget, QGroupBox, QTextEdit, QLabel, QPushButton, 
                            QLineEdit, QSpinBox, QCheckBox, QComboBox, QGridLayout)
from PyQt5.QtCore import Qt, QMetaObject, QObject, Q_ARG
from PyQt5.QtGui import QIcon, QFont
import sys
from feature.ocr_feature import OCRFeature
from feature.mouse_clicker_feature import MouseClickerFeature

class BaseGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('Search Cat - 多功能工具箱')
        self.setGeometry(100, 100, 800, 600)
        self.setWindowIcon(QIcon('icon/icon.png'))
        
        # 主容器
        container = QWidget()
        self.setCentralWidget(container)
        
        # 主布局
        self.main_layout = QHBoxLayout(container)
        
        # 左侧功能区
        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 右侧结果显示区
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        
        # 设置左右面板比例
        self.main_layout.addWidget(self.left_panel, 2)  # 左侧占2份
        self.main_layout.addWidget(self.right_panel, 1)  # 右侧占1份

class QSearchApp(BaseGUI):
    def __init__(self):
        super().__init__()
        self.setup_left_panel()
        self.setup_right_panel()
        
        # 初始化功能模块
        self.ocr_feature = OCRFeature(self)
        self.ocr_feature.init_ui()
        
        self.clicker_feature = MouseClickerFeature(self)
        self.clicker_feature.init_ui()
        
    def setup_left_panel(self):
        """设置左侧功能面板"""
        # OCR功能组
        ocr_group = QGroupBox("OCR 识图搜索")
        ocr_layout = QVBoxLayout(ocr_group)
        
        # 窗口选择区域
        window_layout = QHBoxLayout()
        self.window_btn = QPushButton('选择窗口')
        self.window_label = QLabel('未选择窗口')
        window_layout.addWidget(self.window_btn)
        window_layout.addWidget(self.window_label)
        ocr_layout.addLayout(window_layout)
        
        # 区域选择区域
        region_layout = QHBoxLayout()
        self.region_btn = QPushButton('选择区域')
        self.region_label = QLabel('未选择区域')
        region_layout.addWidget(self.region_btn)
        region_layout.addWidget(self.region_label)
        ocr_layout.addLayout(region_layout)
        
        # 控制按钮区域
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton('开始 OCR (F1)')
        self.status_label = QLabel('状态: 停止')
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.status_label)
        ocr_layout.addLayout(control_layout)
        
        # 添加到左侧布局
        self.left_layout.addWidget(ocr_group)
        
        # 鼠标连点器功能组
        clicker_group = QGroupBox("鼠标连点器")
        clicker_layout = QGridLayout(clicker_group)
        
        # 坐标设置
        clicker_layout.addWidget(QLabel("X坐标:"), 0, 0)
        self.x_spin = QSpinBox()
        self.x_spin.setRange(0, 9999)
        clicker_layout.addWidget(self.x_spin, 0, 1)
        
        clicker_layout.addWidget(QLabel("Y坐标:"), 0, 2)
        self.y_spin = QSpinBox()
        self.y_spin.setRange(0, 9999)
        clicker_layout.addWidget(self.y_spin, 0, 3)
        
        # 点击设置
        clicker_layout.addWidget(QLabel("点击次数:"), 1, 0)
        self.click_count = QSpinBox()
        self.click_count.setRange(1, 9999)
        self.click_count.setValue(10)
        clicker_layout.addWidget(self.click_count, 1, 1)
        
        clicker_layout.addWidget(QLabel("间隔(ms):"), 1, 2)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(10, 10000)
        self.interval_spin.setValue(100)
        clicker_layout.addWidget(self.interval_spin, 1, 3)
        
        # 点击按钮
        self.click_btn = QPushButton("开始点击 (F2)")
        clicker_layout.addWidget(self.click_btn, 2, 0, 1, 4)
        
        # 模式选择
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("点击模式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["左键单击", "右键单击", "左键双击"])
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()
        clicker_layout.addLayout(mode_layout, 3, 0, 1, 4)
        
        # 选项
        option_layout = QHBoxLayout()
        self.repeat_check = QCheckBox("重复执行")
        self.repeat_check.setChecked(True)
        option_layout.addWidget(self.repeat_check)
        option_layout.addStretch()
        clicker_layout.addLayout(option_layout, 4, 0, 1, 4)
        
        self.left_layout.addWidget(clicker_group)
        
        # 添加伸缩空间使布局更紧凑
        self.left_layout.addStretch()
        
    def setup_right_panel(self):
        """设置右侧结果显示面板"""
        # 当前结果区域
        current_group = QGroupBox("当前结果")
        current_layout = QVBoxLayout(current_group)
        
        self.current_result = QTextEdit()
        self.current_result.setReadOnly(True)
        self.current_result.setPlaceholderText("当前识别结果将显示在这里...")
        self.current_result.setMaximumHeight(120)  # 设置合适的高度
        self.current_result.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa; 
                border: 2px solid #dee2e6; 
                padding: 10px; 
                font-size: 14px;
                border-radius: 5px;
            }
        """)
        current_layout.addWidget(self.current_result)
        
        self.right_layout.addWidget(current_group)
        
        # 操作日志区域
        log_group = QGroupBox("操作日志")
        log_layout = QVBoxLayout(log_group)
        
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMaximumHeight(250)
        self.log_display.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa; 
                border: 1px solid #dee2e6; 
                padding: 5px;
                font-family: Consolas, monospace;
            }
        """)
        log_layout.addWidget(self.log_display)
        
        # 日志控制按钮
        log_control_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("清空日志")
        self.export_log_btn = QPushButton("导出日志")
        log_control_layout.addWidget(self.clear_log_btn)
        log_control_layout.addWidget(self.export_log_btn)
        log_control_layout.addStretch()
        log_layout.addLayout(log_control_layout)
        
        self.right_layout.addWidget(log_group)
        
        # 状态信息区域
        status_group = QGroupBox("系统状态")
        status_layout = QVBoxLayout(status_group)
        
        self.system_status = QLabel("系统就绪")
        self.system_status.setStyleSheet("""
            QLabel {
                background-color: #e9ecef; 
                border: 1px solid #ced4da; 
                padding: 8px;
                border-radius: 4px;
            }
        """)
        status_layout.addWidget(self.system_status)
        
        # 统计信息
        stats_layout = QHBoxLayout()
        stats_layout.addWidget(QLabel("OCR执行:"))
        self.ocr_count = QLabel("0")
        stats_layout.addWidget(self.ocr_count)
        stats_layout.addStretch()
        
        stats_layout.addWidget(QLabel("点击次数:"))
        self.click_count_display = QLabel("0")
        stats_layout.addWidget(self.click_count_display)
        status_layout.addLayout(stats_layout)
        
        self.right_layout.addWidget(status_group)
        
        # 添加伸缩空间
        self.right_layout.addStretch()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle('Fusion')
    
    window = QSearchApp()
    window.show()
    sys.exit(app.exec_())