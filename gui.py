from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout,
                            QWidget, QTabWidget)
from PyQt5.QtCore import Qt,QMetaObject,QObject, Q_ARG
from PyQt5.QtGui import QIcon
import sys
from ocr_feature import OCRFeature
from mouse_clicker_feature import MouseClickerFeature

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

class QSearchApp(BaseGUI):
    def __init__(self):
        super().__init__()
         # Create tab widget
        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)
        
        # OCR Tab
        self.ocr_tab = QWidget()
        self.ocr_layout = QVBoxLayout(self.ocr_tab)
        self.ocr_feature = OCRFeature(self)
        self.ocr_feature.init_ui()
        self.tabs.addTab(self.ocr_tab, "OCR 识图搜索")
        
        # Mouse Clicker Tab
        self.clicker_tab = QWidget()
        self.clicker_layout = QVBoxLayout(self.clicker_tab)
        self.clicker_feature = MouseClickerFeature(self)
        self.clicker_feature.init_ui()
        self.tabs.addTab(self.clicker_tab, "鼠标连点器")
        
    # def call_in_main_thread(self, callback):
    #     """Execute a callback in the main thread"""
    #     QMetaObject.invokeMethod(self, "_execute_callback", 
    #                            Qt.QueuedConnection,
    #                            Q_ARG(object, callback))
        
    # def _execute_callback(self, callback):
    #     """Internal method to execute the callback"""
    #     callback()
        
       

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = QSearchApp()
    window.show()
    sys.exit(app.exec_())
