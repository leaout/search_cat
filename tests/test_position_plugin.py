"""Portable tests for multi-client location isolation and collapsed minimaps."""

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from automation import qqsg_code_navigation as reader
from plugin_platform.manager import PluginManager, PluginManifest
from plugin_platform.sdk import WindowAPI

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('position_plugin',
        ROOT / 'plugins/com.searchcat.qqsg.position/main.py')
PLUGIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLUGIN)


class PositionTests(unittest.TestCase):
    def test_manifest_defaults_and_sdk_route(self):
        manifest = PluginManifest.load(ROOT / 'plugins/com.searchcat.qqsg.position')
        config = PluginManager._default_config(manifest)
        self.assertFalse(config['navigate'])
        self.assertEqual(config['interval'], 3)
        self.assertIn('screen.capture', manifest.permissions)
        call = Mock(return_value={'map_name': '秃龙洞口', 'position': [6, 4]})
        api = WindowAPI(call)
        self.assertEqual(api.read_navigation_state(['秃龙洞口'])['position'], [6, 4])
        call.assert_called_once_with('window.navigation_state', {'map_names': ['秃龙洞口']})

    def test_empty_map_list_is_not_silently_replaced_by_mining_defaults(self):
        call = Mock()
        WindowAPI(call).read_navigation_state([])
        call.assert_called_once_with('window.navigation_state', {'map_names': []})

    def test_collapsed_fallback_and_frame_release(self):
        host = SimpleNamespace(dry_run=False, frames={'frame': object()},
                               _capture_window=Mock(return_value={'id': 'frame', 'width': 1280, 'height': 960}))
        with patch.object(reader, '_focus'), patch.object(reader, '_scan', side_effect=[
                ([[]], 1280, 960), ([[{'text': '秃龙洞口(6,4)'}]], 1280, 960)]) as scan:
            result = reader.read_navigation_state(host, ['秃龙洞口'])
        self.assertEqual(result['position'], [6, 4])
        self.assertEqual(scan.call_args.args[1], (1075, 24, 203, 40))
        self.assertEqual(host.frames, {})

    def test_four_clients_clear_stale_position_without_movement(self):
        catalog = {'秃龙洞口': {'id': 23, 'name': '秃龙洞口'}}
        paths = []
        with patch.object(PLUGIN, 'QQSGPackage'), patch.object(PLUGIN, 'parse_map_catalog', return_value=catalog):
            for hwnd in (133552, 330190, 395914, 920054):
                context = Mock()
                context.config = {}
                context.dry_run = False
                context.windows.current.return_value = {'hwnd': hwnd, 'pid': hwnd, 'title': 'QQ三国'}
                context.windows.is_alive.side_effect = [True, True, False]
                context.windows.read_navigation_state.side_effect = [
                    {'map_name': '秃龙洞口', 'position': [6, 4]},
                    {'diagnostic': {'reason': '地图名/坐标未匹配'}}]
                PLUGIN.on_start(context)
                writes = context.storage.write_json.call_args_list
                self.assertTrue(writes[0].args[1]['valid'])
                self.assertIsNone(writes[1].args[1]['position'])
                self.assertFalse(writes[1].args[1]['valid'])
                paths.append(writes[0].args[0])
                context.windows.navigate_by_code.assert_not_called()
        self.assertEqual(len(set(paths)), 4)

    def test_navigation_uses_ui_units_and_only_when_enabled(self):
        context = Mock()
        context.config = {'navigate': True, 'target_map': '秃龙洞口', 'target_x': 6, 'target_y': 4}
        context.dry_run = True
        context.windows.current.return_value = {'pid': 1, 'hwnd': 2}
        with patch.object(PLUGIN, 'QQSGPackage'), patch.object(PLUGIN, 'parse_map_catalog',
                return_value={'秃龙洞口': {'id': 23, 'name': '秃龙洞口'}}), \
                patch.object(PLUGIN, 'navigate_and_wait') as navigate:
            PLUGIN.on_start(context)
        navigate.assert_called_once_with(context, 23, 600, 400, '秃龙洞口')
        context.windows.read_navigation_state.assert_not_called()
