import importlib.util
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PLUGIN_PATH = (
    Path(__file__).resolve().parents[1]
    / 'plugins'
    / 'com.searchcat.qqsg.official_task'
    / 'main.py'
)
SPEC = importlib.util.spec_from_file_location('official_task_plugin', PLUGIN_PATH)
PLUGIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLUGIN)


class FakeContext:
    def __init__(self, ocr_results):
        self.config = {
            'minimap_region': [500, 0, 280, 100],
            'arrival_tolerance': 0,
            'waypoint_max_attempts': 5,
            'seconds_per_coordinate': 0.1,
            'minimum_move_pulse': 0.05,
            'maximum_move_pulse': 0.2,
            'position_scan_interval': 0,
            'stuck_scan_limit': 3,
            'input_mode': 'foreground',
        }
        self.dry_run = False
        self._ocr_results = iter(ocr_results)
        self.capture = SimpleNamespace(window=lambda **_kwargs: SimpleNamespace(id='frame'))
        self.windows = SimpleNamespace(
            activate=lambda: {'active': True},
            current=lambda: {'width': 1000, 'height': 800},
        )
        self.ocr = SimpleNamespace(recognize=lambda *_args, **_kwargs: next(self._ocr_results))
        self.debug = SimpleNamespace(watch=lambda *_args: None)
        self.mouse = SimpleNamespace(
            click=lambda x, y, **kwargs: self.logs.append(('click', (x, y, kwargs))),
            move=lambda x, y, **kwargs: self.logs.append(('move', (x, y, kwargs))),
        )
        self.key_events = []
        self.keyboard = SimpleNamespace(
            key_down=lambda key, mode: self.key_events.append(('down', key, mode)),
            key_up=lambda key, mode: self.key_events.append(('up', key, mode)),
            press=lambda key, mode: self.key_events.append(('press', key, mode)),
            hold_combo=lambda *keys, duration, mode: self.key_events.append(
                ('combo', keys, duration, mode)
            ),
            directional_jump=lambda direction, lead_time, jump_hold, follow_time, mode:
                self.key_events.append(
                    ('directional_jump', direction, lead_time, jump_hold, follow_time, mode)
                ),
        )
        self.logs = []

    def log(self, message, level='info'):
        self.logs.append((level, message))

    def sleep(self, _seconds):
        return None


def ocr_line(text, confidence=0.95):
    return {'text': text, 'confidence': confidence, 'center': [10, 10]}


class OfficialTaskNavigationTests(unittest.TestCase):
    def test_runtime_step_retries_until_success(self):
        attempts = []
        logs = []
        context = SimpleNamespace(
            config={'runtime_retry_interval': 0},
            step=lambda _name: nullcontext(),
            log=lambda message, level='info': logs.append((level, message)),
            sleep=lambda _seconds: None,
            dry_run=False,
        )

        def operation():
            attempts.append(len(attempts) + 1)
            if len(attempts) < 3:
                raise RuntimeError('暂时失败')
            return 'completed'

        result = PLUGIN._run_step_until_success(context, '寻路', operation)

        self.assertEqual(result, 'completed')
        self.assertEqual(attempts, [1, 2, 3])
        self.assertEqual(sum(level == 'warning' for level, _message in logs), 2)

    def test_map_name_accepts_adjacent_ocr_transposition(self):
        expected = '\u6210\u90fd.\u5b50\u57ce'
        self.assertTrue(PLUGIN._map_names_equivalent('\u57ce\u90fd.\u5b50\u57ce', expected))
        self.assertTrue(PLUGIN._map_names_equivalent('\u6210\u90fd\uff0c\u5b50\u57ce', expected))
        self.assertFalse(PLUGIN._map_names_equivalent('\u5efa\u4e1a.\u5b50\u57ce', expected))

    def test_session_map_is_confirmed_once_and_later_ocr_is_ignored(self):
        context = FakeContext([])
        expected = '\u6210\u90fd.\u5b50\u57ce'

        self.assertTrue(PLUGIN._confirm_session_map(context, expected, expected))
        self.assertEqual(context._qqsg_confirmed_map, expected)
        self.assertTrue(PLUGIN._confirm_session_map(
            context, '\u5b8c\u5168\u9519\u8bef', expected,
        ))
        self.assertFalse(PLUGIN._confirm_session_map(
            context, expected, '\u5efa\u4e1a.\u5b50\u57ce',
        ))

    def test_minimap_integer_position_uses_cell_center_for_planning(self):
        self.assertEqual(PLUGIN._minimap_cell_center((11, 7), 100), [1150.0, 750.0])

    def test_talk_activates_window_before_pressing_g(self):
        context = FakeContext([])
        events = []
        context.windows = SimpleNamespace(
            activate=lambda: events.append('activate') or {'active': True},
        )
        context.keyboard = SimpleNamespace(
            press=lambda key, mode: events.append(('press', key, mode)),
        )

        PLUGIN._talk_to_nearest_npc(context)

        self.assertEqual(events, ['activate', ('press', 'g', 'foreground')])

    def test_restore_control_click_uses_safe_relative_scene_point(self):
        context = FakeContext([])
        clicks = []
        context.mouse = SimpleNamespace(
            click=lambda x, y, **kwargs: clicks.append((x, y, kwargs)),
        )

        PLUGIN._restore_game_control(context)

        self.assertEqual(clicks[0][:2], (500, 280))
        self.assertEqual(clicks[0][2]['coordinate_space'], 'client')

    def test_terrain_model_lookup_ignores_map_punctuation(self):
        config = {'terrain_models': {'成都.子城': {'terrain_records': [[1]]}}}
        self.assertEqual(
            PLUGIN._terrain_model_for_map(config, '成都·子城'),
            {'terrain_records': [[1]]},
        )

    def test_accept_task_uses_enter_spam_by_default(self):
        context = FakeContext([])
        context.config['accept_enter_count'] = 4
        context.config['accept_enter_interval'] = 0
        PLUGIN._accept_official_task(context)
        self.assertEqual(context.key_events, [('press', 'enter', 'foreground')] * 4)

    def test_accept_task_rejects_excessive_enter_count(self):
        context = FakeContext([])
        context.config['accept_enter_count'] = 21
        with self.assertRaisesRegex(ValueError, '1 到 20'):
            PLUGIN._accept_official_task(context)

    def test_task_presence_accepts_misread_npc_prefix(self):
        self.assertTrue(PLUGIN._has_official_task('IPC：刘'))
        self.assertTrue(PLUGIN._has_official_task('高级官爵任务'))
        self.assertFalse(PLUGIN._has_official_task('普通任务'))

    def test_npc_ocr_consensus_resolves_unique_surname(self):
        routes = {'霍峻': [23, 20, 4], '秦密': [23, 18, 12], '向宠': [23, 15, 5]}

        name, score, candidates, reason = PLUGIN._fuzzy_npc_match(
            'NPC:霍楼\n高级官爵任务[已完成]\nNPC:霍梭', routes,
        )

        self.assertEqual(name, '霍峻')
        self.assertEqual(candidates, ['霍楼', '霍梭'])
        self.assertEqual(score, 100.0)
        self.assertIn('姓氏唯一', reason)

    def test_find_target_keeps_clickable_npc_line_center(self):
        context = FakeContext([])
        lines = [{'text': 'NPC:霍楼', 'client_center': [700, 180], 'center': [20, 20]}]

        name, route, point = PLUGIN._find_target(
            'NPC:霍楼', lines, {'霍峻': [23, 20, 4]}, context=context,
        )

        self.assertEqual(name, '霍峻')
        self.assertEqual(route, [23, 20, 4])
        self.assertEqual(point, [700, 180])

    def test_npc_click_targets_name_substring_not_whole_line_center(self):
        result = PLUGIN._npc_line_center([{
            'text': 'NPC:霍峻',
            'confidence': 0.9,
            'client_center': [150, 110],
            'client_box': [[100, 100], [200, 100], [200, 120], [100, 120]],
        }])

        self.assertEqual(result['point'], [183, 110])
        self.assertGreater(result['point'][0], 150)

    def test_task_click_retries_when_character_never_starts_moving(self):
        context = FakeContext([
            [ocr_line('成都·子城 (10, 16)')]
            for _ in range(20)
        ])
        context.config.update({
            'native_navigation_start_scan_limit': 2,
            'native_navigation_click_retries': 2,
            'native_navigation_max_scans': 20,
            'native_navigation_start_wait': 0,
            'native_navigation_scan_interval': 0,
        })

        with self.assertRaisesRegex(RuntimeError, '重试点击任务栏 NPC 3 次'):
            PLUGIN._navigate_by_task_click(
                context, '向宠', [1, 15, 16], [800, 180],
            )

        clicks = [event for event in context.logs if event[0] == 'click']
        self.assertEqual(len(clicks), 3)
        self.assertTrue(any('未触发自动寻路' in message
                            for level, message in context.logs
                            if level == 'warning'))

    def test_minimap_recovers_digits_using_enhanced_same_frame(self):
        context = FakeContext([[ocr_line('成都，子城')],
                               [ocr_line('成都，子城')], [ocr_line('(11,9)')]])
        state = PLUGIN._scan_minimap(context)
        self.assertEqual(state['position'], (11, 9))
        self.assertEqual(state['map'], '成都，子城')
        self.assertTrue(any('minimap_yellow' in text for _, text in context.logs))

    def test_minimap_does_not_invent_missing_coordinates(self):
        context = FakeContext([[ocr_line('成都，子城')]] * 3)
        self.assertIsNone(PLUGIN._scan_minimap(context))

    def test_final_target_stops_within_one_cell(self):
        context = FakeContext([[ocr_line(f'成都·子城 ({x}, 16)')]
                               for x in (11, 10, 9, 8, 7)])
        context.config['terrain_test_plan'] = {
            'map': '成都.子城', 'scale': 100, 'start': [11, 16.2],
            'target': [7.4, 16.2],
            'terrain_records': [[1, 2, 0, 0, 1620, 2000, 1620, 0]],
            'planner': {'jump_x': 180, 'jump_up': 120, 'allow_climb': False},
            'steps': [{'action': 'walk', 'segment': 1,
                       'from': [11, 16.2], 'to': [7.4, 16.2]}],
        }
        PLUGIN._run_terrain_test(context)
        self.assertEqual(sum(event[0] == 'down' for event in context.key_events), 2)
        self.assertTrue(all(event[1] == 'left' for event in context.key_events))

    def test_jump_connection_is_aligned_before_transfer(self):
        context = FakeContext([])
        positions = iter([(11, 7), (10, 7)])

        result = PLUGIN._align_to_connection(
            context, lambda: next(positions), [10.1, 7.1], 'foreground', 1,
        )

        self.assertEqual(result, (10, 7))
        self.assertEqual(
            context.key_events,
            [('down', 'left', 'foreground'), ('up', 'left', 'foreground')],
        )

    def test_jump_connection_ignores_minimap_y_rounding_difference(self):
        context = FakeContext([])

        result = PLUGIN._align_to_connection(
            context, lambda: (10, 8), [10.1, 7.1], 'foreground', 1,
        )

        self.assertEqual(result, (10, 8))
        self.assertEqual(context.key_events, [])
        self.assertTrue(any('忽略小地图 Y 取整差异' in message
                            for _level, message in context.logs))

    def test_vertical_jump_inherits_forward_route_direction(self):
        step = {'from': [17.2, 5.9], 'to': [17.2, 5.6]}
        next_step = {'from': [17.2, 5.6], 'to': [18.4, 4.6]}

        direction = PLUGIN._jump_direction(step, next_step, [20, 4], (17, 5), 'left')

        self.assertEqual(direction, 'right')

    def test_drop_direction_uses_fractional_connection_edge(self):
        step = {'from': [10.1, 7.1], 'to': [10.9, 9.4]}

        direction = PLUGIN._jump_direction(step, None, [15, 5], (10, 7))

        self.assertEqual(direction, 'right')

    def test_walk_endpoint_accepts_arch_height_quantization(self):
        self.assertTrue(PLUGIN._walk_endpoint_reached((26, 6), [26.3, 5.9]))
        self.assertFalse(PLUGIN._walk_endpoint_reached((26, 8), [26.3, 5.9]))

    def test_transfer_endpoint_accepts_fractional_coordinate_rounding(self):
        self.assertTrue(PLUGIN._walk_endpoint_reached(
            (11, 9), [10.9, 9.4], horizontal_tolerance=1,
        ))

    def test_final_npc_arrival_accepts_one_cell_in_both_axes(self):
        self.assertTrue(PLUGIN._walk_endpoint_reached(
            (14, 6), [15.0, 5.9], horizontal_tolerance=1,
        ))
        self.assertFalse(PLUGIN._walk_endpoint_reached(
            (13, 6), [15.0, 5.9], horizontal_tolerance=1,
        ))

    def test_npc_radius_finishes_route_even_before_last_planner_step(self):
        context = FakeContext([
            [ocr_line('成都·子城 (8, 16)')],
            [ocr_line('成都·子城 (8, 16)')],
        ])
        plan = {
            'map': '成都.子城',
            'scale': 100,
            'target': [7.4, 16.2],
            'steps': [],
            'terrain_records': [[1, 2, 0, 0, 1620, 2000, 1620, 0]],
        }
        planned = {
            'steps': [
                {'action': 'walk', 'segment': 1, 'from': [8.5, 16.2], 'to': [7.4, 16.2]},
                {'action': 'jump', 'segment': 2, 'from': [7.4, 16.2], 'to': [7.4, 15.2]},
            ],
        }

        with patch.object(PLUGIN, 'plan_route', return_value=planned):
            PLUGIN._execute_terrain_route(context, plan, '前往 NPC 奋威中郎将')

        self.assertEqual(context.key_events, [])
        self.assertTrue(any('结束整条寻路' in message
                            for _level, message in context.logs))

    def test_minimap_ocr_extracts_map_and_position(self):
        context = FakeContext([[ocr_line('成都·子城 (11, 7)')]])

        state = PLUGIN._scan_minimap(context)

        self.assertEqual(state['map'], '成都·子城')
        self.assertEqual(state['position'], (11, 7))

    def test_custom_route_accepts_compact_and_detailed_waypoints(self):
        context = FakeContext([])
        context.config['navigation_routes'] = {
            '奋威中郎将': {
                'map': '成都·子城',
                'waypoints': [[15, 12], {'x': 11, 'y': 7, 'jump': True}],
            }
        }

        waypoints = PLUGIN._route_waypoints(context, '奋威中郎将', None)

        self.assertEqual([(item['x'], item['y']) for item in waypoints], [(15, 12), (11, 7)])
        self.assertTrue(waypoints[-1]['jump'])

    def test_waypoint_controller_moves_right_then_releases_key(self):
        context = FakeContext([
            [ocr_line('成都·子城 (10, 7)')],
            [ocr_line('成都·子城 (11, 7)')],
        ])

        PLUGIN._move_to_waypoint(
            context,
            {'map': '成都·子城', 'x': 11, 'y': 7, 'jump': False},
            1,
            1,
        )

        self.assertEqual(
            context.key_events,
            [('down', 'right', 'foreground'), ('up', 'right', 'foreground')],
        )


if __name__ == '__main__':
    unittest.main()
