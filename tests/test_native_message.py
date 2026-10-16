"""Message dialogs must not pull Tk into the Qt desktop distribution."""
import unittest
from unittest.mock import patch
from core.winhandler import WindowHandler


class NativeMessageTests(unittest.TestCase):
    def test_native_dialog_levels_without_real_popup(self):
        with patch('core.winhandler.ctypes.windll.user32.MessageBoxW') as dialog:
            handler = WindowHandler()
            for level, title, icon in [('info', '信息', 0x40), ('warning', '警告', 0x30),
                                       ('error', '错误', 0x10)]:
                handler.show_message('测试', level)
                dialog.assert_called_with(None, '测试', title, icon)
