from typing import Callable, Any, List
import ctypes
from ctypes import wintypes
from numpy import ndarray
import pygetwindow as gw
from PIL import Image
import mss
import time
import tkinter as tk
from tkinter import messagebox
import numpy as np
import win32con
import win32gui
import win32process
import win32ui

def require_window(method: Callable) -> Callable:
    """
    装饰器，用于检查是否已设置窗口。如果未设置窗口，则显示警告信息。

    参数:
    method (Callable): 需要装饰的函数。

    返回:
    Callable: 装饰后的函数。
    """
    def wrapper(self: 'WindowHandler', *args: Any, **kwargs: Any) -> Any:
        if not self.window:
            self.show_message("请先设置窗口。", "warning")
            return
        return method(self, *args, **kwargs)
    return wrapper


class WindowHandler:
    def __init__(self):
        """
        初始化WindowHandler实例，设置初始窗口为None。
        """
        self.window = None
        self.window_info = None

    def list_windows(self) -> List[str]:
        """
        获取所有窗口的标题列表。

        返回:
        List[str]: 窗口标题列表。
        """
        windows = gw.getAllTitles()
        return [title for title in windows if title]  # 忽略空标题
        
    def choose_window(self) -> None:
        """显示包含进程信息和截图预览的窗口选择对话框。"""
        candidates = self._list_window_candidates()
        if not candidates:
            self.show_message("未找到可选择的窗口。", "error")
            return

        try:
            from PyQt5.QtWidgets import QApplication
        except ImportError:
            self.window = candidates[0]['window']
            self.window_info = candidates[0]
            return

        if QApplication.instance() is None:
            self.window = candidates[0]['window']
            self.window_info = candidates[0]
            return
        self._choose_window_qt(candidates)

    def _list_window_candidates(self) -> list:
        """枚举可见顶层窗口，并补充 PID、HWND 和几何信息。"""
        candidates = []
        for window in gw.getAllWindows():
            hwnd = getattr(window, '_hWnd', None)
            title = (getattr(window, 'title', '') or '').strip()
            if not hwnd or not title or not win32gui.IsWindowVisible(hwnd):
                continue
            width = int(window.right - window.left)
            height = int(window.bottom - window.top)
            if width <= 80 or height <= 60:
                continue
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                pid = 0
            candidates.append({
                'window': window,
                'hwnd': int(hwnd),
                'title': title,
                'pid': int(pid),
                'left': int(window.left),
                'top': int(window.top),
                'width': width,
                'height': height,
            })

        candidates.sort(key=lambda item: (item['top'], item['left'], item['title'].lower()))
        title_counts = {}
        for candidate in candidates:
            title = candidate['title']
            title_counts[title] = title_counts.get(title, 0) + 1
            candidate['number'] = title_counts[title]
        return candidates

    @staticmethod
    def capture_window_image(hwnd: int, width: int, height: int) -> np.ndarray:
        """通过窗口句柄抓取窗口画面，避免被其他窗口遮挡。"""
        capture_width = max(1, int(width))
        capture_height = max(1, int(height))
        window_dc = win32gui.GetWindowDC(hwnd)
        source_dc = win32ui.CreateDCFromHandle(window_dc)
        memory_dc = source_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        try:
            bitmap.CreateCompatibleBitmap(source_dc, capture_width, capture_height)
            memory_dc.SelectObject(bitmap)
            print_window = ctypes.windll.user32.PrintWindow
            print_window.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
            print_window.restype = wintypes.BOOL
            rendered = print_window(hwnd, memory_dc.GetSafeHdc(), 2)
            if rendered != 1:
                raise RuntimeError('目标窗口不支持后台预览')
            bitmap_data = bitmap.GetBitmapBits(True)
            image = np.frombuffer(bitmap_data, dtype=np.uint8)
            image = image.reshape((capture_height, capture_width, 4))
            return image[:, :, [2, 1, 0]].copy()
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            memory_dc.DeleteDC()
            source_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, window_dc)

    @staticmethod
    def _capture_window_preview(hwnd: int, width: int, height: int) -> np.ndarray:
        """通过窗口句柄抓取左上角预览，避免被其他窗口遮挡。"""
        preview_width = max(1, min(int(width), 480))
        preview_height = max(1, min(int(height), 300))
        return WindowHandler.capture_window_image(hwnd, preview_width, preview_height)

    def _choose_window_qt(self, candidates: list) -> None:
        from PyQt5.QtCore import QSize, Qt
        from PyQt5.QtGui import QImage, QPixmap
        from PyQt5.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                                     QLineEdit, QListWidget, QListWidgetItem,
                                     QPushButton, QVBoxLayout)

        dialog = QDialog(QApplication.activeWindow())
        dialog.setWindowTitle('选择目标窗口')
        dialog.resize(820, 520)
        root_layout = QVBoxLayout(dialog)
        root_layout.setContentsMargins(20, 18, 20, 18)
        root_layout.setSpacing(12)

        heading = QLabel('选择目标窗口')
        heading.setObjectName('sectionTitle')
        root_layout.addWidget(heading)
        hint = QLabel('同名窗口按屏幕位置编号，通过序号、进程 ID 和左上角人物信息确认。')
        hint.setObjectName('sectionHint')
        root_layout.addWidget(hint)

        search_input = QLineEdit()
        search_input.setPlaceholderText('搜索窗口标题，例如：QQ三国')
        root_layout.addWidget(search_input)

        content_layout = QHBoxLayout()
        window_list = QListWidget()
        window_list.setMinimumWidth(320)
        content_layout.addWidget(window_list, 3)

        preview_layout = QVBoxLayout()
        preview = QLabel('选择窗口后显示左上角预览')
        preview.setAlignment(Qt.AlignCenter)
        preview.setMinimumSize(320, 220)
        preview.setStyleSheet('background: #F7F9FC; border: 1px solid #E1E6EE; border-radius: 8px;')
        preview_layout.addWidget(preview, 1)
        detail_label = QLabel('预览区域：窗口左上角')
        detail_label.setWordWrap(True)
        preview_layout.addWidget(detail_label)
        content_layout.addLayout(preview_layout, 2)
        root_layout.addLayout(content_layout, 1)

        button_layout = QHBoxLayout()
        locate_button = QPushButton('定位窗口')
        refresh_preview_button = QPushButton('刷新预览')
        cancel_button = QPushButton('取消')
        confirm_button = QPushButton('选择此窗口')
        confirm_button.setObjectName('primaryButton')
        button_layout.addWidget(locate_button)
        button_layout.addWidget(refresh_preview_button)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(confirm_button)
        root_layout.addLayout(button_layout)

        def display_text(candidate):
            return f"{candidate['title']}  #{candidate['number']}    PID {candidate['pid']}"

        def populate(filter_text=''):
            window_list.clear()
            keyword = filter_text.strip().lower()
            for index, candidate in enumerate(candidates):
                if keyword and keyword not in candidate['title'].lower():
                    continue
                item = QListWidgetItem(display_text(candidate))
                item.setData(Qt.UserRole, index)
                item.setSizeHint(item.sizeHint().expandedTo(QSize(0, 42)))
                window_list.addItem(item)
            if window_list.count():
                window_list.setCurrentRow(0)

        def current_candidate():
            item = window_list.currentItem()
            return candidates[item.data(Qt.UserRole)] if item else None

        def update_preview():
            candidate = current_candidate()
            if not candidate:
                preview.setText('没有匹配的窗口')
                preview.setPixmap(QPixmap())
                detail_label.clear()
                return
            detail_label.setText(
                f"{candidate['title']}  #{candidate['number']}    PID {candidate['pid']}\n"
                "预览区域：窗口左上角"
            )
            try:
                frame = self._capture_window_preview(
                    candidate['hwnd'], candidate['width'], candidate['height']
                )
                image = QImage(
                    frame.data, frame.shape[1], frame.shape[0], frame.strides[0],
                    QImage.Format_RGB888,
                ).copy()
                pixmap = QPixmap.fromImage(image).scaled(
                    preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                preview.setPixmap(pixmap)
                preview.setText('')
            except Exception as error:
                preview.setPixmap(QPixmap())
                preview.setText(f'预览失败\n{error}')

        def locate_window():
            candidate = current_candidate()
            if not candidate:
                return
            try:
                win32gui.ShowWindow(candidate['hwnd'], win32con.SW_RESTORE)
                win32gui.FlashWindow(candidate['hwnd'], True)
            except Exception as error:
                detail_label.setText(f"定位窗口失败: {error}")

        def accept_selection():
            candidate = current_candidate()
            if not candidate:
                return
            self.window = candidate['window']
            self.window_info = dict(candidate)
            dialog.accept()

        search_input.textChanged.connect(populate)
        window_list.currentItemChanged.connect(lambda *_: update_preview())
        refresh_preview_button.clicked.connect(update_preview)
        locate_button.clicked.connect(locate_window)
        cancel_button.clicked.connect(dialog.reject)
        confirm_button.clicked.connect(accept_selection)
        window_list.itemDoubleClicked.connect(lambda *_: accept_selection())

        populate()
        dialog.exec_()

    @require_window
    def capture_screenshot(self, filename: str = "screenshot.png") -> str:
        """
        捕获当前窗口的截图并保存为文件。

        参数:
        filename (str): 截图文件的保存路径。

        返回:
        str: 截图文件的保存路径。
        """
        self.window.activate()
        time.sleep(1)
        left, top, right, bottom = self.window.left, self.window.top, self.window.right, self.window.bottom
        with mss.mss() as sct:
            monitor = {"top": top, "left": left, "width": right-left, "height": bottom-top}
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            # 保存截图
            img.save(filename)
        return filename
    @require_window
    def capture_question_screenshot(self) -> ndarray:
        """
        捕获当前窗口的截图并保存为文件。

        参数:
        filename (str): 截图文件的保存路径。

        返回:
        str: 截图文件的保存路径。
        """
        # self.window.activate()
        # time.sleep(0.5)
        # y1 =105/970 y2=265/970 x1=left x2=bottom
        x1 = self.window.left
        y1 = 105/970*(self.window.bottom - self.window.top)
        x2 = self.window.right
        y2 = 265/970*(self.window.bottom - self.window.top)
        x1 = int(x1)
        y1 = int(y1)
        x2 = int(x2)
        y2 = int(y2)
        # left, top, right, bottom = self.window.left, self.window.top, self.window.right, self.window.bottom
        with mss.mss() as sct:
            monitor = {"top": y1, "left": x1, "width": x2-x1, "height": y2-y1}
            
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            # img.save("test.png")
            img_array = np.array(img)
            return img_array
        return None
    
    def capture_screenshot_ext(self,x1,y1,x2,y2) -> ndarray:
        """
        捕获当前窗口的截图并返回ndarray。

        """
        left, top, right, bottom = x1, y1, x2, y2
        with mss.mss() as sct:
            monitor = {"top": top, "left": left, "width": right-left, "height": bottom-top}
            
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            img_array = np.array(img)
            return img_array
            

        return None

    @require_window
    def move_and_resize_window(self, x: int, y: int, width: int, height: int) -> None:
        """
        移动并调整窗口大小。

        参数:
        x (int): 窗口的新X坐标。
        y (int): 窗口的新Y坐标。
        width (int): 窗口的新宽度。
        height (int): 窗口的新高度。
        """
        self.window.moveTo(x, y)
        self.window.resizeTo(width, height)

    @require_window
    def minimize_window(self) -> None:
        """
        最小化窗口。
        """
        self.window.minimize()

    @require_window
    def maximize_window(self) -> None:
        """
        最大化窗口。
        """
        self.window.maximize()

    @require_window
    def restore_window(self) -> None:
        """
        还原窗口。
        """
        self.window.restore()

    @require_window
    def close_window(self) -> None:
        """
        关闭窗口。
        """
        self.window.close()

    @require_window
    def focus_window(self) -> None:
        """
        激活并聚焦窗口。
        """
        self.window.activate()
        self.window.restore()

    def show_message(self, message: str, msg_type: str = "info") -> None:
        """
        显示消息框。

        参数:
        message (str): 要显示的消息内容。
        msg_type (str): 消息类型，可以是"info"、"warning"或"error"。
        """
        root = tk.Tk()
        root.withdraw()
        if msg_type == "info":
            messagebox.showinfo("信息", message)
        elif msg_type == "warning":
            messagebox.showwarning("警告", message)
        elif msg_type == "error":
            messagebox.showerror("错误", message)
        root.destroy()


if __name__ == "__main__":
    ws = WindowHandler()
    ws.choose_window()
    ws.capture_screenshot("screenshot.png")
