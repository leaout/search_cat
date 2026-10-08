"""Real Qt selection/preview regressions; Windows capture and all input are mocked."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

try:
    import numpy as np
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication, QDialog, QDialogButtonBox, QVBoxLayout, QWidget
    from feature import automation_feature as module
except ModuleNotFoundError:
    QApplication = None


@unittest.skipIf(QApplication is None, 'Windows GUI dependencies unavailable')
class AutomationWindowSelectionQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if not isinstance(cls.app, QApplication):
            raise unittest.SkipTest('Requires QApplication, not an existing QCoreApplication')

    def setUp(self):
        self.windows = [
            {'hwnd': 1001, 'pid': 11, 'title': 'QQ三国 7线', 'number': 1},
            {'hwnd': 1002, 'pid': 22, 'title': 'QQ三国 7线', 'number': 2},
        ]
        self.patches = [
            patch.object(module.win32gui, 'IsWindow', return_value=True),
            patch.object(module.win32gui, 'GetWindowRect', return_value=(0, 0, 1280, 960)),
            patch.object(module.WindowHandler, '_capture_window_preview',
                         return_value=np.full((300, 480, 3), 120, dtype=np.uint8)),
        ]
        self.is_window, self.rect, self.capture = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
            dialog.deleteLater()
        self.app.processEvents()

    def dialog(self, existing=None):
        dialog = module.AutomationWindowDialog(self.windows, existing or set())
        self.dialogs.append(dialog)
        dialog.show()
        self.app.processEvents()
        return dialog

    def click_row(self, dialog, index, modifiers=Qt.NoModifier):
        item = dialog.choices.item(index)
        QTest.mouseClick(dialog.choices.viewport(), Qt.LeftButton, modifiers,
                         dialog.choices.visualItemRect(item).center())
        self.app.processEvents()

    def feature(self):
        container = QWidget()
        self.dialogs.append(container)
        parent = SimpleNamespace(left_layout=QVBoxLayout(container))
        config = {'profiles': {'默认方案': dict(module.DEFAULT_PROFILE)},
                  'active_profile': '默认方案', 'last_window': None}
        with patch.object(module.AutomationFeature, '_load_config', return_value=config):
            feature = module.AutomationFeature(parent)
        save = patch.object(feature, '_write_config')
        save.start()
        self.addCleanup(save.stop)
        feature.create_ui()
        return feature

    def test_single_row_click_adds_without_a_checkbox(self):
        dialog = self.dialog()
        self.assertFalse(dialog.buttons.button(QDialogButtonBox.Ok).isEnabled())
        self.click_row(dialog, 1)
        self.assertEqual([i['hwnd'] for i in dialog.selected_windows()], [1002])
        self.assertTrue(dialog.buttons.button(QDialogButtonBox.Ok).isEnabled())
        QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_ctrl_click_keeps_multiple_selected_rows(self):
        dialog = self.dialog()
        self.click_row(dialog, 0)
        self.click_row(dialog, 1, Qt.ControlModifier)
        self.assertEqual({i['hwnd'] for i in dialog.selected_windows()}, {1001, 1002})
        self.assertEqual(dialog.selection_label.text(), '已选择 2 个窗口')

    def test_empty_selection_cannot_accept(self):
        dialog = self.dialog()
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertTrue(dialog.isVisible())
        self.assertIn('至少一个', dialog.selection_label.text())

    def test_filter_does_not_add_hidden_selected_windows(self):
        dialog = self.dialog({1001, 1002})
        dialog.search.setText('PID 22')
        self.assertEqual([i['hwnd'] for i in dialog.selected_windows()], [1002])
        dialog.search.setText('没有这个窗口')
        self.assertEqual(dialog.selected_windows(), [])
        self.assertFalse(dialog.buttons.button(QDialogButtonBox.Ok).isEnabled())

    def test_switching_rows_updates_portrait_and_identity(self):
        dialog = self.dialog()
        self.click_row(dialog, 0)
        self.assertFalse(dialog.preview.pixmap().isNull())
        self.assertIn('PID 11', dialog.detail.text())
        self.click_row(dialog, 1)
        self.assertFalse(dialog.preview.pixmap().isNull())
        self.assertIn('PID 22', dialog.detail.text())
        self.capture.assert_called_with(1002, 1280, 960)

    def test_preview_failure_does_not_prevent_adding(self):
        dialog = self.dialog()
        self.capture.side_effect = RuntimeError('后台截图不支持')
        self.click_row(dialog, 1)
        self.assertIn('预览失败', dialog.preview.text())
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.selected_windows()[0]['hwnd'], 1002)

    def test_feature_receives_selection_and_only_dialog_has_preview(self):
        feature = self.feature()

        def select_and_accept(dialog):
            dialog.show()
            self.app.processEvents()
            self.click_row(dialog, 1)
            dialog.accept()
            return dialog.result()

        with patch.object(module.WindowHandler, 'list_window_candidates', return_value=self.windows):
            with patch.object(module.AutomationWindowDialog, 'exec_', select_and_accept):
                feature.choose_window()
        self.assertEqual([i['hwnd'] for i in feature.target_windows], [1002])
        self.assertEqual(feature.window_label.text(), '已添加 1 个窗口')
        self.assertIn('本次新增 1', feature.status_label.text())
        self.assertFalse(hasattr(feature, 'window_preview'))
        self.assertEqual(feature.selected_hwnd, 1002)
        feature.clear_windows()
        self.assertEqual(feature.window_label.text(), '已添加 0 个窗口')
        self.assertIsNone(feature.selected_hwnd)

    def test_main_window_list_changes_do_not_capture_screenshots(self):
        feature = self.feature()
        feature._add_windows(self.windows)
        feature.window_list.setCurrentRow(1)
        feature.clear_windows()
        self.capture.assert_not_called()

    def test_cancel_preserves_added_windows(self):
        feature = self.feature()
        feature._add_windows([self.windows[0]])
        with patch.object(module.WindowHandler, 'list_window_candidates', return_value=self.windows):
            with patch.object(module.AutomationWindowDialog, 'exec_', return_value=QDialog.Rejected):
                feature.choose_window()
        self.assertEqual([i['hwnd'] for i in feature.target_windows], [1001])

    def test_preview_is_on_demand_not_a_continuous_screenshot_loop(self):
        dialog = self.dialog()
        self.click_row(dialog, 1)
        count = self.capture.call_count
        QTest.qWait(200)
        self.assertEqual(self.capture.call_count, count)
        QTest.mouseClick(dialog.refresh, Qt.LeftButton)
        self.assertEqual(self.capture.call_count, count + 1)


if __name__ == '__main__':
    unittest.main()
