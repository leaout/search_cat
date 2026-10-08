"""Portable tests: mocked UI only, never control a running game."""

import ast
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from automation import qqsg_code_navigation as host_nav
from plugin_platform import qqsg_code_navigation as nav
from plugin_platform.sdk import WindowAPI
from tests.test_qqsg_status import load_host_method
from tests.test_qqsg_mining import MODULE as mining
from tests.test_official_task_navigation import PLUGIN as official


def panel():
    return [{'text': label, 'center': [x, 304]} for label, x in [('好友', 429), ('队伍', 472), ('军团', 514)]]


def prompt():
    return [{'text': '请输入添加好友的名称：', 'center': [624, 465]},
            {'text': '确定', 'center': [572, 547]}, {'text': '取消', 'center': [677, 547]}]


class ProtocolTests(unittest.TestCase):
    def test_historical_format_and_raw_units(self):
        self.assertEqual(nav.navigation_code(23, 1300, 1600), '/<DnpcWalkEx=23|1300|1600>/123456</C04>')
        self.assertIn('55|5182|776', nav.navigation_code(55, 5182, 776))

    def test_invalid_parameters_never_build_arbitrary_code(self):
        for args in [(True, 1, 1), (0, 1, 1), (70000, 1, 1), (23, -1, 1), (23, 1.1, 1),
                     (23, '1>/malicious', 1), (23, 1, 100001)]:
            with self.assertRaises(ValueError):
                nav.navigation_code(*args)

    def test_panel_translation_but_not_scaling_or_duplicates(self):
        self.assertEqual(nav.social_anchor(panel()), (429, 304))
        moved = [{**item, 'center': [item['center'][0] + 100, item['center'][1] + 60]} for item in panel()]
        self.assertEqual(nav.social_anchor(moved), (529, 364))
        self.assertIsNone(nav.social_anchor(panel() + [panel()[0]]))
        self.assertIsNone(nav.social_anchor([{'text': '好友', 'center': [100, 100]},
                                             {'text': '队伍', 'center': [186, 100]}]))

    def test_prompt_and_link_are_exact_and_inside_field(self):
        self.assertEqual(nav.input_anchor(prompt()), (624, 465))
        link = {'text': '123456', 'center': [620, 497]}
        self.assertEqual(nav.link_point([link], (624, 465)), (620, 497))
        for items in [[{**link, 'text': '用户123456'}], [{**link, 'center': [100, 497]}], [link, link]]:
            self.assertIsNone(nav.link_point(items, (624, 465)))

    def test_real_screenshot_tabs_ignore_chat_guild_and_missing_friend(self):
        # Offline PaddleOCR output from the two supplied Build36 screenshots.
        for team_x, black_y in [(472.0, 304.5), (472.5, 305.5)]:
            items = [{'text': label, 'center': center} for label, center in [
                ('队伍', [team_x, 305.5]), ('结拜', [597.5, 305.0]),
                ('情侣', [641.0, 305.5]), ('敌对', [683.0, 305.5]),
                ('黑名单', [727.0, black_y]), ('军团', [222.0, 910.0]),
                ('好友数量：4/200', [578.0, 627.5]),
            ]]
            anchor = nav.social_anchor(items)
            self.assertIsNotNone(anchor)
            self.assertLessEqual(abs(anchor[0] - 429), 1)
            self.assertLessEqual(abs(anchor[1] - 305), 1)
            # Genuine second matching tab row is ambiguous, not an outlier.
            self.assertIsNone(nav.social_anchor(items + [
                {'text': '好友', 'center': [100, 100]}, {'text': '队伍', 'center': [143, 100]},
            ]))

    def test_real_cropped_tabs_and_single_label_do_not_guess(self):
        items = [{'text': label, 'center': center} for label, center in [
            ('好友', [430, 303.8]), ('队伍', [471.5, 305.5]), ('师徒', [555.5, 305.5]),
        ]]
        self.assertEqual(nav.social_anchor(items), (429, 305))
        self.assertIsNone(nav.social_anchor([items[0]]))
        self.assertIsNone(nav.social_anchor([{'text': '好友', 'center': [float('nan'), 100]}]))

    def test_minimap_requires_name_and_unique_parenthesized_position(self):
        names = list(nav.MINING_MAPS.values())
        self.assertEqual(nav.minimap_state([{'text': '江陵东郊（17，6）'}], names),
                         {'map_name': '江陵东郊', 'position': [17, 6]})
        for text in ['军团地图(17,6)', '江陵准备区(17,6)', '江陵 17 6', '江陵(1,2)(3,4)',
                     '江陵(1,2)黄石矿洞二层(1,2)', '生命334/360']:
            self.assertIsNone(nav.minimap_state([{'text': text}], names), text)

    def test_sdk_uses_one_transaction_and_explicit_names(self):
        call = Mock(return_value={})
        api = WindowAPI(call)
        api.navigate_by_code(907, 1000, 570)
        call.assert_called_once_with('window.navigate_by_code', {'map_id': 907, 'x': 1000, 'y': 570})
        call.reset_mock()
        api.read_navigation_state(['江陵'])
        call.assert_called_once_with('window.navigation_state', {'map_names': ['江陵']})


class HostTransactionTests(unittest.TestCase):
    def setUp(self):
        self.host = Mock()
        keyboard_path = Path(__file__).resolve().parents[1] / 'core' / 'winoperator.py'
        keyboard_class = next(node for node in ast.parse(keyboard_path.read_text(encoding='utf-8')).body
                              if isinstance(node, ast.ClassDef) and node.name == 'Win32Keyboard')
        self.host.keyboard = Mock(spec=[node.name for node in keyboard_class.body if isinstance(node, ast.FunctionDef)])
        self.host.dry_run = False
        self.host._activate_bound_window.return_value = True
        self.params = {'map_id': 907, 'x': 1000, 'y': 570}
        self.sleep = patch.object(host_nav.time, 'sleep')
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def scans(self, initially_open=False, prompt_open=False, unchanged=False,
              lost_parent=False, lost_prompt=False, moved_tabs=False):
        # Initial UI, F4, switch to friends, add dialog, generated link,
        # after click, cancel, close-before pixels, close-after pixels.
        rows = [prompt() + panel()] if prompt_open else [panel() if initially_open else []]
        if not initially_open and not prompt_open:
            rows += [panel()]
        if not prompt_open:
            rows += [panel(), prompt() + panel()]
        rows += [[{'text': '123456', 'center': [620, 497]}],
                 [] if lost_prompt else prompt() + panel(), [] if lost_parent else panel()]
        pixels = [bytes([0]) * 120, bytes([0 if unchanged else 100]) * 120]
        iterator = iter(rows)

        def scan(host, region=None, variants=('none',), signature=False):
            if signature:
                data = pixels.pop(0)
                tabs = [{**item, 'center': [item['center'][0] + 100, item['center'][1]]}
                        for item in panel()] if moved_tabs else panel()
                return ([tabs] if pixels else [[]]), 344, 28, data
            return [next(iterator)], 1280, 960
        return patch.object(host_nav, '_scan', side_effect=scan)

    def test_complete_sequence_never_confirms_or_sends_chat(self):
        with self.scans():
            result = host_nav.start_code_navigation(self.host, self.params)
        self.assertTrue(result['clicked'])
        self.assertTrue(result['ui_restored'])
        self.assertEqual([call.args for call in self.host.keyboard.press.call_args_list], [('f4',)])
        self.host.keyboard.press_combination.assert_called_once_with('ctrl', 'a')
        points = [(call.args[0]['x'], call.args[0]['y']) for call in self.host._mouse_click.call_args_list]
        self.assertEqual(points, [(429, 304), (670, 625), (624, 497), (620, 497), (677, 547), (775, 265)])
        self.assertNotIn((572, 547), points)
        self.host._keyboard_type_text.assert_called_once_with({'text': nav.navigation_code(907, 1000, 570),
                                                               'mode': 'foreground'})

    def test_existing_panel_does_not_toggle_f4(self):
        with self.scans(initially_open=True):
            self.assertTrue(host_nav.start_code_navigation(self.host, self.params)['ui_restored'])
        self.host.keyboard.press.assert_not_called()

    def test_existing_input_does_not_open_another_dialog(self):
        with self.scans(prompt_open=True):
            self.assertTrue(host_nav.start_code_navigation(self.host, self.params)['clicked'])
        self.assertEqual(self.host._mouse_click.call_count, 4)
        self.host.keyboard.press.assert_not_called()

    def test_empty_ocr_does_not_prove_panel_closed(self):
        with self.scans(unchanged=True):
            result = host_nav.start_code_navigation(self.host, self.params)
        self.assertFalse(result['ui_restored'])

    def test_cancel_parent_ocr_miss_still_requires_cropped_close(self):
        with self.scans(lost_parent=True):
            result = host_nav.start_code_navigation(self.host, self.params)
        self.assertTrue(result['ui_restored'])
        self.assertEqual(self.host._mouse_click.call_args.args[0]['x'], 775)

    def test_post_link_prompt_ocr_miss_is_not_restored(self):
        with self.scans(lost_prompt=True):
            result = host_nav.start_code_navigation(self.host, self.params)
        self.assertTrue(result['clicked'])
        self.assertFalse(result['ui_restored'])
        self.assertEqual(self.host._mouse_click.call_count, 4)

    def test_different_cropped_tab_position_refuses_close(self):
        with self.scans(moved_tabs=True):
            result = host_nav.start_code_navigation(self.host, self.params)
        self.assertFalse(result['ui_restored'])
        self.assertEqual(self.host._mouse_click.call_count, 5)

    def test_input_prompt_without_parent_refuses_typing(self):
        with patch.object(host_nav, '_read', return_value=([prompt()], 1280, 960)):
            with self.assertRaises(RuntimeError):
                host_nav.start_code_navigation(self.host, self.params)
        self.host._keyboard_type_text.assert_not_called()
        self.host._mouse_click.assert_not_called()

    def test_dry_run_does_not_focus_capture_or_input(self):
        self.host.dry_run = True
        result = host_nav.start_code_navigation(self.host, self.params)
        self.assertFalse(result['clicked'])
        self.host._activate_bound_window.assert_not_called()
        self.host.keyboard.press.assert_not_called()

    def test_purchase_modal_blocks_all_input(self):
        with patch.object(host_nav, '_read', return_value=([[{'text': '选择数量'}]], 1280, 960)):
            with self.assertRaises(RuntimeError):
                host_nav.start_code_navigation(self.host, self.params)
        self.host.keyboard.press.assert_not_called()
        self.host._mouse_click.assert_not_called()

    def test_unrecognized_panel_does_not_blindly_click(self):
        with patch.object(host_nav, '_read', return_value=([[]], 1280, 960)):
            with self.assertRaises(RuntimeError):
                host_nav.start_code_navigation(self.host, self.params)
        self.host._mouse_click.assert_not_called()
        self.host._keyboard_type_text.assert_not_called()

    def test_unrecognized_link_never_clicks_confirm(self):
        with patch.object(host_nav, '_read', side_effect=[([prompt() + panel()], 1280, 960), ([[]], 210, 50)]):
            with self.assertRaises(RuntimeError):
                host_nav.start_code_navigation(self.host, self.params)
        self.assertEqual(self.host._mouse_click.call_count, 1)

    def test_lost_focus_refuses_input(self):
        self.host._validate_bound_window_foreground.side_effect = RuntimeError('lost focus')
        with patch.object(host_nav, '_read', return_value=([panel()], 1280, 960)):
            with self.assertRaises(RuntimeError):
                host_nav.start_code_navigation(self.host, self.params)
        self.host._mouse_click.assert_not_called()

    def test_state_crop_releases_frame_and_rejects_disagreement(self):
        self.host.frames = {'temp': object()}
        self.host._capture_window.return_value = {'id': 'temp', 'width': 1280, 'height': 960}
        scans = [[{'text': '黄石矿洞二层(10,5)'}], [{'text': '黄石矿洞二层(11,5)'}]]
        with patch.object(host_nav, '_scan', return_value=(scans, 290, 185)) as scan:
            self.assertIsNone(host_nav.read_navigation_state(self.host))
        self.assertEqual(self.host.frames, {})
        self.assertEqual(scan.call_args.args[1], (990, 0, 290, 185))


class ArrivalTests(unittest.TestCase):
    def setUp(self):
        self.context = Mock()
        self.context.dry_run = False
        self.context.windows.is_alive.return_value = True
        self.context.windows.navigate_by_code.return_value = {'clicked': True, 'ui_restored': True}
        self.start = {'map_name': '江陵', 'position': [17, 6]}
        self.target = {'map_name': '黄石矿洞二层', 'position': [10, 5]}

    def run_nav(self):
        nav.navigate_and_wait(self.context, 907, 1000, 570, '黄石矿洞二层', start_map='江陵')

    def test_two_fresh_target_observations_are_required(self):
        self.context.windows.read_navigation_state.side_effect = [self.start, self.target, None, self.target, self.target]
        self.run_nav()
        self.assertEqual(self.context.windows.read_navigation_state.call_count, 5)
        self.assertEqual(self.context.storage.write_json.call_args.args[1]['state'], 'arrived')
        self.context.keyboard.press.assert_not_called()

    def test_wrong_start_map_never_opens_code_dialog(self):
        self.context.windows.read_navigation_state.return_value = {'map_name': '军团地图', 'position': [17, 6]}
        with self.assertRaises(RuntimeError):
            self.run_nav()
        self.context.windows.navigate_by_code.assert_not_called()

    def test_timeout_does_not_mean_success_or_reclick(self):
        self.context.windows.read_navigation_state.return_value = self.start
        with patch.object(nav.time, 'monotonic', side_effect=[0, 999]):
            with self.assertRaises(RuntimeError):
                self.run_nav()
        self.context.windows.navigate_by_code.assert_called_once()
        self.assertEqual(self.context.storage.write_json.call_args.args[1]['state'], 'failed')
        self.context.keyboard.press.assert_not_called()

    def test_unrestored_ui_blocks_monitoring(self):
        self.context.windows.read_navigation_state.return_value = self.start
        self.context.windows.navigate_by_code.return_value = {'clicked': True, 'ui_restored': False}
        with self.assertRaises(RuntimeError):
            self.run_nav()
        self.assertEqual(self.context.windows.read_navigation_state.call_count, 1)

    def test_already_arrived_needs_two_reads_not_history(self):
        self.context.windows.read_navigation_state.return_value = self.target
        self.run_nav()
        self.assertEqual(self.context.windows.read_navigation_state.call_count, 2)
        self.context.windows.navigate_by_code.assert_not_called()
        self.context.storage.read_json.assert_not_called()

    def test_dry_run_has_no_game_or_checkpoint_side_effects(self):
        self.context.dry_run = True
        self.run_nav()
        self.context.windows.read_navigation_state.assert_not_called()
        self.context.windows.navigate_by_code.assert_not_called()
        self.context.storage.write_json.assert_not_called()

    def test_code_only_mining_debug_skips_all_other_actions(self):
        self.context.config = {'code_navigation_only': True}
        with patch.object(mining, '_travel_by_code') as travel, \
                patch.object(mining, '_switch_line') as switch, \
                patch.object(mining, '_ensure_pickaxe_ready') as pickaxe, \
                patch.object(mining, '_ensure_gathering_fatigue') as fatigue:
            self.context.step.return_value.__enter__ = Mock()
            self.context.step.return_value.__exit__ = Mock(return_value=False)
            mining.on_start(self.context)
        travel.assert_called_once_with(self.context)
        switch.assert_not_called()
        pickaxe.assert_not_called()
        fatigue.assert_not_called()

    def test_normal_mining_refuses_town_code_target(self):
        self.context.config = {'code_target_map_id': 55, 'travel_mode': 'code'}
        with patch.object(mining, 'navigate_and_wait') as navigate, \
                patch.object(mining, '_ensure_gathering_fatigue') as fatigue:
            with self.assertRaises(ValueError):
                mining.on_start(self.context)
        navigate.assert_not_called()
        fatigue.assert_not_called()

    def test_debug_navigation_allows_town_target(self):
        self.context.config = {'code_target_map_id': 55, 'code_navigation_only': True}
        with patch.object(mining, 'navigate_and_wait') as navigate:
            mining._travel_by_code(self.context)
        self.assertEqual(navigate.call_args.args[1], 55)

    def test_schema_keeps_legacy_actions_as_default(self):
        path = Path(mining.__file__).with_name('config.schema.json')
        schema = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(schema['properties']['travel_mode']['default'], 'actions')

    def test_official_restore_multiplies_minimap_coordinates_only_once(self):
        self.context.config = {'navigation_routes': {'诸葛亮': {'map': '成都.子城'}}}
        with patch.object(nav, 'navigate_and_wait') as navigate:
            official._navigate_by_code(self.context, '诸葛亮', [23, 13, 16])
        self.assertEqual(navigate.call_args.args[1:], (23, 1300, 1600, '成都.子城'))

    def test_official_code_switch_does_not_use_manual_terrain(self):
        self.context.config = {'coordinate_navigation_mode': 'code'}
        with patch.object(official, '_navigate_by_code') as navigate, \
                patch.object(official, '_navigate_route') as terrain:
            official._navigate_to_target(self.context, '诸葛亮', [23, 13, 16], None)
        navigate.assert_called_once()
        terrain.assert_not_called()


class DispatchTests(unittest.TestCase):
    def test_atomic_transaction_requires_all_four_permissions(self):
        dispatch, _ = load_host_method('dispatch')
        permissions = ['window.bind', 'screen.capture', 'mouse.foreground', 'keyboard.foreground']
        for missing in permissions:
            host = Mock()
            host.permissions = [permission for permission in permissions if permission != missing]
            with self.assertRaises(PermissionError):
                dispatch(host, 'window.navigate_by_code', {'map_id': 907, 'x': 1000, 'y': 570})
            host.input_coordinator.run.assert_not_called()
        host = Mock()
        host.permissions = permissions
        host._uses_foreground_input.return_value = True
        dispatch(host, 'window.navigate_by_code', {'map_id': 907, 'x': 1000, 'y': 570})
        host.input_coordinator.run.assert_called_once()

    def test_navigation_state_also_requires_capture_permission(self):
        dispatch, _ = load_host_method('dispatch')
        host = Mock()
        host.permissions = ['window.bind']
        with self.assertRaises(PermissionError):
            dispatch(host, 'window.navigation_state', {})

    def test_both_navigation_rpcs_use_foreground_lock(self):
        method, _ = load_host_method('_uses_foreground_input')
        for name in ['window.navigate_by_code', 'window.navigation_state']:
            self.assertTrue(method(name, {}))


if __name__ == '__main__':
    unittest.main()
