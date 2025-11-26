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
        
        # 注意：这里移除了原有的鼠标连点器界面创建代码
        # 连点器界面将在 MouseClickerFeature 中创建
        
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
        
        # 添加伸缩空间使当前结果区域占据整个右侧面板
        self.right_layout.addStretch()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle('Fusion')
    
    window = QSearchApp()
    window.show()
    sys.exit(app.exec_())