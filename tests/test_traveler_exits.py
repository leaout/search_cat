"""Bounded six-exit workflow regressions, with no real window/input calls."""

import copy
import importlib.util
import json
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'plugins/com.searchcat.qqsg.traveler'
SPEC = importlib.util.spec_from_file_location('traveler_test_plugin', DIRECTORY / 'main.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def entry(position=None):
    return {'map_name': MODULE.ENTRY_MAP, 'position': position or [8, 21]}


def destination():
    return {'map_name': MODULE.DESTINATION, 'position': [2, 10]}


class TravelerExitTests(unittest.TestCase):
    def setUp(self):
        terrain = patch.object(MODULE, 'load_terrain', return_value=[])
        pilot = patch.object(MODULE, 'TerrainPilot')
        terrain.start()
        self.pilot = pilot.start()
        self.addCleanup(terrain.stop)
        self.addCleanup(pilot.stop)

    def context(self, states, config=None, dry=False):
        records = []
        windows = Mock()
        windows.read_navigation_state.side_effect = states
        windows.is_alive.return_value = True
        windows.navigate_by_code.return_value = {'clicked': True, 'ui_restored': True}
        storage = Mock()
        storage.write_json.side_effect = lambda path, value: records.append(copy.deepcopy(value))
        context = SimpleNamespace(config=config or {}, dry_run=dry, windows=windows,
                                  keyboard=Mock(), storage=storage, log=Mock(),
                                  sleep=Mock(), step=lambda name: nullcontext())
        return context, records

    def test_six_failed_exits_are_tried_once_and_stop(self):
        states = [entry(), entry()] + [entry([10, 20]), entry(), entry()] * 6
        context, records = self.context(states)
        with self.assertRaisesRegex(RuntimeError, '六个出口'):
            MODULE.on_start(context)
        self.assertEqual(self.pilot.call_count, 6)
        context.windows.navigate_by_code.assert_not_called()
        self.assertEqual(records[-1]['status'], 'needs_attention')
        self.assertEqual([a['exit'] for a in records[-1]['attempts']], list(range(1, 7)))
        self.assertTrue(all(a['result'] == 'returned_to_start' for a in records[-1]['attempts']))

    def test_success_on_third_exit_skips_remaining(self):
        states = [entry(), entry()] + [entry([10, 20]), entry(), entry()] * 2
        states += [entry([10, 20]), destination(), destination()]
        context, records = self.context(states)
        MODULE.on_start(context)
        self.assertEqual(self.pilot.call_count, 3)
        self.assertEqual(records[-1]['status'], 'completed')
        self.assertEqual(records[-1]['attempts'][-1]['result'], 'success')

    def test_exit_trigger_only_once_and_raw_coordinates_not_multiplied(self):
        context, records = self.context([entry(), entry(), entry([2, 2]), entry([2, 2]),
                                         destination(), destination()])
        MODULE.on_start(context)
        self.pilot.assert_called_once_with(context, [], [232, 177])
        context.keyboard.press.assert_called_once_with('up')
        self.assertEqual(records[-1]['status'], 'completed')

    def test_starting_at_spawn_is_not_a_failed_exit(self):
        context, records = self.context([entry()] * 14,
                                        {'attempt_timeout': 10, 'scan_interval': 5})
        with self.assertRaisesRegex(RuntimeError, '六个出口'):
            MODULE.on_start(context)
        self.assertEqual(self.pilot.call_count, 6)
        self.assertTrue(all(a['result'] == 'timeout' for a in records[-1]['attempts']))

    def test_five_unknown_reads_stop_without_success_or_next_exit(self):
        context, records = self.context([entry(), entry()] + [None] * 5)
        with self.assertRaisesRegex(RuntimeError, '连续5次'):
            MODULE.on_start(context)
        self.assertEqual(self.pilot.call_count, 1)
        self.pilot.return_value.drive.assert_not_called()
        self.assertEqual(records[-1]['status'], 'needs_attention')
        self.assertNotIn('completed', [r['status'] for r in records])

    def test_one_destination_read_does_not_prove_success(self):
        context, records = self.context([entry(), entry(), destination()] + [None] * 5)
        with self.assertRaises(RuntimeError):
            MODULE.on_start(context)
        self.assertEqual(records[-1]['status'], 'needs_attention')
        self.assertEqual(self.pilot.call_count, 1)

    def test_unknown_start_prevents_navigation(self):
        context, records = self.context([None, entry()] * 3)
        with self.assertRaisesRegex(RuntimeError, '未连续确认'):
            MODULE.on_start(context)
        context.windows.navigate_by_code.assert_not_called()

    def test_start_transient_miss_recovers_without_input(self):
        context, _ = self.context([None, entry(), None, entry(), entry()])
        result = MODULE._confirm_start(context, 0.7)
        self.assertEqual(result, entry())
        self.assertEqual(context.keyboard.mock_calls, [])

    def test_planning_failure_stops_without_key_input(self):
        context, records = self.context([entry(), entry(), entry([10, 20])])
        self.pilot.return_value.drive.side_effect = RuntimeError('无法规划')
        with self.assertRaisesRegex(RuntimeError, '无法规划'):
            MODULE.on_start(context)
        context.keyboard.press.assert_not_called()
        self.assertEqual(records[-1]['status'], 'needs_attention')

    def test_simulated_run_does_not_read_windows_input_or_save_success(self):
        context, records = self.context([], dry=True)
        MODULE.on_start(context)
        context.windows.read_navigation_state.assert_not_called()
        context.windows.navigate_by_code.assert_not_called()
        context.keyboard.press.assert_not_called()
        self.assertEqual(records, [])

    def test_already_in_destination_requires_two_reads(self):
        context, records = self.context([destination(), destination()])
        MODULE.on_start(context)
        context.windows.navigate_by_code.assert_not_called()
        self.assertEqual(records[-1]['status'], 'completed')

    def test_all_six_variants_use_their_own_exit_coordinates(self):
        data = json.loads((DIRECTORY / 'exits.json').read_text(encoding='utf-8'))['maps']
        for map_id in range(456, 462):
            with self.subTest(map_id=map_id):
                self.pilot.reset_mock()
                context, records = self.context([entry(), entry()] +
                                                [entry([10, 20]), entry(), entry()] * 6,
                                                {'map_id': map_id})
                with self.assertRaises(RuntimeError):
                    MODULE.on_start(context)
                self.assertEqual([call.args[2] for call in self.pilot.call_args_list], data[str(map_id)])
                context.windows.navigate_by_code.assert_not_called()

    def test_invalid_config_rejected_before_input(self):
        for config in ({'map_id': 462}, {'map_id': True}, {'attempt_timeout': float('nan')},
                       {'trigger_key': 'enter'}, {'scan_interval': 0}):
            with self.subTest(config=config):
                context, _ = self.context([], config)
                with self.assertRaises(ValueError):
                    MODULE.on_start(context)
                context.windows.navigate_by_code.assert_not_called()

    def test_closed_window_prevents_further_attempts(self):
        context, records = self.context([entry(), entry()])
        context.windows.is_alive.return_value = False
        with self.assertRaisesRegex(RuntimeError, '窗口已关闭'):
            MODULE.on_start(context)
        self.assertEqual(self.pilot.call_count, 1)
        self.assertEqual(records[-1]['status'], 'needs_attention')

    def test_interrupt_propagates_without_trying_the_next_exit(self):
        context, records = self.context([entry(), entry(), entry([10, 20])])
        self.pilot.return_value.drive.side_effect = InterruptedError('停止')
        with self.assertRaises(InterruptedError):
            MODULE.on_start(context)
        self.assertEqual(self.pilot.call_count, 1)
        context.keyboard.press.assert_not_called()


if __name__ == '__main__':
    unittest.main()
