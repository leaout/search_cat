from typing import Callable, Any, List
import pygetwindow as gw
from PIL import Image
import mss
import time
import tkinter as tk
from tkinter import ttk, messagebox

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

    def list_windows(self) -> List[str]:
        """
        获取所有窗口的标题列表。

        返回:
        List[str]: 窗口标题列表。
        """
        windows = gw.getAllTitles()
        return [title for title in windows if title]  # 忽略空标题
        
    def choose_window(self) -> None:
        """
        显示窗口选择对话框，供用户选择窗口。
        """
        windows = self.list_windows()
        if not windows:
            self.show_message("未找到任何窗口。", "error")
            return
        root = tk.Tk()
        root.title("选择窗口")
        # 设置窗口大小和位置
        window_width = 400
        window_height = 250
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        position_top = int(screen_height / 2 - window_height / 2)
        position_right = int(screen_width / 2 - window_width / 2)
        root.geometry(f"{window_width}x{window_height}+{position_right}+{position_top}")
        root.configure(bg="#F5F5F5")
        # 添加标签
        label = tk.Label(root, text="请选择一个窗口标题：", font=("Arial", 12), bg="#F5F5F5")
        label.pack(pady=20)
        # 添加下拉菜单
        selected_window = tk.StringVar()
        dropdown = ttk.Combobox(root, textvariable=selected_window, values=windows, state='readonly', font=("Arial", 10))
        dropdown.pack(pady=10, padx=20, fill=tk.X)
        dropdown.current(0)
        # 确认按钮回调函数
        def on_select() -> None:
            window_title = selected_window.get()
            for win in gw.getWindowsWithTitle(window_title):
                if win.title == window_title:
                    self.window = win
                    break
            if not self.window:
                self.show_message("未找到指定窗口，请确保窗口标题正确。", "error")
            root.destroy()
        # 添加确认按钮
        button = tk.Button(root, text="确认", command=on_select, font=("SimHei", 12), bg="#4CAF50", fg="white", relief="flat", height=2)
        button.pack(pady=20, padx=20, fill=tk.X)
        # 设置窗口风格
        style = ttk.Style()
        # 使用主题
        style.theme_use("clam")  
        # 调整下拉菜单内边距
        style.configure("TCombobox", padding=5)  
        root.mainloop()

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
    
    def capture_screenshot_ext(self,x1,y1,x2,y2, filename: str = "screenshot.png") -> str:
        """
        捕获当前窗口的截图并保存为文件。

        参数:
        filename (str): 截图文件的保存路径。

        返回:
        str: 截图文件的保存路径。
        """
        left, top, right, bottom = x1, y1, x2, y2
        with mss.mss() as sct:
            monitor = {"top": top, "left": left, "width": right-left, "height": bottom-top}
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            # 保存截图
            img.save(filename)
        return filename

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
        