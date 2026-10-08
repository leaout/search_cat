"""Capture cleanup checks without capturing or controlling a real window."""
import unittest
from unittest.mock import Mock, patch

from core.winhandler import WindowHandler


class CaptureResourceTests(unittest.TestCase):
    def _exercise(self, rendered):
        events = []
        source, memory, bitmap = Mock(), Mock(), Mock()
        source.CreateCompatibleDC.return_value = memory
        memory.SelectObject.side_effect = lambda value: events.append(('select', value)) or 'original'
        memory.DeleteDC.side_effect = lambda: events.append(('memory', None))
        source.DeleteDC.side_effect = lambda: events.append(('source', None))
        bitmap.GetHandle.return_value = 456
        bitmap.GetBitmapBits.return_value = bytes([1, 2, 3, 255] * 4)
        print_window = Mock(return_value=rendered)
        with patch('core.winhandler.win32gui.GetWindowDC', return_value=123), \
                patch('core.winhandler.win32ui.CreateDCFromHandle', return_value=source), \
                patch('core.winhandler.win32ui.CreateBitmap', return_value=bitmap), \
                patch('core.winhandler.win32gui.DeleteObject',
                      side_effect=lambda value: events.append(('bitmap', value))), \
                patch('core.winhandler.win32gui.ReleaseDC',
                      side_effect=lambda *args: events.append(('release', None))), \
                patch('core.winhandler.ctypes.windll.user32.PrintWindow', print_window):
            if rendered:
                image = WindowHandler.capture_window_image(999, 2, 2)
                self.assertEqual(image[0, 0].tolist(), [3, 2, 1])
                self.assertTrue(image.flags['C_CONTIGUOUS'])
            else:
                with self.assertRaises(RuntimeError):
                    WindowHandler.capture_window_image(999, 2, 2)
        self.assertEqual(events[1:], [('select', 'original'), ('bitmap', 456),
                                     ('memory', None), ('source', None), ('release', None)])

    def test_success_restores_bitmap_before_deleting(self):
        self._exercise(1)

    def test_failed_capture_also_releases_resources(self):
        self._exercise(0)
