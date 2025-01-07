from typing import Callable, Any, List, Tuple
import pyautogui
import cv2
import numpy as np

class WinOperator:
    def __init__(self, window=None):
        """
        初始化WinOperator类。

        参数:
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则操作将在整个桌面上进行。
        """
        self.window = window

    def click(self, x: int, y: int, window=None) -> None:
        """
        在指定窗口中的特定位置执行点击操作。

        参数:
        x (int): 相对于窗口左上角的X坐标。
        y (int): 相对于窗口左上角的Y坐标。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        # 确保坐标值为整数
        x = int(round(x))
        y = int(round(y))
        self._perform_action('click', x, y, window)

    def double_click(self, x: int, y: int, window=None) -> None:
        """
        在指定窗口中的特定位置执行双击操作。

        参数:
        x (int): 相对于窗口左上角的X坐标。
        y (int): 相对于窗口左上角的Y坐标。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        self._perform_action('doubleClick', x, y, window)

    def long_click(self, x: int, y: int, duration: float = 2.0, window=None) -> None:
        """
        在指定窗口中的特定位置执行长按操作。

        参数:
        x (int): 相对于窗口左上角的X坐标。
        y (int): 相对于窗口左上角的Y坐标。
        duration (float, optional): 长按的持续时间。默认是2秒。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        self._perform_long_click_action(x, y, duration, window)
        
    def move_to(self, x: int, y: int, window=None) -> None:
        """
        将鼠标移动到指定窗口中的特定位置。

        参数:
        x (int): 相对于窗口左上角的X坐标。
        y (int): 相对于窗口左上角的Y坐标。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        self._perform_action('moveTo', x, y, window)

    def right_click(self, x: int, y: int, window=None) -> None:
        """
        在指定窗口中的特定位置执行右击操作。

        参数:
        x (int): 相对于窗口左上角的X坐标。
        y (int): 相对于窗口左上角的Y坐标。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        self._perform_action('rightClick', x, y, window)

    def scroll(self, clicks: int, window=None) -> None:
        """
        在指定窗口内执行滚动操作。

        参数:
        clicks (int): 滚动的行数。如果为正数，则向上滚动；如果为负数，则向下滚动。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        self._perform_scroll_action(clicks, window)
        
    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5, window=None) -> None:
        """
        在指定窗口内执行滑动操作。

        参数:
        start_x (int): 起始点相对于窗口左上角的X坐标。
        start_y (int): 起始点相对于窗口左上角的Y坐标。
        end_x (int): 终点相对于窗口左上角的X坐标。
        end_y (int): 终点相对于窗口左上角的Y坐标。
        duration (float, optional): 滑动的持续时间。默认是0.5秒。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        self._perform_swipe_action(start_x, start_y, end_x, end_y, duration, window)

    def gesture(self, points: list, duration: float = 0.5, window=None) -> None:
        """
        在指定窗口内执行多个坐标点的手势操作。

        参数:
        points (list): 坐标点列表，每个点是一个元组 (x, y)，相对于窗口左上角的坐标。
        duration (float, optional): 每次移动的持续时间。默认是0.5秒。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        self._perform_gesture_action(points, duration, window)
        
    def _perform_action(self, action: str, x: int, y: int, window=None) -> None:
        """
        执行指定的鼠标操作。

        参数:
        action (str): 要执行的操作名称（如'click', 'doubleClick', 'moveTo', 'rightClick'）。
        x (int): 相对于窗口左上角的X坐标。
        y (int): 相对于窗口左上角的Y坐标。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        target_window = window if window else self.window
        if target_window:
            target_window.activate()
            window_left, window_top = target_window.left, target_window.top
            getattr(pyautogui, action)(window_left + x, window_top + y)
        else:
            getattr(pyautogui, action)(x, y)
    
    def _perform_scroll_action(self, clicks: int, window=None) -> None:
        """
        执行滚动操作。

        参数:
        clicks (int): 滚动的行数。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        target_window = window if window else self.window
        if target_window:
            target_window.activate()
            pyautogui.scroll(clicks)
        else:
            pyautogui.scroll(clicks)
    
    def _perform_swipe_action(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float, window=None) -> None:
        """
        执行滑动操作。

        参数:
        start_x (int): 起始点相对于窗口左上角的X坐标。
        start_y (int): 起始点相对于窗口左上角的Y坐标。
        end_x (int): 终点相对于窗口左上角的X坐标。
        end_y (int): 终点相对于窗口左上角的Y坐标。
        duration (float): 滑动的持续时间。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        target_window = window if window else self.window
        if target_window:
            target_window.activate()
            window_left, window_top = target_window.left, target_window.top
            pyautogui.moveTo(window_left + start_x, window_top + start_y)
            pyautogui.dragTo(window_left + end_x, window_top + end_y, duration=duration)
        else:
            pyautogui.moveTo(start_x, start_y)
            pyautogui.dragTo(end_x, end_y, duration=duration)

    def _perform_gesture_action(self, points: list, duration: float, window=None) -> None:
        """
        执行手势操作。

        参数:
        points (list): 坐标点列表，每个点是一个元组 (x, y)。
        duration (float): 每次移动的持续时间。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        target_window = window if window else self.window
        if target_window:
            target_window.activate()
            window_left, window_top = target_window.left, target_window.top
            for (x, y) in points:
                pyautogui.moveTo(window_left + x, window_top + y, duration=duration)
        else:
            for (x, y) in points:
                pyautogui.moveTo(x, y, duration=duration)
                
    def _perform_long_click_action(self, x: int, y: int, duration: float, window=None) -> None:
        """
        执行长按操作。

        参数:
        x (int): 相对于窗口左上角的X坐标。
        y (int): 相对于窗口左上角的Y坐标。
        duration (float): 长按的持续时间。
        window (object, optional): 通过pygetwindow获取的窗口对象。如果未提供，则使用实例化时的窗口。
        """
        target_window = window if window else self.window
        if target_window:
            target_window.activate()
            window_left, window_top = target_window.left, target_window.top
            pyautogui.mouseDown(window_left + x, window_top + y)
            pyautogui.sleep(duration)
            pyautogui.mouseUp(window_left + x, window_top + y)
        else:
            pyautogui.mouseDown(x, y)
            pyautogui.sleep(duration)
            pyautogui.mouseUp(x, y)
            
    def select_screen_region(self):
        """
        从桌面截图中选取一个块区域并返回坐标信息。

        返回:
        tuple: 包含左上角和右下角坐标的元组 (x1, y1, x2, y2)。
        """
        print("请选择屏幕区域，按下 Enter 键确认...")
        screenshot = pyautogui.screenshot()
        screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        
        # 创建一个与截图相同大小的透明蒙版
        overlay = screenshot.copy()
        cv2.addWeighted(overlay, 0.6, screenshot, 0.2, 0, overlay)  # 设置透明度
        # 显示截图并让用户选择区域，并且取消边框
        roi = cv2.selectROI("select screen region", overlay)
        cv2.destroyWindow("select screen region")

        if roi != (0, 0, 0, 0):
            x, y, width, height = roi
            x1, y1 = x, y
            x2, y2 = x + width, y + height
            print(f"选择的区域坐标: 左上角 (x1={x1}, y1={y1}), 右下角 (x2={x2}, y2={y2})")
            return x1, y1, x2, y2
        else:
            print("未选择任何区域")
            return None
    def click_trueorfalse(self, text, window=None):
        """点击真/假按钮
        
        参数:
        text (str): 'A' 表示真，'B' 表示假
        window (object, optional): 通过pygetwindow获取的窗口对象
        """
        if window is None:
            window = self.window
            
        if window is None:
            raise ValueError("未选择目标窗口")
            
        try:
            window.activate()
            left, top, right, bottom = window.left, window.top, window.right, window.bottom
            
            # 计算按钮坐标并转换为整数
            true_x = int((right - left) * 130 / 527)
            true_y = int((bottom - top) * 785 / 970)
            false_x = int((right - left) * 365 / 527)
            false_y = int((bottom - top) * 785 / 970)
            
            if text == 'A':
                self.click(true_x, true_y, window)
            elif text == 'B':
                self.click(false_x, false_y, window)
            else:
                raise ValueError(f"无效的选项: {text}")
                
        except Exception as e:
            raise RuntimeError(f"点击操作失败: {str(e)}")

if __name__ == "__main__":
  # handler = WinHandler()
  # handler.choose_window()
  # handler.capture_screenshot("screenshot.png")
  # ocr = Ocr()
  # data = ocr.do_ocr("screenshot.png")
  # search_results = ocr.search_text(data, "任务")
  # x, y = search_results[0]['position']['c']
  # operator = WinOperator()
  # operator.click(x, y, handler.window)
  
  operator = WinOperator()
  while True:
      x, y = pyautogui.position()
      operator.click(x, y)
