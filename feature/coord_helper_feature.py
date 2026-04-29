import json
import cv2
import numpy as np
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QPushButton, QLabel, QListWidget, QListWidgetItem,
                             QInputDialog, QMessageBox, QLineEdit)
from PyQt5.QtCore import Qt
import mss
from pygetwindow import getWindowsWithTitle
from pynput import mouse
import threading



CONFIG_FILE = "ui_coords.json"


class CoordHelperFeature:
    def __init__(self, gui):
        self.gui = gui
        self.group_box = None
        self.config = {}
        self.list_widget = None
        self.window_title_edit = None
        self.mouse_listener = None
        self.active = False
        self._stop_requested = False

    def toggle(self):
        self.active = not self.active
        if self.active:
            self.gui.status_bar.showMessage("坐标助手已激活")
        else:
            self.gui.status_bar.showMessage("坐标助手已停止")
            self.stop_listening()

    def stop_listening(self):
        self._stop_requested = True
        if self.mouse_listener:
            try:
                self.mouse_listener.stop()
            except:
                pass

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
        self.mouse_listener = None

        def on_click(x, y, button, pressed):
            if self._stop_requested:
                if self.mouse_listener:
                    self.mouse_listener.stop()
                return
            if not pressed:
                return
            rel_x = x - left
            rel_y = y - top
            print("屏幕坐标(" + str(x) + "," + str(y) + ") -> 窗口相对坐标(" + str(rel_x) + ", " + str(rel_y) + ")")
            name, ok = QInputDialog.getText(self.gui, "保存坐标",
                                                     "相对坐标: (" + str(rel_x) + ", " + str(rel_y) + ")\n输入元素名称（取消停止监听）:")
            if ok and name.strip():
                self.config[name.strip()] = [rel_x, rel_y]
                self.save_config()
                self.update_list()
            # 无论是否保存，都停止监听
            self.stop_listening()

        def listen():
            with mouse.Listener(on_click=on_click) as listener:
                self.mouse_listener = listener
                listener.join()

        thread = threading.Thread(target=listen, daemon=True)
        thread.start()

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

        def draw_rect(event, x, y, flags, param):
            nonlocal drawing, ix, iy, fx, fy
            if event == cv2.EVENT_LBUTTONDOWN:
                drawing = True
                ix, iy = x, y
                fx, fy = x, y
            elif event == cv2.EVENT_MOUSEMOVE and drawing:
                fx, fy = x, y
            elif event == cv2.EVENT_LBUTTONUP:
                drawing = False
                fx, fy = x, y

        cv2.namedWindow("框选区域（拖框选择，C确认，R重置，ESC退出）")
        cv2.setMouseCallback("框选区域（拖框选择，C确认，R重置，ESC退出）", draw_rect)

        while True:
            img = clone.copy()
            if ix != -1 and fx != -1:
                cv2.rectangle(img, (ix, iy), (fx, fy), (0, 255, 0), 2)
                w, h = abs(fx - ix), abs(fy - iy)
                cv2.putText(img, str(w) + "x" + str(h), (ix, iy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.imshow("框选区域（拖框选择，C确认，R重置，ESC退出）", img)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('r'):
                ix, iy, fx, fy = -1, -1, -1, -1
            elif key == ord('c'):
                if ix == -1 or fx == -1:
                    continue
                x1, x2 = min(ix, fx), max(ix, fx)
                y1, y2 = min(iy, fy), max(iy, fy)
                rel_x1 = x1 - left
                rel_y1 = y1 - top
                rel_w = x2 - x1
                rel_h = y2 - y1
                msg = "相对坐标: 左" + str(rel_x1) + ", 上" + str(rel_y1) + ", 宽" + str(rel_w) + ", 高" + str(rel_h)
                name, ok = QInputDialog.getText(self.gui, "保存区域",
                                                        msg + "\n输入区域名称（取消跳过）:")
                if ok and name.strip():
                    self.config[name.strip()] = [rel_x1, rel_y1, rel_w, rel_h]
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
