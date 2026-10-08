"""Regression tests for terrain jumps; these never capture or operate the game."""

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


PLUGIN_PATH = (
    Path(__file__).resolve().parents[1]
    / 'plugins'
    / 'com.searchcat.qqsg.official_task'
    / 'main.py'
)
SPEC = importlib.util.spec_from_file_location('official_jump_regression_plugin', PLUGIN_PATH)
PLUGIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLUGIN)


def fake_context():
    logs = []
    return SimpleNamespace(
        config={
            'jump_key_hold': 0.12,
            'jump_direction_lead': 0.10,
            'jump_direction_follow': 0.05,
            'jump_landing_wait': 0.75,
        },
        dry_run=False,
        keyboard=SimpleNamespace(hold_combo=Mock(), directional_jump=Mock()),
        log=lambda message, level='info': logs.append((level, message)),
        sleep=Mock(),
        logs=logs,
    )


def minimap(position):
    return {'map': '成都.子城', 'position': position}


def saved_plan():
    return {
        'map': '成都.子城',
        'scale': 100,
        'start': [10.9, 9.4],
        'target': [30, 8],
        'steps': [],
        'terrain_records': [[1, 2, 0, 0, 800, 3000, 800, 0]],
    }


def planned_steps(start, end):
    return {
        'steps': [
            {'action': 'jump', 'segment': 1, 'from': start, 'to': end},
            {'action': 'walk', 'segment': 2, 'from': end, 'to': [30, 8]},
        ],
    }


class OfficialJumpRegressionTests(unittest.TestCase):
    def execute_successful_jump(self, start, end, initial, landing):
        context = fake_context()
        states = [minimap(point) for point in (initial, initial, landing, landing, (30, 8))]
        with (
            patch.object(PLUGIN, 'plan_route', return_value=planned_steps(start, end)),
            patch.object(PLUGIN, '_scan_minimap', side_effect=states) as scan,
            patch.object(PLUGIN, '_align_to_connection', return_value=initial),
        ):
            PLUGIN._execute_terrain_route(context, saved_plan(), '寻路回归测试')
        self.assertEqual(scan.call_count, 5)
        return context

    def test_logged_leftward_connection_uses_left_jump_first(self):
        context = self.execute_successful_jump([10.9, 9.4], [9.7, 8.8], (10, 9), (9, 8))

        context.keyboard.directional_jump.assert_called_once_with(
            'left', lead_time=0.10, jump_hold=0.12, follow_time=0.05, mode='foreground',
        )
        context.keyboard.hold_combo.assert_not_called()

    def test_rightward_connection_uses_right_jump_first(self):
        context = self.execute_successful_jump([9.7, 9.4], [10.9, 8.8], (9, 9), (10, 8))

        self.assertEqual(context.keyboard.directional_jump.call_args.args, ('right',))
        context.keyboard.hold_combo.assert_not_called()

    def test_fractional_horizontal_motion_is_not_lost_to_integer_quantization(self):
        context = self.execute_successful_jump([10.9, 9.4], [10.1, 8.8], (10, 9), (10, 8))

        self.assertEqual(context.keyboard.directional_jump.call_args.args, ('left',))
        context.keyboard.hold_combo.assert_not_called()

    def test_vertical_connection_uses_space_despite_following_rightward_step(self):
        context = self.execute_successful_jump([10.9, 9.4], [10.9, 8.8], (10, 9), (10, 8))

        context.keyboard.hold_combo.assert_called_once_with('space', duration=0.12, mode='foreground')
        context.keyboard.directional_jump.assert_not_called()

    def test_wrong_landing_replans_from_fresh_position_without_second_jump(self):
        context = fake_context()
        states = [minimap(point) for point in ((10, 9), (10, 9), (10, 8), (10, 8))]
        with (
            patch.object(
                PLUGIN, 'plan_route',
                side_effect=[planned_steps([10.9, 9.4], [9.7, 8.8]), ValueError('停止模拟重规划')],
            ) as planner,
            patch.object(PLUGIN, '_scan_minimap', side_effect=states) as scan,
            patch.object(PLUGIN, '_align_to_connection', return_value=(10, 9)),
        ):
            with self.assertRaisesRegex(RuntimeError, '无法从当前坐标'):
                PLUGIN._execute_terrain_route(context, saved_plan(), '寻路回归测试')

        self.assertEqual(scan.call_count, 4)
        self.assertEqual(planner.call_args_list[1].args[1], [1050.0, 850.0])
        context.keyboard.directional_jump.assert_called_once()
        context.keyboard.hold_combo.assert_not_called()
        self.assertTrue(any('实际落点 (10, 8)' in message for _, message in context.logs))

    def test_vertical_unchanged_landing_allows_controlled_directional_fallback(self):
        context = fake_context()
        states = [
            minimap(point) for point in ((10, 9), (10, 9), (10, 9), (10, 8), (10, 8), (30, 8))
        ]
        with (
            patch.object(PLUGIN, 'plan_route', return_value=planned_steps([10.9, 9.4], [10.9, 8.8])),
            patch.object(PLUGIN, '_scan_minimap', side_effect=states) as scan,
            patch.object(PLUGIN, '_align_to_connection', return_value=(10, 9)),
        ):
            PLUGIN._execute_terrain_route(context, saved_plan(), '寻路回归测试')

        self.assertEqual(scan.call_count, 6)
        context.keyboard.hold_combo.assert_called_once_with('space', duration=0.12, mode='foreground')
        context.keyboard.directional_jump.assert_called_once_with(
            'right', lead_time=0.10, jump_hold=0.12, follow_time=0.05, mode='foreground',
        )

    def test_vertical_changed_but_wrong_landing_replans_instead_of_directional_fallback(self):
        context = fake_context()
        states = [minimap(point) for point in ((10, 9), (10, 9), (11, 8), (11, 8))]
        with (
            patch.object(
                PLUGIN, 'plan_route',
                side_effect=[planned_steps([10.9, 9.4], [10.9, 8.8]), ValueError('停止模拟重规划')],
            ) as planner,
            patch.object(PLUGIN, '_scan_minimap', side_effect=states),
            patch.object(PLUGIN, '_align_to_connection', return_value=(10, 9)),
        ):
            with self.assertRaisesRegex(RuntimeError, '无法从当前坐标'):
                PLUGIN._execute_terrain_route(context, saved_plan(), '寻路回归测试')

        self.assertEqual(planner.call_args_list[1].args[1], [1150.0, 850.0])
        context.keyboard.hold_combo.assert_called_once()
        context.keyboard.directional_jump.assert_not_called()

    def test_missing_landing_ocr_stops_without_inventing_success_or_retrying_input(self):
        context = fake_context()
        with (
            patch.object(PLUGIN, 'plan_route', return_value=planned_steps([10.9, 9.4], [9.7, 8.8])),
            patch.object(PLUGIN, '_scan_minimap', side_effect=[minimap((10, 9)), minimap((10, 9))] + [None] * 3),
            patch.object(PLUGIN, '_align_to_connection', return_value=(10, 9)),
        ):
            with self.assertRaisesRegex(RuntimeError, '连续无法读取人物坐标'):
                PLUGIN._execute_terrain_route(context, saved_plan(), '寻路回归测试')

        context.keyboard.directional_jump.assert_called_once()
        context.keyboard.hold_combo.assert_not_called()

    def test_dry_run_does_not_send_jump_input(self):
        context = fake_context()
        context.dry_run = True
        with (
            patch.object(PLUGIN, 'plan_route', return_value=planned_steps([10.9, 9.4], [9.7, 8.8])),
            patch.object(PLUGIN, '_scan_minimap', return_value=minimap((10, 9))),
            patch.object(PLUGIN, '_align_to_connection') as align,
        ):
            PLUGIN._execute_terrain_route(context, saved_plan(), '寻路回归测试')

        align.assert_not_called()
        context.keyboard.directional_jump.assert_not_called()
        context.keyboard.hold_combo.assert_not_called()


if __name__ == '__main__':
    unittest.main()
