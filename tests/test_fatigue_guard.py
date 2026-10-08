"""Verify fatigue guard control flow using mocks; never send real game input."""

import importlib.util
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch


MAIN = Path(__file__).resolve().parents[1] / 'plugins/com.searchcat.qqsg.mining/main.py'
SPEC = importlib.util.spec_from_file_location('fatigue_guard_main', MAIN)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fatigue_result(used: int, limit: int) -> dict:
    return {'reading': [used, limit], 'reason': '', 'ui_restored': True}


class GatheringFatigueGuardTests(unittest.TestCase):
    def setUp(self):
        self.context = Mock()
        self.context.dry_run = False
        self.context.config = {
            'fatigue_monitor_enabled': True,
            'fatigue_recheck_seconds': 5,
        }
        self.context.windows.current.return_value = {'hwnd': 42, 'title': 'QQ三国 14线'}
        self.context.windows.is_alive.return_value = True
        self.context.step.side_effect = lambda name: nullcontext()

    def assert_no_input(self):
        self.assertEqual(self.context.keyboard.mock_calls, [])
        self.assertEqual(self.context.mouse.mock_calls, [])

    def test_ready_persists_actual_limit_and_remaining(self):
        self.context.windows.read_gathering_fatigue.return_value = fatigue_result(334, 2520)
        MODULE._ensure_gathering_fatigue(self.context)
        self.context.windows.read_gathering_fatigue.assert_called_once_with()
        path, snapshot = self.context.storage.write_json.call_args.args
        self.assertEqual(path, 'mining/fatigue-42.json')
        self.assertEqual(snapshot['state'], 'ready')
        self.assertEqual(snapshot['used'], 334)
        self.assertEqual(snapshot['limit'], 2520)
        self.assertEqual(snapshot['remaining'], 2186)
        self.assertEqual(snapshot['source'], 'f1')
        self.assert_no_input()
        self.context.sleep.assert_not_called()

    def test_full_persists_exhaustion_and_stops_without_input(self):
        self.context.windows.read_gathering_fatigue.return_value = fatigue_result(2520, 2520)
        with self.assertRaises(MODULE.GatheringFatigueLimitReached):
            MODULE._ensure_gathering_fatigue(self.context)
        snapshot = self.context.storage.write_json.call_args.args[1]
        self.assertEqual(snapshot['state'], 'exhausted')
        self.assertEqual(snapshot['remaining'], 0)
        self.assert_no_input()
        self.context.sleep.assert_not_called()

    def test_unknown_waits_then_ready_with_no_ui_attempt(self):
        self.context.storage.read_json.return_value = {'state': 'ready', 'used': 0, 'limit': 2520}
        self.context.windows.read_gathering_fatigue.side_effect = [
            {'reading': None, 'reason': '提示未识别', 'ui_restored': True},
            fatigue_result(334, 2520),
        ]
        MODULE._ensure_gathering_fatigue(self.context)
        self.assertEqual(self.context.windows.read_gathering_fatigue.call_count, 2)
        self.context.sleep.assert_called_once_with(5.0)
        states = [call.args[1]['state'] for call in self.context.storage.write_json.call_args_list]
        self.assertEqual(states, ['unknown', 'ready'])
        unknown = self.context.storage.write_json.call_args_list[0].args[1]
        self.assertIsNone(unknown['used'])
        self.assertIsNone(unknown['limit'])
        self.assertIsNone(unknown['remaining'])
        self.context.storage.read_json.assert_not_called()
        self.assert_no_input()

    def test_no_manual_region_needed_and_invalid_legacy_region_is_ignored(self):
        for region in (None, [], [10, 10, 0, 20], [-1, 10, 20, 20], [10, 10]):
            with self.subTest(region=region):
                self.setUp()
                if region is not None:
                    self.context.config['fatigue_region'] = region
                self.context.windows.read_gathering_fatigue.return_value = fatigue_result(334, 2520)
                with patch.object(MODULE, '_shop_scan') as scan:
                    MODULE._ensure_gathering_fatigue(self.context)
                scan.assert_not_called()
                self.context.windows.read_gathering_fatigue.assert_called_once_with()
                self.context.sleep.assert_not_called()
                self.assert_no_input()

    def test_ui_not_restored_pauses_even_when_reading_is_valid(self):
        self.context.windows.read_gathering_fatigue.side_effect = [
            {'reading': [334, 2520], 'reason': '状态面板尚未收起', 'ui_restored': False},
            fatigue_result(334, 2520),
        ]
        MODULE._ensure_gathering_fatigue(self.context)
        self.context.sleep.assert_called_once_with(5.0)
        unknown = self.context.storage.write_json.call_args_list[0].args[1]
        self.assertEqual(unknown['state'], 'unknown')
        self.assertIsNone(unknown['used'])
        self.assertEqual(unknown['detail'], '状态面板尚未收起')
        self.assertEqual(self.context.storage.write_json.call_args.args[1]['state'], 'ready')
        self.assert_no_input()

    def test_invalid_rpc_results_pause_until_fresh_valid_reading(self):
        invalid_results = [
            None, [], '334/2520', 334,
            {}, {'reading': [334, 2520]},
            {'reading': [334, 2520], 'ui_restored': 1},
            {'reading': [334, 2520], 'ui_restored': None},
        ]
        invalid_results.extend({'reading': value, 'ui_restored': True} for value in (
            None, [], [334], [334, 2520, 1], '334/2520', {'used': 334, 'limit': 2520},
            [True, 2520], [334, True], [-1, 2520], [2521, 2520], [0, 0],
            [334, -2520], ['334', 2520], [334, '2520'], [334.0, 2520],
        ))
        for result in invalid_results:
            with self.subTest(result=result):
                self.setUp()
                self.context.windows.read_gathering_fatigue.side_effect = [result, fatigue_result(334, 2520)]
                MODULE._ensure_gathering_fatigue(self.context)
                self.context.sleep.assert_called_once_with(5.0)
                states = [call.args[1]['state'] for call in self.context.storage.write_json.call_args_list]
                self.assertEqual(states, ['unknown', 'ready'])
                unknown = self.context.storage.write_json.call_args_list[0].args[1]
                self.assertIsNone(unknown['used'])
                self.assertIsNone(unknown['limit'])
                self.assertIsNone(unknown['remaining'])
                self.assert_no_input()

    def test_disabled_does_not_read_or_mutate_state(self):
        self.context.config = {'fatigue_monitor_enabled': False}
        with patch.object(MODULE, '_shop_scan') as scan:
            MODULE._ensure_gathering_fatigue(self.context)
        scan.assert_not_called()
        self.context.windows.read_gathering_fatigue.assert_not_called()
        self.context.windows.current.assert_not_called()
        self.context.storage.write_json.assert_not_called()
        self.assert_no_input()

    def test_dry_run_does_not_capture_or_persist_real_observation(self):
        self.context.dry_run = True
        with patch.object(MODULE, '_shop_scan') as scan:
            MODULE._ensure_gathering_fatigue(self.context)
        scan.assert_not_called()
        self.context.windows.read_gathering_fatigue.assert_not_called()
        self.context.windows.current.assert_not_called()
        self.context.storage.write_json.assert_not_called()
        self.assert_no_input()

    def test_closed_window_stops_before_ocr(self):
        self.context.windows.is_alive.return_value = False
        with patch.object(MODULE, '_shop_scan') as scan:
            with self.assertRaisesRegex(RuntimeError, '窗口已关闭'):
                MODULE._ensure_gathering_fatigue(self.context)
        scan.assert_not_called()
        self.context.windows.read_gathering_fatigue.assert_not_called()
        self.assert_no_input()

    def test_on_start_full_ends_normally_before_switch_equip_or_buy(self):
        self.context.config.update({'pickaxe_auto_buy_enabled': True,
                                    'pickaxe_monitor_enabled': True,
                                    'pickaxe_auto_equip_enabled': True})
        self.context.windows.read_gathering_fatigue.return_value = fatigue_result(2520, 2520)
        with patch.object(MODULE, '_switch_line') as switch, \
                patch.object(MODULE, '_ensure_pickaxe_ready') as equip, \
                patch.object(MODULE, '_try_buy_middle_pickaxe') as buy, \
                patch.object(MODULE, '_activate') as activate:
            MODULE.on_start(self.context)
        switch.assert_not_called()
        equip.assert_not_called()
        buy.assert_not_called()
        activate.assert_not_called()
        self.assert_no_input()
        self.assertTrue(any('结束本次脚本' in str(call.args[0])
                            for call in self.context.log.call_args_list))

    def test_press_g_rechecks_each_press_and_stops_at_second_reading(self):
        self.context.windows.read_gathering_fatigue.side_effect = [
            fatigue_result(2519, 2520), fatigue_result(2520, 2520),
        ]
        with patch.object(MODULE, '_activate'), patch.object(MODULE, '_wait') as wait:
            with self.assertRaises(MODULE.GatheringFatigueLimitReached):
                MODULE._press_g(self.context, count=3, interval=0.1)
        self.context.keyboard.press.assert_called_once_with('g', mode='foreground')
        wait.assert_called_once_with(self.context, 0.1)
        self.assertEqual(self.context.mouse.mock_calls, [])

    def test_buy_full_refuses_before_shop_or_purchase_ledger(self):
        self.context.windows.read_gathering_fatigue.return_value = fatigue_result(2520, 2520)
        with patch.object(MODULE, '_activate') as activate, \
                patch.object(MODULE, '_reserve_pickaxe_purchase') as reserve:
            with self.assertRaises(MODULE.GatheringFatigueLimitReached):
                MODULE._try_buy_middle_pickaxe(self.context)
        activate.assert_not_called()
        reserve.assert_not_called()
        self.context.storage.read_json.assert_not_called()
        self.assertEqual(len(self.context.storage.write_json.call_args_list), 1)
        self.assertEqual(self.context.storage.write_json.call_args.args[0], 'mining/fatigue-42.json')
        self.assert_no_input()


if __name__ == '__main__':
    unittest.main()
