import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PLUGIN_MAIN = Path(__file__).resolve().parents[1] / 'plugins' / 'com.searchcat.qqsg.mining' / 'main.py'
SPEC = importlib.util.spec_from_file_location('qqsg_mining_main', PLUGIN_MAIN)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class QQSGMiningTests(unittest.TestCase):
    def test_purchase_pending_survives_restart_and_blocks_duplicate(self):
        context = Mock()
        context.dry_run = False
        context.config = {'pickaxe_character_id': 'test-character', 'pickaxe_wage_budget': 10}
        records = {}
        context.storage.read_json.side_effect = lambda path, default: records.get(path, default)
        context.storage.write_json.side_effect = lambda path, value: records.update({path: value})
        transaction = MODULE._reserve_pickaxe_purchase(context, 100)
        with self.assertRaises(ValueError):
            MODULE._reserve_pickaxe_purchase(context, 100)
        self.assertFalse(MODULE._confirm_pickaxe_purchase(context, transaction, False))
        with self.assertRaises(ValueError):
            MODULE._reserve_pickaxe_purchase(context, 100)
        self.assertTrue(MODULE._confirm_pickaxe_purchase(context, transaction, True))
        MODULE._finish_pickaxe_fulfillment(context, (360, 360))
        transaction = MODULE._reserve_pickaxe_purchase(context, 100)
        MODULE._confirm_pickaxe_purchase(context, transaction, True)
        with self.assertRaises(ValueError):
            MODULE._reserve_pickaxe_purchase(context, 100)
        context.mouse.click.assert_not_called()

    def test_purchase_requires_identity_balance_and_explicit_budget(self):
        context = Mock()
        context.dry_run = False
        context.config = {}
        with self.assertRaises(ValueError):
            MODULE._reserve_pickaxe_purchase(context, 100)
        context.config = {'pickaxe_character_id': 'test', 'pickaxe_wage_budget': 10}
        with self.assertRaises(ValueError):
            MODULE._reserve_pickaxe_purchase(context, 4)
        context.storage.write_json.assert_not_called()

    def _spare_context(self):
        context = Mock()
        context.dry_run = False
        context.config = {'pickaxe_inventory_region': [100, 200, 200, 300],
                          'pickaxe_tooltip_region': [300, 200, 200, 300],
                          'pickaxe_inventory_key': 'i', 'pickaxe_inventory_close_key': 'i'}
        context.windows.activate.return_value = {'active': True}
        context.vision.find_image.return_value = type('Match', (), {'found': True, 'center': [20, 30]})()
        return context

    def test_spare_pickaxe_wrong_name_never_clicked(self):
        context = self._spare_context()
        context.ocr.recognize.side_effect = [[], [{'text': '物品'}], [{'text': '高级精钢矿锄'}]]
        self.assertFalse(MODULE._try_equip_spare_pickaxe(context))
        context.mouse.click.assert_not_called()
        self.assertEqual(context.keyboard.press.call_count, 2)

    def test_verified_spare_uses_client_offset_and_closes_inventory(self):
        context = self._spare_context()
        context.ocr.recognize.side_effect = [[], [{'text': '物品'}], [{'text': '中级精钢矿锄'}], []]
        self.assertTrue(MODULE._try_equip_spare_pickaxe(context))
        self.assertEqual(context.mouse.click.call_count, 2)
        for call in context.mouse.click.call_args_list:
            self.assertEqual(call.args, (120, 230))
            self.assertEqual(call.kwargs['coordinate_space'], 'client')

    def test_shop_item_label_cannot_prove_backpack_is_open(self):
        context = self._spare_context()
        context.ocr.recognize.return_value = [{'text': '物品'}, {'text': '商店物品'}]
        self.assertFalse(MODULE._try_equip_spare_pickaxe(context))
        self.assertEqual(context._pickaxe_spare_state, 'unknown')
        context.vision.find_image.assert_not_called()
        context.mouse.click.assert_not_called()

    def test_failed_spare_is_not_repeated_while_waiting(self):
        context = self._spare_context()
        context.windows.current.return_value = {'hwnd': 123}
        context.config.update({'pickaxe_monitor_enabled': True, 'pickaxe_auto_equip_enabled': True,
                               'pickaxe_region': [10, 10, 180, 40]})
        context.ocr.recognize.side_effect = [[{'text': '0/360'}]] * 3 + [[{'text': '360/360'}]]
        with patch.object(MODULE, '_try_equip_spare_pickaxe', return_value=False) as equip:
            MODULE._ensure_pickaxe_ready(context)
        equip.assert_called_once_with(context)

    def test_pickaxe_reading_requires_unambiguous_360_fraction(self):
        self.assertEqual(MODULE._parse_pickaxe_durability([{'text': '334 ／ 360'}]), (334, 360))
        self.assertEqual(MODULE._parse_pickaxe_durability([{'text': '0/360'}]), (0, 360))
        for text in ('361/360', '12/2040', '334', '34/36'):
            self.assertIsNone(MODULE._parse_pickaxe_durability([{'text': text}]))
        self.assertIsNone(MODULE._parse_pickaxe_durability([
            {'text': '3/360'}, {'text': '8/360'}]))

    def test_pickaxe_unknown_and_depleted_wait_for_manual_recovery(self):
        context = Mock()
        context.dry_run = False
        context.config = {'pickaxe_monitor_enabled': True, 'pickaxe_region': [10, 10, 180, 40]}
        context.windows.current.return_value = {'hwnd': 123}
        context.ocr.recognize.side_effect = [[], [{'text': '0/360'}], [{'text': '360/360'}]]
        MODULE._ensure_pickaxe_ready(context)
        self.assertEqual(context.sleep.call_count, 2)
        states = [call.args[1]['state'] for call in context.storage.write_json.call_args_list]
        self.assertEqual(states, ['unknown', 'depleted', 'ready'])
        context.mouse.click.assert_not_called()
        context.keyboard.press.assert_not_called()

    def test_pickaxe_monitor_requires_crop_and_can_be_disabled(self):
        context = Mock()
        context.dry_run = False
        context.config = {}
        MODULE._ensure_pickaxe_ready(context)
        context.capture.window.assert_not_called()
        context.config = {'pickaxe_monitor_enabled': True}
        with self.assertRaises(ValueError):
            MODULE._ensure_pickaxe_ready(context)

    def test_disappeared_pickaxe_requires_repeated_empty_scans(self):
        context = Mock()
        context.dry_run = False
        context.config = {'pickaxe_monitor_enabled': True, 'pickaxe_region': [10, 10, 180, 40]}
        context.windows.current.return_value = {'hwnd': 123}
        context.ocr.recognize.side_effect = [[], [], [], [{'text': '360/360'}]]
        MODULE._ensure_pickaxe_ready(context)
        records = [call.args[1] for call in context.storage.write_json.call_args_list]
        self.assertEqual([record['state'] for record in records], ['unknown', 'missing_suspected', 'ready'])
        self.assertEqual(records[1]['next_action'], 'replenish_or_verify')
        self.assertEqual(context.sleep.call_count, 3)
        context.keyboard.press.assert_not_called()
        context.mouse.click.assert_not_called()

    def test_unreadable_visible_label_is_not_missing(self):
        context = Mock()
        context.dry_run = False
        context.config = {'pickaxe_monitor_enabled': True, 'pickaxe_region': [10, 10, 180, 40]}
        context.windows.current.return_value = {'hwnd': 123}
        context.ocr.recognize.side_effect = [[{'text': '矿锄'}]] * 3 + [[{'text': '360/360'}]]
        MODULE._ensure_pickaxe_ready(context)
        states = [call.args[1]['state'] for call in context.storage.write_json.call_args_list]
        self.assertEqual(states, ['unknown', 'ready'])

    def test_detached_current_line_footer_does_not_poison_grid(self):
        items = [{'text': f'{n}线（繁忙）', 'center': point}
                 for n, point in ((11, [595, 522]), (12, [697, 521]),
                                  (13, [595, 552]), (14, [697, 552]),
                                  (15, [595, 582]), (16, [696, 582]))]
        items.extend([{'text': '14线', 'center': [674, 623]},
                      {'text': '卖的5线白虎仓库摆20.5收1级', 'center': [176, 808]}])
        target = MODULE._find_target_line(items, 7)
        self.assertIsNotNone(target)
        self.assertAlmostEqual(target['center'][0], 595, delta=1)
        self.assertAlmostEqual(target['center'][1], 462, delta=1)

    def test_merged_bottom_rows_locate_missing_upper_line(self):
        items = []
        for left in (11, 13, 15):
            y = 398 + ((left - 1) // 2) * 30
            items.append({'text': f'{left}线（繁忙）{left + 1}线（繁忙）',
                          'box': [[537, y - 9], [747, y - 9], [747, y + 9], [537, y + 9]]})
        target = MODULE._find_target_line(items, 7)
        self.assertIsNotNone(target)
        self.assertEqual(target['center'], [590, 488])

    def test_merged_chat_is_not_a_selector_row(self):
        items = [{'text': '活动11线12线', 'box': [[537, 540], [747, 540], [747, 560], [537, 560]]}]
        self.assertIsNone(MODULE._find_target_line(items, 7))

    def test_empty_region_means_full_client(self):
        self.assertIsNone(MODULE._valid_region([]))
        self.assertEqual(MODULE._valid_region([1, 2, 30, 40]), (1, 2, 30, 40))

    def test_invalid_region_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE._valid_region([0, 0, 0, 10])
        with self.assertRaises(ValueError):
            MODULE._valid_region([0, 0, 10])

    def test_match_point_adds_region_offset(self):
        match = type('Match', (), {'found': True, 'center': [12, 8]})()
        self.assertEqual(MODULE._match_point(match, (100, 200, 300, 400)), (112, 208))
        self.assertIsNone(MODULE._match_point(type('Match', (), {'found': False})(), None))

    def test_fallback_points_ignore_malformed_entries(self):
        self.assertEqual(
            MODULE._fallback_points([[10, 20], ['bad', 3], [1], [-2, 4], [30, 40, 50]]),
            [(10, 20), (30, 40)],
        )

    def test_line_switch_ocr_matching_prefers_short_target(self):
        items = [
            {'text': '推荐14线活动', 'center': [20, 20]},
            {'text': '14线', 'center': [30, 40]},
        ]
        self.assertEqual(MODULE._find_target_line(items, 14)['text'], '14线')

    def test_line_switch_grid_does_not_guess_missing_column(self):
        items = [
            {'text': '13线（繁忙）', 'center': [80, 340], '_frame_width': 313},
            {'text': '15线（繁忙）', 'center': [80, 374], '_frame_width': 313},
        ]
        target = MODULE._find_target_line(items, 14)
        self.assertEqual(target['center'], [199, 340])
        self.assertTrue(target['_inferred_column'])

    def test_line_switch_grid_fallback_infers_missing_target_row(self):
        # OCR may return only 5/15/16 while the 13/14 row is fully missed.
        # The row geometry still identifies the 14-line click position.
        items = [
            {'text': '5线（繁忙）', 'center': [80, 170], '_frame_width': 313, '_frame_height': 450},
            {'text': '15线（繁忙）', 'center': [80, 340], '_frame_width': 313, '_frame_height': 450},
            {'text': '16线（繁忙）', 'center': [207, 340], '_frame_width': 313, '_frame_height': 450},
        ]
        target = MODULE._find_target_line(items, 14)
        self.assertTrue(target['_grid_fallback'])
        self.assertEqual(target['center'], [207, 306])

    def test_grid_tracks_panel_translation_not_client_size(self):
        items = [
            {'text': '5线（繁忙）', 'center': [590, 430], '_frame_width': 1280},
            {'text': '15线（繁忙）', 'center': [590, 580], '_frame_width': 1280},
            {'text': '16线（繁忙）', 'center': [695, 580], '_frame_width': 1280},
            {'text': '当前所在：7线', 'center': [660, 625]},
            {'text': '91线', 'center': [100, 100]},
        ]
        self.assertEqual(MODULE._find_target_line(items, 14)['center'], [695, 550])
        for item in items:
            item['center'] = [item['center'][0] - 500, item['center'][1] - 250]
            item['_frame_width'] = 280
        self.assertEqual(MODULE._find_target_line(items, 14)['center'], [195, 300])

    def test_grid_rejects_inconsistent_rows(self):
        items = [
            {'text': '5线', 'center': [80, 170]},
            {'text': '13线', 'center': [80, 310]},
            {'text': '15线', 'center': [80, 340]},
            {'text': '16线', 'center': [207, 220]},
        ]
        self.assertIsNone(MODULE._find_target_line(items, 14))

    def test_sparse_middle_rows_locate_all_sixteen_lines(self):
        items = [{'text': f'{n}线（繁忙）', 'center': [590 if n % 2 else 695, 398 + ((n - 1) // 2) * 30]}
                 for n in (5, 6, 9, 10, 13, 14)]
        for target in range(1, 17):
            with self.subTest(target=target):
                result = MODULE._find_target_line(items, target)
                self.assertIsNotNone(result)
                self.assertEqual(list(result['center']),
                                 [590 if target % 2 else 695, 398 + ((target - 1) // 2) * 30])

    def test_missing_right_column_locates_first_and_last_rows(self):
        items = [{'text': f'{n}线', 'center': [590, 398 + ((n - 1) // 2) * 30]} for n in (5, 9, 13)]
        for target in (1, 2, 15, 16):
            result = MODULE._find_target_line(items, target)
            self.assertEqual(result['center'],
                             [590 if target % 2 else 695, 398 + ((target - 1) // 2) * 30])

    def test_current_line_footer_and_merged_row_are_not_click_targets(self):
        items = [{'text': '当前所在：14线', 'center': [675, 650]},
                 {'text': '13线（繁忙）14线（繁忙）', 'center': [640, 578]}]
        self.assertIsNone(MODULE._find_target_line(items, 14))

    def test_target_number_on_wrong_row_is_corrected(self):
        items = [{'text': f'{n}线', 'center': [590 if n % 2 else 695, 398 + ((n - 1) // 2) * 30]}
                 for n in (5, 6, 9, 10, 13, 15, 16)]
        items.append({'text': '14线', 'center': [695, 548]})
        result = MODULE._find_target_line(items, 14)
        self.assertEqual(result['center'], [695, 578])
        self.assertTrue(result['_grid_fallback'])

    def test_nearby_lines_locate_14_despite_unrelated_ocr(self):
        items = [
            {'text': '1线', 'center': [140, 130]},
            {'text': '7线', 'center': [620, 330]},
            {'text': '13线（正常）', 'center': [590, 578]},
            {'text': '15线（正常）', 'center': [590, 608]},
            {'text': '16线（繁忙）', 'center': [700, 608]},
        ]
        target = MODULE._find_target_line(items, 14)
        self.assertEqual(target['center'], [700, 578])
        self.assertTrue(target['_nearby_fallback'])

    def test_neighboring_left_labels_only_locate_14(self):
        items = [
            {'text': '1线（爆满）', 'center': [155, 220]},
            {'text': '7线（繁忙）', 'center': [590, 398]},
            {'text': '9线（繁忙）', 'center': [592, 428]},
            {'text': '13线（正常）', 'center': [590, 578]},
            {'text': '15线（繁忙）', 'center': [591, 608]},
        ]
        target = MODULE._find_target_line(items, 14)
        self.assertEqual(target['center'], [696, 578])
        self.assertTrue(target['_inferred_column'])

    def test_build36_missing_right_column_uses_panel_pitch(self):
        items = [{'text': f'{n}线（繁忙）', 'center': [590, 370 + ((n - 1) // 2) * 30]}
                 for n in (1, 5, 7, 9, 11, 13, 15)]
        target = MODULE._find_target_line(items, 14)
        self.assertEqual(target['center'], [695, 550])
        self.assertTrue(target['_inferred_column'])
        items[-1]['center'][1] += 20
        self.assertIsNone(MODULE._find_target_line(items, 14))

    def test_server_button_from_other_system_menu_rows(self):
        items = [
            {'text': '返回登录窗口', 'center': [645, 433]},
            {'text': '重新选择角色', 'center': [645, 468]},
            {'text': '在线客服', 'center': [645, 503]},
            {'text': '数据隐私保护助手', 'center': [645, 573]},
            {'text': '退出游戏', 'center': [645, 643]},
        ]
        button = MODULE._find_server_button(items)
        self.assertEqual(button['center'], [645, 538])
        self.assertTrue(button['_menu_fallback'])

    def test_line_switch_retries_until_title_changes(self):
        class FakeContext:
            dry_run = False
            config = {'line_switch_max_attempts': 4, 'line_switch_retry_wait': 0.1}

            def __init__(self):
                self.title = 'QQ三国 7线'
                self.messages = []
                self.windows = type('Windows', (), {'current': lambda outer: {'title': self.title}})()

            def log(self, message, _level='info'):
                self.messages.append(message)

        context = FakeContext()
        attempts = []

        def attempt(_context, _line):
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError('服务器人数已满')
            context.title = 'QQ三国 14线'

        with patch.object(MODULE, '_switch_line_once', side_effect=attempt), \
                patch.object(MODULE, '_dismiss_switch_failure') as dismiss, \
                patch.object(MODULE, '_wait'):
            MODULE._switch_line(context, 14)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(dismiss.call_count, 2)

    def test_line_switch_stops_after_configured_attempts(self):
        class FakeContext:
            dry_run = False
            config = {'line_switch_max_attempts': 2}
            windows = type('Windows', (), {'current': lambda self: {'title': 'QQ三国 7线'}})()

            def log(self, *_args):
                pass

        with patch.object(MODULE, '_switch_line_once', side_effect=RuntimeError('人数已满')) as attempt, \
                patch.object(MODULE, '_dismiss_switch_failure'), patch.object(MODULE, '_wait'):
            with self.assertRaisesRegex(RuntimeError, '2 次尝试后'):
                MODULE._switch_line(FakeContext(), 14)
        self.assertEqual(attempt.call_count, 2)

    def test_switch_failure_dialog_is_acknowledged_before_retry(self):
        class FakeContext:
            dry_run = False

            def __init__(self):
                self.clicked = []
                self.mouse = type('Mouse', (), {
                    'click': lambda _mouse, x, y, **_kwargs: self.clicked.append((x, y)),
                    'move': lambda *_args, **_kwargs: None,
                })()

            def log(self, *_args):
                pass

        context = FakeContext()
        items = [
            {'text': '您当前在副本地图中，不能切换服务器', 'center': [300, 180]},
            {'text': '确定', 'center': [305, 235]},
        ]
        with patch.object(MODULE, '_ocr_client', return_value=items), patch.object(MODULE, '_wait'):
            MODULE._dismiss_switch_failure(context)
        self.assertEqual(context.clicked, [(305, 235)])

    def test_build36_menu_geometry_when_ocr_reads_no_buttons(self):
        item = {'text': '系统', 'center': [550, 300], '_frame_width': 1280, '_frame_height': 960}
        self.assertEqual(MODULE._build36_server_button([item])['center'], [644, 514])
        item['_frame_width'] = 640
        self.assertIsNone(MODULE._build36_server_button([item]))

    def test_action_validation_and_jump_flag(self):
        actions = MODULE._normalize_actions([
            {'direction': 'right', 'seconds': 2, 'jump': True, 'g_count': 2},
        ], 'patrol_route')
        self.assertEqual(actions[0]['direction'], 'right')
        self.assertTrue(actions[0]['jump'])
        self.assertEqual(actions[0]['g_count'], 2)
        with self.assertRaises(ValueError):
            MODULE._normalize_actions([{'direction': 'teleport', 'seconds': 1}], 'travel_actions')

    def test_patrol_flow_runs_in_dry_run(self):
        class FakeWindows:
            def current(self):
                return {'title': 'QQ三国测试窗口'}

            def is_alive(self):
                return True

        class FakeKeyboard:
            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        class FakeDebug:
            def watch(self, *_args, **_kwargs):
                return None

        class FakeContext:
            dry_run = True
            config = {
                'target_line': 14,
                'switch_line_enabled': True,
                'skip_travel': False,
                'travel_actions': [{'direction': 'right', 'seconds': 0.1}],
                'patrol_route': [{'direction': 'left', 'seconds': 0.1, 'g_count': 1}],
                'patrol_loops': 1,
                'refresh_wait_enabled': False,
                'mine_entry_wait': 0,
                'g_interval': 0.1,
            }
            windows = FakeWindows()
            keyboard = FakeKeyboard()
            debug = FakeDebug()

            def log(self, *_args, **_kwargs):
                return None

            def sleep(self, _seconds):
                return None

            def step(self, _name):
                class Step:
                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        return False

                return Step()

        MODULE.on_start(FakeContext())


if __name__ == '__main__':
    unittest.main()
