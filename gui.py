from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                            QWidget, QGroupBox, QTextEdit, QLabel, QPushButton, 
                            QLineEdit, QSpinBox, QCheckBox, QComboBox, QGridLayout,
                            QStatusBar, QFrame, QListWidget)
from PyQt5.QtCore import Qt, QMetaObject, QObject, Q_ARG, QTimer, QDateTime
from PyQt5.QtGui import QIcon, QFont
import sys
import json
import os
import keyboard
from datetime import datetime, timedelta
from feature.ocr_feature import OCRFeature
from feature.mouse_clicker_feature import MouseClickerFeature
from feature.window_key_feature import WindowKeyFeature
from feature.coord_helper_feature import CoordHelperFeature
from feature.yolo_feature import YOLOFeature
from feature.travel_feature import TravelFeature

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
    
    def require_license(self):
        """检查许可证，过期则弹窗提示并返回False"""
        if self.check_license_valid():
            return True
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(
            self, "许可证已过期",
            f"软件试用期已于 {self.expiry_date.strftime('%Y-%m-%d')} 到期，所有功能已禁用。\n"
            "请联系管理员获取新的许可证。"
        )
        return False
    
    def get_remaining_days(self):
        """获取剩余天数"""
        now = datetime.now()
        if now >= self.expiry_date:
            return 0
        remaining = self.expiry_date - now
        return remaining.days + 1  # 包括当天
    
    def init_ui(self):
        self.setWindowTitle('Search Cat')
        self.resize(1120, 720)
        self.setMinimumSize(960, 640)
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
        
        # 快捷键状态显示
        self.hotkey_status_label = QLabel("● 待机 · Home 启停")
        self.hotkey_status_label.setObjectName("runStatus")
        self.status_bar.addPermanentWidget(self.hotkey_status_label)
        
        # 主容器
        container = QWidget()
        container.setObjectName('appRoot')
        self.setCentralWidget(container)
        
        # 主布局
        self.main_layout = QHBoxLayout(container)
        self.main_layout.setContentsMargins(24, 20, 24, 20)
        self.main_layout.setSpacing(20)
        
        # 左侧功能区
        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(14)
        
        # 右侧结果显示区
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(12)
        
        # 设置左右面板比例
        self.main_layout.addWidget(self.left_panel, 3)
        self.main_layout.addWidget(self.right_panel, 2)
        
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
            # 如果是QSearchApp实例，过期后禁用功能
            if hasattr(self, '_update_feature_enabled_state'):
                self._update_feature_enabled_state()
    
    def update_question_count(self, count):
        """更新题库数量显示"""
        self.question_count_label.setText(f"题库: {count}题")

class QSearchApp(BaseGUI):
    def __init__(self):
        super().__init__()
        self.setup_feature_selector()
        self.setup_left_panel()
        self.setup_right_panel()
        
        self.ocr_feature = OCRFeature(self)
        self.ocr_feature.create_ui()
        
        self.clicker_feature = MouseClickerFeature(self)
        self.clicker_feature.create_ui()
        
        self.window_key_feature = WindowKeyFeature(self)
        self.window_key_feature.create_ui()
        
        self.coord_helper_feature = CoordHelperFeature(self)
        self.coord_helper_feature.create_ui()
        
        self.yolo_feature = YOLOFeature(self)
        self.yolo_feature.create_ui()

        self.travel_feature = TravelFeature(self)
        self.travel_feature.create_ui()

        self.left_layout.addStretch()
        
        self.feature_groups = {
            'OCR识别': self.ocr_feature.group_box,
            '连点器': self.clicker_feature.group_box,
            '窗口按键': self.window_key_feature.group_box,
            '坐标助手': self.coord_helper_feature.group_box,
            'YOLO检测': self.yolo_feature.group_box,
            '行脚助手': self.travel_feature.group_box,
        }
        
        self.feature_combo.currentTextChanged.connect(self.switch_feature)
        self.switch_feature('OCR识别')
        
        keyboard.add_hotkey('home', self.toggle_current_feature)
        
        # 启动时检查许可证，过期则禁用功能
        self._update_feature_enabled_state()
        
    def _update_feature_enabled_state(self):
        """根据许可证状态启用/禁用功能按钮"""
        if not hasattr(self, 'start_feature_btn'):
            return
        is_valid = self.check_license_valid()
        self.start_feature_btn.setEnabled(is_valid)
        self.feature_combo.setEnabled(is_valid)
        if not is_valid:
            self.start_feature_btn.setText('已过期')
            self.start_feature_btn.setToolTip('软件试用期已过期，所有功能已禁用')
        # 禁用/启用所有功能模块的group box
        if hasattr(self, 'feature_groups'):
            for group in self.feature_groups.values():
                group.setEnabled(is_valid)
        
    def setup_feature_selector(self):
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(190)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 20, 14, 16)
        sidebar_layout.setSpacing(12)

        title = QLabel('Search Cat')
        title.setObjectName('appTitle')
        subtitle = QLabel('桌面识别与自动化工具')
        subtitle.setObjectName('appSubtitle')
        subtitle.setWordWrap(True)
        sidebar_layout.addWidget(title)
        sidebar_layout.addWidget(subtitle)

        nav_label = QLabel('功能')
        nav_label.setObjectName('navLabel')
        sidebar_layout.addWidget(nav_label)

        self.feature_combo = QListWidget()
        self.feature_combo.setObjectName('featureNav')
        self.feature_combo.addItems([
            'OCR识别', '行脚助手', '连点器',
            '窗口按键', '坐标助手', 'YOLO检测',
        ])
        self.feature_combo.setCurrentRow(0)
        self.feature_combo.setSpacing(3)
        sidebar_layout.addWidget(self.feature_combo, 1)

        self.start_feature_btn = QPushButton('启动当前功能')
        self.start_feature_btn.clicked.connect(self.toggle_current_feature)
        self.start_feature_btn.hide()

        shortcut = QLabel('HOME\n启动 / 停止当前功能')
        shortcut.setObjectName('shortcutBadge')
        shortcut.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(shortcut)

        self.main_layout.insertWidget(0, sidebar)

        page_header = QVBoxLayout()
        self.page_title = QLabel('OCR 识别')
        self.page_title.setObjectName('sectionTitle')
        self.page_hint = QLabel('配置当前功能后，可在右侧查看实时结果')
        self.page_hint.setObjectName('sectionHint')
        page_header.addWidget(self.page_title)
        page_header.addWidget(self.page_hint)
        self.left_layout.insertLayout(0, page_header)
        
    def switch_feature(self, feature_name):
        for name, group in self.feature_groups.items():
            group.setVisible(name == feature_name)
        self.current_feature = feature_name
        self.right_panel.setVisible(feature_name == 'OCR识别')
        display_names = {
            'OCR识别': 'OCR 识别',
            '连点器': '高级连点器',
            '窗口按键': '窗口按键',
            '坐标助手': '坐标助手',
            'YOLO检测': 'YOLO 目标检测',
            '行脚助手': '行脚洞口助手',
        }
        self.page_title.setText(display_names.get(feature_name, feature_name))
        hints = {
            'OCR识别': '按步骤选择窗口和题目区域，建议先测试再启动',
            '连点器': '配置输入方式、执行位置和运行频率',
            '窗口按键': '选择目标窗口并配置循环按键序列',
            '坐标助手': '记录目标窗口内的点坐标和区域',
            'YOLO检测': '加载模型并配置目标检测区域',
            '行脚助手': '识别行脚场景并判断 1–6 号洞口',
        }
        self.page_hint.setText(hints.get(feature_name, '配置当前功能'))
        
    def toggle_current_feature(self):
        if not self.current_feature:
            return
        
        if not self.require_license():
            return
        
        if self.current_feature == 'OCR识别':
            self.ocr_feature.toggle()
        elif self.current_feature == '连点器':
            self.clicker_feature.toggle()
        elif self.current_feature == '窗口按键':
            self.window_key_feature.toggle()
        elif self.current_feature == '坐标助手':
            self.coord_helper_feature.toggle() if hasattr(self.coord_helper_feature, 'toggle') else None
        elif self.current_feature == 'YOLO检测':
            self.yolo_feature.toggle()
        elif self.current_feature == '行脚助手':
            self.travel_feature.toggle()
        
    def setup_left_panel(self):
        """左侧功能面板由各feature自行创建"""
        
    def setup_right_panel(self):
        """设置右侧结果显示面板"""
        result_header = QVBoxLayout()
        result_title = QLabel('实时结果')
        result_title.setObjectName('sectionTitle')
        result_hint = QLabel('识别内容、匹配答案和运行错误会显示在这里')
        result_hint.setObjectName('sectionHint')
        result_header.addWidget(result_title)
        result_header.addWidget(result_hint)
        self.right_layout.addLayout(result_header)

        # 当前结果区域
        current_group = QGroupBox()
        current_group.setObjectName('resultCard')
        current_layout = QVBoxLayout(current_group)
        current_layout.setContentsMargins(18, 18, 18, 18)
        
        self.current_result = QTextEdit()
        self.current_result.setReadOnly(True)
        self.current_result.setPlaceholderText("尚无结果\n\n请在左侧完成配置后先执行一次测试。")
        current_layout.addWidget(self.current_result)
        
        self.right_layout.addWidget(current_group, 1)


APP_STYLE = """
QMainWindow, QWidget#appRoot {
    background: #F4F6F9;
    color: #1B2430;
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
}
QFrame#appHeader, QGroupBox {
    background: #FFFFFF;
    border: 1px solid #E4E9F0;
    border-radius: 12px;
}
QFrame#sidebar {
    background: #FFFFFF;
    border: 1px solid #E4E9F0;
    border-radius: 12px;
}
QFrame#sidebar QLabel#appTitle { color: #172033; font-size: 22px; }
QFrame#sidebar QLabel#appSubtitle { color: #718096; }
QLabel#navLabel {
    color: #8A95A6; font-size: 11px; font-weight: 600;
    padding: 14px 8px 2px 8px;
}
QLabel#appTitle { font-size: 24px; font-weight: 600; color: #172033; }
QLabel#appSubtitle, QLabel#sectionHint { color: #718096; }
QLabel#sectionTitle { font-size: 18px; font-weight: 600; color: #172033; }
QLabel#fieldLabel { font-weight: 600; color: #465268; }
QLabel#stepTitle {
    color: #356AE6; font-size: 14px; font-weight: 600;
    padding-top: 5px;
}
QLabel#modeHint {
    background: #F1F6FF; color: #476181; border-radius: 7px;
    padding: 9px 11px;
}
QLabel#modeHint[warning="true"] { background: #FFF4E8; color: #9A5410; }
QLabel#featureStatus { color: #657086; padding-left: 6px; }
QLabel#shortcutBadge {
    background: #EEF4FF; color: #3268D6; border: 1px solid #D9E6FF;
    border-radius: 7px; padding: 6px 10px; font-size: 11px;
}
QGroupBox {
    margin-top: 10px;
    padding: 18px 14px 14px 14px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 16px; padding: 0 7px;
    color: #334155; background: #F4F6F9;
}
QGroupBox#resultCard { margin-top: 0; padding: 0; }
QPushButton {
    min-height: 36px; padding: 0 14px;
    background: #FFFFFF; border: 1px solid #CDD5E1; border-radius: 7px;
    color: #344054; font-weight: 500;
}
QPushButton:hover { background: #F8FAFC; border-color: #9EABC0; }
QPushButton:pressed { background: #EEF2F7; }
QPushButton:disabled { background: #F2F4F7; color: #A0A8B5; border-color: #E3E7ED; }
QPushButton#primaryButton {
    background: #356AE6; color: #FFFFFF; border-color: #356AE6;
}
QPushButton#primaryButton:hover { background: #285ACB; border-color: #285ACB; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 36px; padding: 0 10px;
    background: #FFFFFF; border: 1px solid #CDD5E1; border-radius: 7px;
    selection-background-color: #356AE6;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 2px solid #356AE6;
}
QComboBox::drop-down { border: 0; width: 28px; }
QTextEdit {
    background: #FBFCFE; border: 0; border-radius: 8px;
    padding: 12px; color: #273449; font-size: 14px;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; }
QStatusBar { background: #FFFFFF; border-top: 1px solid #E4E9F0; color: #657086; }
QStatusBar QLabel { background: transparent; padding: 2px 8px; }
QLabel#runStatus { color: #356AE6; font-weight: 600; }
QListWidget {
    background: #FFFFFF; border: 1px solid #E4E9F0; border-radius: 8px;
    padding: 5px;
}
QListWidget::item { min-height: 32px; border-radius: 5px; padding: 0 8px; }
QListWidget::item:selected { background: #EAF1FF; color: #285ACB; }
QListWidget#featureNav {
    background: transparent; border: 0; padding: 0; color: #465268;
    outline: 0;
}
QListWidget#featureNav::item {
    min-height: 42px; border-radius: 7px; padding-left: 12px;
    font-weight: 500;
}
QListWidget#featureNav::item:hover { background: #F3F6FA; color: #285ACB; }
QListWidget#featureNav::item:selected { background: #EAF1FF; color: #285ACB; }
QFrame#sidebar QLabel#shortcutBadge {
    background: #F6F8FB; color: #64748B; border: 1px solid #E4E9F0;
    padding: 9px 7px;
}
"""

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle('Fusion')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    app.setStyleSheet(APP_STYLE)
    
    window = QSearchApp()
    window.show()
    sys.exit(app.exec_())
