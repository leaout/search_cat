"""Exercise the real batch worker without Windows/Qt/OCR installations."""

import ast
import re
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock

from plugin_platform.line_grid import find_line_target, infer_server_menu_button


def load_worker():
    # Isolate the worker class from the GUI module's optional desktop imports.
    source = (Path(__file__).resolve().parents[1] / 'feature' / 'script_platform_feature.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    node = next(item for item in tree.body if isinstance(item, ast.ClassDef)
                and item.name == 'BatchLineSwitchWorker')

    class Thread:
        def __init__(self, parent=None):
            self.interrupted = False

        def isInterruptionRequested(self):
            return self.interrupted

        def requestInterruption(self):
            self.interrupted = True

    namespace = {
        'QThread': Thread, 'pyqtSignal': lambda *args: Mock(),
        'PluginManager': object, 'AutomationHost': Mock(), 'win32gui': Mock(),
        're': re, 'time': time, 'find_line_target': find_line_target,
        'Event': Event,
        'infer_server_menu_button': infer_server_menu_button,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['BatchLineSwitchWorker'], namespace


class BatchLineSwitchTests(unittest.TestCase):
    def setUp(self):
        self.worker_class, self.namespace = load_worker()
        self.worker = self.worker_class(Mock(), [{'hwnd': 1}, {'hwnd': 2}], 14, False)

    def test_stop_during_ocr_prevents_click_retry_and_next_window(self):
        host = Mock()

        def dispatch(method, params):
            self.worker.requestInterruption()
            return []

        host.dispatch.side_effect = dispatch
        original_dispatch = host.dispatch
        self.namespace['AutomationHost'].return_value = host
        self.worker._window_state = Mock(return_value=(7, 'QQ三国 7线'))

        def switch_once(current_host, info):
            current_host.dispatch('ocr.recognize', {})
            current_host.dispatch('mouse.click', {'x': 10, 'y': 10})

        self.worker._switch_one_once = Mock(side_effect=switch_once)
        self.worker.run()
        self.assertEqual(self.worker._switch_one_once.call_count, 1)
        self.assertEqual([call.args[0] for call in original_dispatch.call_args_list], ['ocr.recognize'])
        host.release_all_keys.assert_called_once()
        host.clear_frames.assert_called_once()
        self.worker.finished_result.emit.assert_called_once_with(0, 0)

    def test_wait_and_title_poll_respect_stop(self):
        self.worker.requestInterruption()
        with self.assertRaises(InterruptedError):
            self.worker._wait(10)
        self.worker._window_state = Mock(return_value=(7, 'QQ三国 7线'))
        self.worker._window_title = Mock(return_value='QQ三国 7线')
        with self.assertRaises(InterruptedError):
            self.worker._wait_for_target_line({'hwnd': 1})

    def test_stop_survives_qt_clearing_thread_interruption(self):
        self.worker.requestInterruption()
        self.worker.interrupted = False
        self.assertTrue(self.worker.isInterruptionRequested())

    def test_normal_scan_uses_only_one_ocr_pass(self):
        host = Mock()
        host.dispatch.side_effect = [
            {'id': 'frame', 'width': 1280, 'height': 960},
            [{'text': '14线', 'center': [695, 578]}],
        ]
        items = self.worker._capture_items(host)
        self.assertEqual(len(host.dispatch.call_args_list), 2)
        self.assertEqual(items[0]['center'], [695, 578])
        host.clear_frames.assert_called_once()

    def test_switch_reuses_confirm_button_from_selector_scan(self):
        host = Mock()
        menu = {'text': '服务器选线', 'center': [640, 540]}
        target = {'text': '14线', 'center': [697, 552]}
        confirm = {'text': '确定', 'center': [585, 690]}
        self.worker._open_server_menu = Mock(return_value=menu)
        self.worker._capture_items = Mock(return_value=[target, confirm])
        self.worker._wait = Mock()
        self.worker._wait_for_target_line = Mock(return_value=(True, 'QQ三国14线', 14))
        self.worker._switch_one_once(host, {'hwnd': 1})
        self.worker._capture_items.assert_called_once_with(host)
        clicks = [call.args[1] for call in host.dispatch.call_args_list if call.args[0] == 'mouse.click']
        self.assertEqual([(p['x'], p['y']) for p in clicks], [(640, 540), (697, 552), (585, 690)])

    def test_enhanced_scan_does_not_swallow_stop(self):
        host = Mock()
        host.dispatch.side_effect = [
            {'id': 'frame', 'width': 1280, 'height': 960}, [], InterruptedError('stop'),
        ]
        with self.assertRaises(InterruptedError):
            self.worker._capture_items(host, include_yellow=True)
        host.clear_frames.assert_called_once()

    def test_all_lines_are_located_from_sparse_grid(self):
        items = [{'text': f'{n}线', 'center': [590 if n % 2 else 695, 398 + (n - 1) // 2 * 30]}
                 for n in (5, 6, 9, 10, 13, 14)]
        for target in range(1, 17):
            with self.subTest(target=target):
                result = self.worker._find_target_line(items, target)
                self.assertEqual(list(result['center']),
                                 [590 if target % 2 else 695, 398 + (target - 1) // 2 * 30])

    def test_footer_chat_and_level_numbers_are_not_line_buttons(self):
        items = [{'text': '当前所在：14线', 'center': [675, 650]},
                 {'text': '推荐14线活动', 'center': [300, 100]},
                 {'text': '14', 'center': [100, 20]},
                 {'text': '13线（繁忙）14线（繁忙）', 'center': [640, 578]}]
        self.assertIsNone(self.worker._find_target_line(items, 14))

    def test_user_log_clipped_13_label_does_not_break_line_5(self):
        items = [{'text': text, 'center': point} for text, point in (
            ('1线（爆满）', [597, 372]), ('7线（爆满）', [595, 462]),
            ('9线（爆满）', [595, 492]), ('11线（繁忙）', [594, 522]),
            ('13线', [571, 552]), ('15线（繁忙）', [595, 581]),
            ('16线（繁忙）', [695, 582]),
        )]
        target = self.worker._find_target_line(items, 5)
        self.assertEqual(target['center'], [595, 432])
        self.assertTrue(target['_consensus_grid'])

    def test_user_first_attempt_clipped_both_columns_locates_line_5(self):
        items = [{'text': text, 'center': point} for text, point in (
            ('7线（爆满）', [596, 462]), ('9线（爆满）', [595, 492]),
            ('13线', [571, 552]), ('15线（繁忙）', [595, 581]),
            ('16线', [675, 582]), ('1线1蝎淋1', [600, 371]),
        )]
        result = self.worker._find_target_line(items, 5)
        self.assertLessEqual(abs(result['center'][0] - 595), 1)
        self.assertLessEqual(abs(result['center'][1] - 432), 1)

    def test_chat_outlier_does_not_poison_panel_consensus(self):
        items = [{'text': f'{n}线（繁忙）', 'center': [595 if n % 2 else 697, 522 + (n - 11) // 2 * 30]}
                 for n in range(11, 17)]
        items.append({'text': '5线白虎仓库', 'center': [176, 808]})
        result = self.worker._find_target_line(items, 7)
        self.assertEqual(result['center'], [595, 462])

    def test_bare_current_line_footer_does_not_shift_missing_line(self):
        items = [{'text': f'{n}线（繁忙）', 'center': [595 if n % 2 else 697, 522 + (n - 11) // 2 * 30]}
                 for n in range(11, 17)]
        items.append({'text': '7线', 'center': [674, 623]})
        result = self.worker._find_target_line(items, 7)
        self.assertEqual(result['center'], [595, 462])

    def test_unsupported_random_positions_do_not_form_a_grid(self):
        items = [{'text': '1线', 'center': [100, 100]},
                 {'text': '7线', 'center': [350, 430]},
                 {'text': '13线', 'center': [800, 700]}]
        self.assertIsNone(self.worker._find_target_line(items, 5))

    def test_all_sixteen_lines_against_both_user_failure_logs(self):
        logs = [
            [('7线（爆满）', [596, 462]), ('9线（爆满）', [595, 492]),
             ('13线', [571, 552]), ('15线（繁忙）', [595, 581]),
             ('16线', [675, 582]), ('1线1蝎淋1', [600, 371])],
            [('1线（爆满）', [597, 372]), ('7线（爆满）', [595, 462]),
             ('9线（爆满）', [595, 492]), ('11线（繁忙）', [594, 522]),
             ('13线', [571, 552]), ('15线（繁忙）', [595, 581]),
             ('16线（繁忙）', [695, 582])],
        ]
        for log_number, log in enumerate(logs, 1):
            for line in range(1, 17):
                with self.subTest(log=log_number, target=line):
                    items = [{'text': text, 'center': point} for text, point in log]
                    result = self.worker._find_target_line(items, line)
                    self.assertIsNotNone(result)
                    x, y = result['center']
                    self.assertLessEqual(abs(y - (372 + (line - 1) // 2 * 30)), 2)
                    self.assertTrue(590 <= x <= 602 if line % 2 else 670 <= x <= 705)

    def test_each_line_missing_with_noise_and_translated_panel(self):
        for offset_x, offset_y in ((0, 0), (-500, -250), (150, 90)):
            for target in range(1, 17):
                with self.subTest(offset=(offset_x, offset_y), target=target):
                    items = [{'text': f'{n}线（繁忙）',
                              'center': [(595 if n % 2 else 695) + offset_x,
                                         372 + (n - 1) // 2 * 30 + offset_y]}
                             for n in range(1, 17) if n != target]
                    items.extend([
                        {'text': f'{target}线白虎仓库', 'center': [176, 808]},
                        {'text': f'当前所在：{target}线', 'center': [674 + offset_x, 623 + offset_y]},
                        {'text': '13线', 'center': [571 + offset_x, 552 + offset_y]},
                    ])
                    result = self.worker._find_target_line(items, target)
                    self.assertIsNotNone(result)
                    self.assertEqual(result['center'],
                                     [(595 if target % 2 else 695) + offset_x,
                                      372 + (target - 1) // 2 * 30 + offset_y])

    def test_target_number_on_wrong_row_is_corrected_using_other_rows(self):
        items = [{'text': f'{n}线', 'center': [590 if n % 2 else 695, 398 + (n - 1) // 2 * 30]}
                 for n in (5, 6, 9, 10, 13, 15, 16)]
        items.append({'text': '14线', 'center': [695, 548]})  # 12 misread as 14.
        result = self.worker._find_target_line(items, 14)
        self.assertEqual(result['center'], [695, 578])
        self.assertTrue(result['_grid_fallback'])

    def test_full_line_modal_is_detected(self):
        items = [{'text': '服务器人数已满，请稍后重试', 'center': [650, 400]},
                 {'text': '确定', 'center': [650, 470]}]
        self.assertTrue(self.worker._is_switch_blocker(items))
        self.assertEqual(self.worker._find_switch_blocker(items)['center'], [650, 470])

    def test_delayed_title_change_prevents_second_submission(self):
        self.worker._window_state = Mock(side_effect=[(7, '7线'), (14, '14线')])
        self.worker._switch_one_once = Mock(side_effect=RuntimeError('still 7线'))
        self.worker._wait = Mock()
        self.worker._switch_one(Mock(), {'hwnd': 1})
        self.worker._switch_one_once.assert_called_once()


if __name__ == '__main__':
    unittest.main()
