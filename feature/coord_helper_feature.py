import json
import os
import cv2
import numpy as np
from PyQt5.QtWidgets import (QGroupBox, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QListWidget, QListWidgetItem,
                             QInputDialog, QMessageBox, QLineEdit, QDialog)
from PyQt5.QtCore import QObject, pyqtSignal, Qt
from pygetwindow import getWindowsWithTitle
from pynput import mouse
import threading
import mss


CONFIG_FILE = "data/ui_coords.json"


class CoordHelperFeature(QObject):
    coord_ready = pyqtSignal(int, int)  # rel_x, rel_y

    def __init__(self, gui):
        super().__init__()
        self.gui = gui
        self.group_box = None
        self.config = {}
        self.list_widget = None
        self.window_title_edit = None
        self.mouse_listener = None
        self.active = False
        self._stop_requested = False
        self.coord_ready.connect(self.on_coord_ready)

    def on_coord_ready(self, rel_x, rel_y):
        dialog = QDialog(self.gui)
        dialog.setWindowTitle("保存坐标")
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        dialog.setModal(True)
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel("相对坐标: (" + str(rel_x) + ", " + str(rel_y) + ")\n输入元素名称（取消停止监听）:"))
        
        edit = QLineEdit()
        layout.addWidget(edit)
        
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        dialog.setLayout(layout)
        
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        
        if dialog.exec_() == QDialog.Accepted:
            name = edit.text().strip()
            if name:
                self.config[name] = [rel_x, rel_y]
                self.save_config()
                self.update_list()
        self._stop_requested = True

    def toggle(self):
        self.active = not self.active
        if self.active:
            self.gui.status_bar.showMessage("坐标助手已激活")
        else:
            self.gui.status_bar.showMessage("坐标助手已停止")
            self._stop_requested = True

    def create_ui(self):
        self.group_box = QGroupBox("坐标助手")
        layout = QVBoxLayout()

        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel("窗口标题:"))
        self.window_title_edit = QLineEdit("QQ三国")
        title_layout.addWidget(self.window_title_edit)
        layout.addLayout(title_layout)

        btn_layout = QHBoxLayout()
        self.point_btn = QPushButton("点选坐标")
        self.point_btn.clicked.connect(self.start_point_mode)
        btn_layout.addWidget(self.point_btn)

        self.region_btn = QPushButton("框选区域")
        self.region_btn.clicked.connect(self.start_region_mode)
        btn_layout.addWidget(self.region_btn)
        layout.addLayout(btn_layout)

        self.list_widget = QListWidget()
        self.load_config()
        self.update_list()
        layout.addWidget(QLabel("已保存的坐标/区域:"))
        layout.addWidget(self.list_widget)

        del_layout = QHBoxLayout()
        self.del_btn = QPushButton("删除选中")
        self.del_btn.clicked.connect(self.delete_selected)
        del_layout.addWidget(self.del_btn)

        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self.update_list)
        del_layout.addWidget(self.refresh_btn)
        layout.addLayout(del_layout)

        self.group_box.setLayout(layout)
        self.group_box.setVisible(False)
        self.gui.left_layout.addWidget(self.group_box)

    def get_game_window(self):
        title = self.window_title_edit.text().strip()
        windows = getWindowsWithTitle(title)
        if not windows:
            return None
        w = windows[0]
        return (w.left, w.top, w.width, w.height)

    def load_config(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except FileNotFoundError:
            self.config = {}

    def save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
        self.gui.status_bar.showMessage("配置已保存到 " + CONFIG_FILE)

    def update_list(self):
        self.load_config()
        self.list_widget.clear()
        for name, value in self.config.items():
            if len(value) == 2:
                item_text = "【点】" + name + ": (" + str(value[0]) + ", " + str(value[1]) + ")"
            elif len(value) == 4:
                item_text = "【区】" + name + ": 左" + str(value[0]) + ", 上" + str(value[1]) + ", 宽" + str(value[2]) + ", 高" + str(value[3])
            else:
                item_text = "【未知】" + name + ": " + str(value)
            self.list_widget.addItem(QListWidgetItem(item_text))

    def start_point_mode(self):
        win = self.get_game_window()
        if not win:
            QMessageBox.warning(self.gui, "错误", "未找到目标窗口，请先打开窗口")
            return
        left, top, width, height = win
        msg = "窗口位置：左" + str(left) + ", 上" + str(top) + " | 大小：" + str(width) + "x" + str(height)
        self.gui.status_bar.showMessage(msg)
        QMessageBox.information(self.gui, "提示", "进入点选模式\n在游戏窗口点击任意元素\n点击取消停止监听")

        self._stop_requested = False

        def on_click(x, y, button, pressed):
            if self._stop_requested:
                return False
            if not pressed:
                return
            rel_x = x - left
            rel_y = y - top
            print("屏幕坐标(" + str(x) + "," + str(y) + ") -> 窗口相对坐标(" + str(rel_x) + ", " + str(rel_y) + ")")
            self.coord_ready.emit(rel_x, rel_y)
            return False

        def listen_thread():
            with mouse.Listener(on_click=on_click) as listener:
                listener.join()

        threading.Thread(target=listen_thread, daemon=True).start()

    def start_region_mode(self):
        win = self.get_game_window()
        if not win:
            QMessageBox.warning(self.gui, "错误", "未找到目标窗口，请先打开窗口")
            return
        left, top, width, height = win
        msg = "窗口位置：左" + str(left) + ", 上" + str(top) + " | 大小：" + str(width) + "x" + str(height)
        self.gui.status_bar.showMessage(msg)

        monitor = {"left": left, "top": top, "width": width, "height": height}
        with mss.mss() as sct:
            screenshot = np.array(sct.grab(monitor))
            frame = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

        drawing = False
        ix, iy = -1, -1
        fx, fy = -1, -1
        clone = frame.copy()
        region_selected = False

        def draw_rect(event, x, y, flags, param):
            nonlocal drawing, ix, iy, fx, fy, region_selected
            if event == cv2.EVENT_LBUTTONDOWN:
                drawing = True
                ix, iy = x, y
                fx, fy = x, y
                region_selected = False
            elif event == cv2.EVENT_MOUSEMOVE and drawing:
                fx, fy = x, y
            elif event == cv2.EVENT_LBUTTONUP:
                drawing = False
                fx, fy = x, y
                region_selected = True

        cv2.namedWindow("框选区域（拖框选择，C确认，R重置，ESC退出）")
        cv2.setMouseCallback("框选区域（拖框选择，C确认，R重置，ESC退出）", draw_rect)

        while True:
            img = clone.copy()
            if ix != -1 and fx != -1:
                cv2.rectangle(img, (ix, iy), (fx, fy), (0, 255, 0), 2)
                w, h = abs(fx - ix), abs(fy - iy)
                cv2.putText(img, str(w) + "x" + str(h), (ix, iy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                if region_selected:
                    cv2.putText(img, "Press C to confirm", (ix, iy - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
            cv2.imshow("框选区域（拖框选择，C确认，R重置，ESC退出）", img)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('r'):
                ix, iy, fx, fy = -1, -1, -1, -1
                region_selected = False
            elif key == ord('c') and region_selected:
                cv2.destroyAllWindows()
                x1, x2 = min(ix, fx), max(ix, fx)
                y1, y2 = min(iy, fy), max(iy, fy)
                rel_x1 = x1 - left
                rel_y1 = y1 - top
                rel_w = x2 - x1
                rel_h = y2 - y1
                
                dialog = QDialog(self.gui)
                dialog.setWindowTitle("保存区域")
                dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
                dialog.setModal(True)
                
                layout = QVBoxLayout()
                info = "相对坐标: 左" + str(rel_x1) + ", 上" + str(rel_y1) + ", 宽" + str(rel_w) + ", 高" + str(rel_h)
                layout.addWidget(QLabel(info))
                layout.addWidget(QLabel("输入区域名称:"))
                
                edit = QLineEdit()
                layout.addWidget(edit)
                
                btn_layout = QHBoxLayout()
                ok_btn = QPushButton("确定")
                cancel_btn = QPushButton("取消")
                btn_layout.addWidget(ok_btn)
                btn_layout.addWidget(cancel_btn)
                layout.addLayout(btn_layout)
                
                dialog.setLayout(layout)
                
                ok_btn.clicked.connect(dialog.accept)
                cancel_btn.clicked.connect(dialog.reject)
                
                if dialog.exec_() == QDialog.Accepted:
                    name = edit.text().strip()
                    if name:
                        self.config[name] = [rel_x1, rel_y1, rel_w, rel_h]
                        self.save_config()
                        self.update_list()
                break
            elif key == 27:  # ESC
                break
        cv2.destroyAllWindows()

    def delete_selected(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(self.gui, "提示", "请先选择要删除的项")
            return
        for item in selected_items:
            text = item.text()
            if "【点】" in text:
                name = text.split("【点】")[1].split(":")[0].strip()
            elif "【区】" in text:
                name = text.split("【区】")[1].split(":")[0].strip()
            else:
                name = text.split("【未知】")[1].split(":")[0].strip()
            if name in self.config:
                del self.config[name]
        self.save_config()
        self.update_list()
