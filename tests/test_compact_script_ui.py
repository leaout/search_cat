"""Compact UI contracts, without launching automation or a game."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget, QTabWidget
from feature.script_platform_feature import ScriptPlatformFeature


class CompactScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_selector_sync_and_single_detail_pane(self):
        parent = QWidget()
        parent.left_layout = QVBoxLayout(parent)
        feature = ScriptPlatformFeature(parent)
        with patch.object(feature, 'refresh_plugins'), patch.object(feature, '_display_selected_plugin'):
            feature.create_ui()
        feature.plugin_list.addItems(['One', 'Two'])
        feature.plugin_list.setCurrentRow(0)
        feature.plugin_combo.activated[int].emit(1)
        self.assertEqual(feature.plugin_list.currentRow(), 1)
        feature.plugin_list.setCurrentRow(0)
        self.assertEqual(feature.plugin_combo.currentIndex(), 0)
        tabs = feature.group_box.findChildren(QTabWidget)
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0].count(), 2)
        self.assertLess(feature.preview_label.minimumHeight(), 240)
        parent.resize(640, 500)
        parent.show()
        self.app.processEvents()
        self.assertLessEqual(feature.group_box.minimumSizeHint().width(), 640)
        parent.close()
