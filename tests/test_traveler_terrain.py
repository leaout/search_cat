"""Feedback movement tests without real keyboard input."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from plugin_platform.qqsg_traveler_terrain import TerrainPilot, _geometry, movement_settings


class TerrainPilotTests(unittest.TestCase):
    def pilot(self, action, source, target):
        context = SimpleNamespace(config={}, dry_run=False, keyboard=Mock(), log=Mock())
        pilot = TerrainPilot(context, [], [200, 200])
        pilot.steps = [{'action': action, 'from': source, 'to': target}]
        return pilot, context

    def test_walk_is_bounded(self):
        pilot, context = self.pilot('walk', [1, 2], [9, 2])
        pilot.drive([1, 2])
        context.keyboard.hold_combo.assert_called_once_with('right', duration=0.6)

    def test_fall_during_walk_replans_without_old_platform_input(self):
        pilot, context = self.pilot('walk', [5.5, 18], [6.6, 18])
        with patch.object(pilot, '_replan') as replan:
            pilot.drive([6, 21])
            self.assertEqual(replan.call_args.args[0], [6, 21])
        self.assertEqual(context.keyboard.mock_calls, [])

    def test_slope_height_is_interpolated_not_endpoint_height(self):
        pilot, context = self.pilot('walk', [1, 2], [9, 6])
        pilot.drive([4, 3])
        context.keyboard.hold_combo.assert_called_once()

    def test_jump_waits_for_stable_wrong_landing(self):
        pilot, context = self.pilot('jump', [1, 2], [3, 1])
        pilot.drive([1, 2])
        self.assertEqual(context.keyboard.directional_jump.call_args.args, ('right',))
        with patch.object(pilot, '_replan') as replan:
            pilot.drive([2, 0])
            replan.assert_not_called()
            pilot.drive([2, 0])
            self.assertEqual(replan.call_args.args[0], [2, 0])

    def test_climb_continues_after_leaving_source(self):
        pilot, context = self.pilot('climb', [2, 9], [2, 1])
        pilot.drive([2, 9])
        pilot.drive([2, 7])
        self.assertEqual(context.keyboard.hold_combo.call_count, 2)
        self.assertEqual(pilot.replans, 0)

    def test_plan_uses_current_cell_center(self):
        pilot, _ = self.pilot('walk', [1, 2], [9, 2])
        with patch('plugin_platform.qqsg_traveler_terrain.plan_route', return_value={'steps': []}) as planner:
            pilot.plan([8, 21])
            self.assertEqual(planner.call_args.args[1], [850, 2150])
            self.assertTrue(planner.call_args.kwargs['allow_climb'])

    def test_invalid_settings_and_geometry(self):
        for config in ({'jump_x': True}, {'jump_up': float('nan')}, {'move_pulse_max': 2}):
            with self.assertRaises(ValueError):
                movement_settings(config)
        with self.assertRaises(ValueError):
            _geometry(b'bad')
