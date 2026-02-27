from typing import Callable, Any, List, Tuple
import pyautogui
import cv2
import numpy as np
import threading
import keyboard
import time
import random
import json
import os
import win32api
import win32con
import win32gui
import ctypes

user32 = ctypes.windll.user32


class Win32Mouse:
    """高性能Win32鼠标操作类"""
    
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_WHEEL = 0x0800
    MOUSEEVENTF_ABSOLUTE = 0x8000
    
    def __init__(self):
        self.last_click_time = 0
        self.min_click_interval = 0.01
    
    def click(self, x: int = None, y: int = None, button: str = 'left', 
              random_offset: int = 0, duration: float = 0):
        """高性能点击
        Args:
            x, y: 点击坐标，None则点击当前位置
            button: 'left', 'right', 'middle'
            random_offset: 随机偏移范围
            duration: 点击持续时间(长按)
        """
        if x is not None and y is not None:
            if random_offset > 0:
                x += random.randint(-random_offset, random_offset)
                y += random.randint(-random_offset, random_offset)
            self._set_cursor_pos(x, y)
            time.sleep(0.01)
        
        if button == 'left':
            self._left_click(duration)
        elif button == 'right':
            self._right_click(duration)
        elif button == 'middle':
            self._middle_click(duration)
    
    def _set_cursor_pos(self, x: int, y: int):
        """设置鼠标位置"""
        win32api.SetCursorPos((x, y))
    
    def _left_click(self, duration: float = 0):
        """左键点击"""
        win32api.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        if duration > 0:
            time.sleep(duration)
        win32api.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    
    def _right_click(self, duration: float = 0):
        """右键点击"""
        win32api.mouse_event(self.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        if duration > 0:
            time.sleep(duration)
        win32api.mouse_event(self.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    
    def _middle_click(self, duration: float = 0):
        """中键点击"""
        win32api.mouse_event(self.MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
        if duration > 0:
            time.sleep(duration)
        win32api.mouse_event(self.MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)
    
    def double_click(self, x: int = None, y: int = None, button: str = 'left'):
        """双击"""
        self.click(x, y, button)
        time.sleep(0.05)
        self.click(x, y, button)
    
    def triple_click(self, x: int = None, y: int = None, button: str = 'left'):
        """三连击"""
        for _ in range(3):
            self.click(x, y, button)
            time.sleep(0.05)
    
    def double_right_click(self, x: int = None, y: int = None):
        """双击右键"""
        self.click(x, y, 'right')
        time.sleep(0.05)
        self.click(x, y, 'right')
    
    def scroll(self, clicks: int, x: int = None, y: int = None):
        """滚动
        Args:
            clicks: 滚动行数，正数向上，负数向下
        """
        if x is not None and y is not None:
            self._set_cursor_pos(x, y)
            time.sleep(0.01)
        win32api.mouse_event(self.MOUSEEVENTF_WHEEL, 0, 0, clicks * 120, 0)
    
    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, 
             duration: float = 0.3, button: str = 'left'):
        """拖拽
        Args:
            start_x, start_y: 起始坐标
            end_x, end_y: 结束坐标
            duration: 拖拽持续时间
        """
        self._set_cursor_pos(start_x, start_y)
        time.sleep(0.02)
        
        if button == 'left':
            win32api.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        else:
            win32api.mouse_event(self.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        
        steps = max(1, int(duration / 0.01))
        for i in range(steps + 1):
            t = i / steps
            x = int(start_x + (end_x - start_x) * t)
            y = int(start_y + (end_y - start_y) * t)
            self._set_cursor_pos(x, y)
            time.sleep(duration / steps)
        
        if button == 'left':
            win32api.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        else:
            win32api.mouse_event(self.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    
    def get_cursor_pos(self) -> Tuple[int, int]:
        """获取当前鼠标位置"""
        return win32api.GetCursorPos()
    
    def is_in_region(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """检查鼠标是否在指定区域内"""
        x, y = self.get_cursor_pos()
        return x1 <= x <= x2 and y1 <= y <= y2


class Win32Keyboard:
    """高性能Win32键盘操作类"""
    
    def __init__(self):
        self._vk_code_map = {
            'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
            'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
            'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
            'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
            'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59,
            'z': 0x5A, '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33,
            '4': 0x34, '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38,
            '9': 0x39,
            'space': 0x20, 'enter': 0x0D, 'tab': 0x09, 'esc': 0x1B,
            'backspace': 0x08, 'delete': 0x2E, 'insert': 0x2D,
            'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
            'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
            'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
            'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
            'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
            'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10, 'win': 0x5B,
        }
    
    def _get_vk_code(self, key: str) -> int:
        """获取虚拟键码"""
        key = key.lower().strip()
        if key in self._vk_code_map:
            return self._vk_code_map[key]
        if len(key) == 1:
            return ord(key.upper())
        return 0
    
    def press(self, key: str, hold_time: float = 0):
        """按键
        Args:
            key: 按键名称
            hold_time: 按住时间
        """
        vk = self._get_vk_code(key)
        if vk:
            win32api.keybd_event(vk, 0, 0, 0)
            if hold_time > 0:
                time.sleep(hold_time)
            win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    
    def press_combination(self, *keys):
        """组合键
        Args:
            *keys: 按键列表，如 'ctrl', 'c'
        """
        vk_codes = [self._get_vk_code(k) for k in keys if self._get_vk_code(k)]
        
        for vk in vk_codes:
            win32api.keybd_event(vk, 0, 0, 0)
        
        for vk in reversed(vk_codes):
            win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    
    def type_text(self, text: str, interval: float = 0.05):
        """输入文本
        Args:
            text: 要输入的文本
            interval: 每个字符之间的间隔
        """
        for char in text:
            if char == '\n':
                self.press('enter')
            elif char == '\t':
                self.press('tab')
            else:
                vk = self._get_vk_code(char.lower())
                if vk:
                    self.press(char.lower())
                else:
                    keyboard.write(char)
            time.sleep(interval)
    
    def hold_key(self, key: str):
        """按住按键"""
        vk = self._get_vk_code(key)
        if vk:
            win32api.keybd_event(vk, 0, 0, 0)
    
    def release_key(self, key: str):
        """释放按键"""
        vk = self._get_vk_code(key)
        if vk:
            win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)

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
            print("未选择目标窗口")
            return
            
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

class MouseClicker:
    def __init__(self, interval=0.1):
        self.interval = interval
        self.is_clicking = False
        self.click_thread = None
        self.click_type = 'left'
        self.win32_mouse = Win32Mouse()
        self.random_offset = 0
        self.click_count = 0
        self.max_clicks = 0
        self.target_x = None
        self.target_y = None

    def set_click_type(self, click_type):
        if click_type not in ['left', 'right', 'middle']:
            raise ValueError("无效的点击类型")
        self.click_type = click_type

    def set_position(self, x: int = None, y: int = None):
        self.target_x = x
        self.target_y = y

    def set_random_offset(self, offset: int):
        self.random_offset = offset

    def set_max_clicks(self, max_clicks: int):
        self.max_clicks = max_clicks

    def start_clicking(self):
        if not self.is_clicking:
            self.is_clicking = True
            self.click_count = 0
            self.click_thread = threading.Thread(target=self._click_loop, daemon=True)
            self.click_thread.start()

    def stop_clicking(self):
        self.is_clicking = False
        if self.click_thread and self.click_thread.is_alive():
            self.click_thread.join(timeout=1.0)
            if self.click_thread.is_alive():
                self.click_thread = None

    def _click_loop(self):
        while self.is_clicking:
            if self.max_clicks > 0 and self.click_count >= self.max_clicks:
                self.is_clicking = False
                break
            
            if self.target_x is not None and self.target_y is not None:
                self.win32_mouse.click(self.target_x, self.target_y, 
                                       self.click_type, self.random_offset)
            else:
                self.win32_mouse.click(button=self.click_type)
            
            self.click_count += 1
            time.sleep(self.interval)

class KeyPresser(MouseClicker):
    def __init__(self, interval=0.1):
        super().__init__(interval)
        self.key_combination = 'space'
        self.key_sequence = ['space']
        self.sequence_delay = 0.1
        self.win32_keyboard = Win32Keyboard()

    def set_key(self, key_combination):
        self.key_combination = key_combination
        self.key_sequence = self._parse_key_combination(key_combination)

    def set_sequence_delay(self, delay):
        self.sequence_delay = delay

    def _parse_key_combination(self, combination):
        if not combination:
            return [['space']]
            
        sequence = []
        parts = combination.split('->')
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
                
            if '-' in part:
                keys = [k.strip() for k in part.split('-') if k.strip()]
                if keys:
                    sequence.append(keys)
            else:
                sequence.append([part])
                
        return sequence

    def _click_loop(self):
        while self.is_clicking:
            for key_group in self.key_sequence:
                if isinstance(key_group, list) and len(key_group) > 1:
                    self.win32_keyboard.press_combination(*key_group)
                else:
                    key = key_group[0] if isinstance(key_group, list) else key_group
                    self.win32_keyboard.press(key)
                    
                time.sleep(self.sequence_delay)
                
            time.sleep(self.interval)

            time.sleep(self.interval)


class PositionPreset:
    """位置预设管理器"""
    
    def __init__(self, preset_file: str = "data/position_presets.json"):
        self.preset_file = preset_file
        self.presets = self._load_presets()
    
    def _load_presets(self) -> dict:
        if os.path.exists(self.preset_file):
            try:
                with open(self.preset_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_presets(self):
        os.makedirs(os.path.dirname(self.preset_file), exist_ok=True)
        with open(self.preset_file, 'w', encoding='utf-8') as f:
            json.dump(self.presets, f, ensure_ascii=False, indent=2)
    
    def add_preset(self, name: str, x: int, y: int, description: str = ""):
        self.presets[name] = {
            'x': x, 'y': y, 
            'description': description,
            'timestamp': time.time()
        }
        self._save_presets()
    
    def remove_preset(self, name: str):
        if name in self.presets:
            del self.presets[name]
            self._save_presets()
    
    def get_preset(self, name: str) -> tuple:
        if name in self.presets:
            return self.presets[name]['x'], self.presets[name]['y']
        return None, None
    
    def get_all_presets(self) -> dict:
        return self.presets
    
    def get_current_position(self) -> tuple:
        return Win32Mouse().get_cursor_pos()


class ScriptRecorder:
    """脚本录制/回放器"""
    
    def __init__(self, script_file: str = "data/scripts"):
        self.script_file = script_file
        self.recording = False
        self.playing = False
        self.recorded_actions = []
        self.action_types = ['click', 'right_click', 'double_click', 'key_press', 'wait', 'move']
    
    def start_recording(self):
        self.recorded_actions = []
        self.recording = True
    
    def stop_recording(self):
        self.recording = False
    
    def record_action(self, action_type: str, **kwargs):
        if self.recording:
            action = {
                'type': action_type,
                'timestamp': time.time(),
                'data': kwargs
            }
            self.recorded_actions.append(action)
    
    def save_script(self, name: str):
        if not self.recorded_actions:
            return False
        os.makedirs(self.script_file, exist_ok=True)
        file_path = os.path.join(self.script_file, f"{name}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({
                'name': name,
                'actions': self.recorded_actions,
                'created': time.time()
            }, f, ensure_ascii=False, indent=2)
        return True
    
    def load_script(self, name: str) -> list:
        file_path = os.path.join(self.script_file, f"{name}.json")
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('actions', [])
        return []
    
    def list_scripts(self) -> list:
        if not os.path.exists(self.script_file):
            return []
        return [f.replace('.json', '') for f in os.listdir(self.script_file) if f.endswith('.json')]
    
    def play_script(self, actions: list, loop: bool = False, speed: float = 1.0):
        self.playing = True
        mouse = Win32Mouse()
        keyboard = Win32Keyboard()
        
        while self.playing:
            for action in actions:
                if not self.playing:
                    break
                
                action_type = action.get('type')
                data = action.get('data', {})
                
                try:
                    if action_type == 'click':
                        mouse.click(data.get('x'), data.get('y'), data.get('button', 'left'))
                    elif action_type == 'right_click':
                        mouse.click(data.get('x'), data.get('y'), 'right')
                    elif action_type == 'double_click':
                        mouse.double_click(data.get('x'), data.get('y'))
                    elif action_type == 'key_press':
                        keys = data.get('keys', [])
                        if len(keys) > 1:
                            keyboard.press_combination(*keys)
                        elif keys:
                            keyboard.press(keys[0])
                    elif action_type == 'wait':
                        wait_time = data.get('duration', 0.1) / speed
                        time.sleep(wait_time)
                    elif action_type == 'move':
                        mouse._set_cursor_pos(data.get('x'), data.get('y'))
                except Exception as e:
                    print(f"执行动作出错: {e}")
            
            if not loop:
                break
        
        self.playing = False
    
    def stop_playing(self):
        self.playing = False


class ScheduledClicker:
    """定时点击器 - 支持指定时间自动点击"""
    
    def __init__(self):
        self.scheduled_clicks = []
        self.running = False
        self.thread = None
    
    def add_scheduled_click(self, hour: int, minute: int, second: int, 
                           action: callable, repeat: bool = False):
        self.scheduled_clicks.append({
            'hour': hour, 'minute': minute, 'second': second,
            'action': action, 'repeat': repeat
        })
    
    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_schedule, daemon=True)
            self.thread.start()
    
    def stop(self):
        self.running = False
    
    def _run_schedule(self):
        while self.running:
            now = datetime.now()
            for schedule in self.scheduled_clicks:
                if (now.hour == schedule['hour'] and 
                    now.minute == schedule['minute'] and 
                    now.second == schedule['second']):
                    try:
                        schedule['action']()
                    except Exception as e:
                        print(f"执行定时任务出错: {e}")
                    
                    if not schedule['repeat']:
                        self.scheduled_clicks.remove(schedule)
            time.sleep(1)


from datetime import datetime

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
