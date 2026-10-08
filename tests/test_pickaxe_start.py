"""Test the real GUI start guard without importing Qt or Windows libraries."""

import ast
import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from plugin_platform.qqsg_pickaxe_shop import purchase_session_key


def load_start():
    """Compile only ScriptPlatformFeature.start with mocked desktop dependencies."""
    source = Path(__file__).resolve().parents[1] / 'feature' / 'script_platform_feature.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    feature = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name == 'ScriptPlatformFeature')
    method = next(node for node in feature.body if isinstance(node, ast.FunctionDef)
                  and node.name == 'start')
    namespace = {
        'QMessageBox': Mock(),
        'win32gui': Mock(),
        'win32process': Mock(),
        'PluginProcess': Mock(),
        'deepcopy': deepcopy,
        'json': json,
        'purchase_session_key': purchase_session_key,
    }
    namespace['win32gui'].IsWindow.return_value = True
    namespace['win32process'].GetWindowThreadProcessId.return_value = (1, 9001)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['start'], namespace


def window_info(hwnd=101):
    return {'id': f'window-{hwnd}', 'hwnd': hwnd, 'pid': 9001}


class PickaxeStartTests(unittest.TestCase):
    def setUp(self):
        self.start, self.namespace = load_start()

    def make_feature(self, windows, config, plugin_id='com.searchcat.qqsg.mining'):
        feature = Mock()
        feature.current_manifest.return_value = SimpleNamespace(id=plugin_id)
        feature._read_config.return_value = config
        feature.target_windows = windows
        feature.target_window_info = windows[0] if windows else None
        feature._missing_templates.return_value = []
        feature.session_states = {}
        feature.session_logs = {}
        feature.runners = {}
        feature.dry_run_checkbox.isChecked.return_value = False
        return feature

    def test_auto_purchase_rejects_two_valid_windows(self):
        feature = self.make_feature([window_info(101), window_info(102)], {
            'pickaxe_auto_buy_enabled': True,
            'pickaxe_character_id': '角色甲',
        })

        self.start(feature)

        self.namespace['PluginProcess'].assert_not_called()
        warning = self.namespace['QMessageBox'].warning
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[1], '自动购买暂限单窗口')
        self.assertEqual(feature.runners, {})
        feature._sync_running_ui.assert_not_called()

    def test_auto_purchase_rejects_empty_character_alias(self):
        for alias in ('', '   '):
            with self.subTest(alias=alias):
                self.namespace['QMessageBox'].reset_mock()
                feature = self.make_feature([window_info()], {
                    'pickaxe_auto_buy_enabled': True,
                    'pickaxe_character_id': alias,
                })

                self.start(feature)

                self.namespace['PluginProcess'].assert_not_called()
                warning = self.namespace['QMessageBox'].warning
                warning.assert_called_once()
                self.assertEqual(warning.call_args.args[1], '购买配置不完整')
                self.assertEqual(feature.runners, {})

    def test_single_window_purchase_uses_stable_role_session(self):
        info = window_info()
        config = {
            'pickaxe_auto_buy_enabled': True,
            'pickaxe_character_id': '  抚琴退敌-角色甲  ',
            'pickaxe_wage_budget': 10,
        }
        feature = self.make_feature([info], config)

        self.start(feature)

        factory = self.namespace['PluginProcess']
        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs['session_key'],
                         purchase_session_key(config['pickaxe_character_id']))
        self.assertFalse(factory.call_args.kwargs['dry_run'])
        self.assertEqual(factory.call_args.args[2], config)
        self.assertIsNot(factory.call_args.args[2], config)
        self.assertEqual(factory.call_args.args[3], info)
        self.assertIs(feature.runners[info['id']], factory.return_value)
        self.assertEqual(feature.session_states[info['id']], 'starting')
        factory.return_value.start.assert_called_once()
        feature._sync_running_ui.assert_called_once()
        self.namespace['QMessageBox'].warning.assert_not_called()

    def test_game_hwnd_restart_keeps_same_purchase_session(self):
        config = {'pickaxe_auto_buy_enabled': True, 'pickaxe_character_id': '角色甲'}
        first = self.make_feature([window_info(101)], config)
        restarted = self.make_feature([window_info(809)], config)

        self.start(first)
        self.start(restarted)

        calls = self.namespace['PluginProcess'].call_args_list
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0].args[3]['hwnd'], calls[1].args[3]['hwnd'])
        self.assertEqual(calls[0].kwargs['session_key'], calls[1].kwargs['session_key'])
        self.assertEqual(calls[1].kwargs['session_key'], purchase_session_key('角色甲'))

    def test_disabled_purchase_keeps_each_window_session_id(self):
        windows = [window_info(101), window_info(102)]
        feature = self.make_feature(windows, {'pickaxe_auto_buy_enabled': False})

        self.start(feature)

        calls = self.namespace['PluginProcess'].call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual([call.kwargs['session_key'] for call in calls],
                         [info['id'] for info in windows])
        self.namespace['QMessageBox'].warning.assert_not_called()

    def test_other_plugin_does_not_use_mining_purchase_alias(self):
        info = window_info()
        feature = self.make_feature([info], {'pickaxe_auto_buy_enabled': True},
                                    plugin_id='com.searchcat.qqsg.daily')

        self.start(feature)

        self.assertEqual(self.namespace['PluginProcess'].call_args.kwargs['session_key'], info['id'])
        self.namespace['QMessageBox'].warning.assert_not_called()


if __name__ == '__main__':
    unittest.main()
