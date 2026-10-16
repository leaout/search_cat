"""Compact UI contracts, without launching automation or a game."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget, QTabWidget, QScrollArea, QPushButton
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

    def test_official_long_status_keeps_start_button_in_view(self):
        parent = QWidget()
        parent.left_layout = QVBoxLayout(parent)
        feature = ScriptPlatformFeature(parent)
        with patch.object(feature, 'refresh_plugins'):
            feature.create_ui()
        feature.plugin_description.setText('权限：window.bind，screen.capture，keyboard.foreground。' * 8)
        feature.qqsg_data_status.setText('NPC 路由库：60条 · 已采集1图/37 NPC · 小地图[1074,123,200,26] · 任务栏[1076,388,153,77]')
        feature.qqsg_data_panel.show()
        feature.window_selector.addItem('QQ三国客户端长标题角色名字 PID12345 ' * 4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(parent)
        scroll.resize(650, 560)
        scroll.show()
        self.app.processEvents()
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        viewport = scroll.viewport()
        point = feature.start_btn.mapTo(viewport, feature.start_btn.rect().topRight())
        self.assertLess(point.x(), viewport.width())
        for button in feature.qqsg_data_panel.findChildren(QPushButton):
            self.assertLess(button.mapTo(viewport, button.rect().topRight()).x(), viewport.width())
        scroll.close()
