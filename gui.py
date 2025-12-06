from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                            QWidget, QGroupBox, QTextEdit, QLabel, QPushButton, 
                            QLineEdit, QSpinBox, QCheckBox, QComboBox, QGridLayout,
                            QStatusBar)
from PyQt5.QtCore import Qt, QMetaObject, QObject, Q_ARG, QTimer, QDateTime
from PyQt5.QtGui import QIcon, QFont
import sys
import json
import os
from datetime import datetime, timedelta
from feature.ocr_feature import OCRFeature
from feature.mouse_clicker_feature import MouseClickerFeature

class BaseGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.license_file = "license.json"
        self.expiry_date = self.load_license()
        self.init_ui()
        
    def load_license(self):
        """加载许可证信息，如果不存在则创建默认许可证（30天试用）"""
        default_expiry = datetime.now() + timedelta(days=30)
        
        if not os.path.exists(self.license_file):
            # 创建默认许可证
            license_data = {
                "created": datetime.now().isoformat(),
                "expiry": default_expiry.isoformat(),
                "type": "trial"
            }
            with open(self.license_file, 'w', encoding='utf-8') as f:
                json.dump(license_data, f, ensure_ascii=False, indent=2)
            return default_expiry
        
        try:
            with open(self.license_file, 'r', encoding='utf-8') as f:
                license_data = json.load(f)
                expiry_str = license_data.get("expiry", default_expiry.isoformat())
                return datetime.fromisoformat(expiry_str)
        except Exception as e:
            print(f"加载许可证失败: {e}")
            return default_expiry
    
    def check_license_valid(self):
        """检查许可证是否有效"""
        now = datetime.now()
        return now < self.expiry_date
    
    def get_remaining_days(self):
        """获取剩余天数"""
        now = datetime.now()
        if now >= self.expiry_date:
            return 0
        remaining = self.expiry_date - now
        return remaining.days + 1  # 包括当天
    
    def init_ui(self):
        self.setWindowTitle('Search Cat - 多功能工具箱')
        self.setGeometry(100, 100, 800, 600)
        self.setWindowIcon(QIcon('icon/icon.png'))
        
        # 创建状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # 许可证状态标签
        self.license_label = QLabel()
        self.update_license_display()
        self.status_bar.addPermanentWidget(self.license_label)
        
        # 题库加载数量标签
        self.question_count_label = QLabel("题库: 加载中...")
        self.status_bar.addPermanentWidget(self.question_count_label)
        
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
        self.main_layout.addWidget(self.right_panel, 1)  # 右侧占1份)
        
        # 创建定时器更新许可证显示
        self.license_timer = QTimer()
        self.license_timer.timeout.connect(self.update_license_display)
        self.license_timer.start(60000)  # 每分钟更新一次
    
    def update_license_display(self):
        """更新许可证显示"""
        if self.check_license_valid():
            remaining_days = self.get_remaining_days()
            expiry_str = self.expiry_date.strftime("%Y-%m-%d %H:%M")
            self.license_label.setText(f"到期时间: {expiry_str} (剩余{remaining_days}天)")
            self.license_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.license_label.setText("软件已过期!")
            self.license_label.setStyleSheet("color: red; font-weight: bold;")
    
    def update_question_count(self, count):
        """更新题库数量显示"""
        self.question_count_label.setText(f"题库: {count}题")

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
