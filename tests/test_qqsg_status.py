"""Mock the atomic F1 transaction; never capture or send real game input."""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from automation import qqsg_status as status
from plugin_platform.sdk import WindowAPI


ROOT = Path(__file__).resolve().parents[1]
ANCHOR = (430, 238)


def panel_items():
    return [{'text': '角色信息', 'center': [499, 306], 'box': []},
            {'text': '角色抗性', 'center': [582, 308], 'box': []}]


def fatigue_items(used=334, limit=2520):
    return [{'text': f'采集疲劳度{used}/{limit}', 'center': [800, 410], 'box': []}]


def load_host_method(name):
    """Compile host methods with mocked platform imports for portable tests."""
    path = ROOT / 'automation/services.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'AutomationHost')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {'Any': object, 'win32gui': Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name], namespace


class F1ReaderTests(unittest.TestCase):
    def setUp(self):
        self.host = Mock()
        self.host.dry_run = False
        self.host.frames = {}
        self.host._activate_bound_window.return_value = True
        self.sleep = patch.object(status.time, 'sleep')
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def scans(self, values):
        iterator = iter(values)

        def scan(host, region=None, variants=('none',), signature=False):
            value = next(iterator)
            if isinstance(value, Exception):
                raise value
            if signature:
                scans, pixels = value
                return scans, 185, 44, pixels
            return value, 1280, 960

        return patch.object(status, '_scan', side_effect=scan)

    def successful_scans(self, initially_open=False):
        values = [] if initially_open else [[[]]]
        values += [[panel_items()], [fatigue_items(), fatigue_items()],
                   ([panel_items(), panel_items()], bytes([0]) * 120),
                   ([[], []], bytes([100]) * 120)]
        return values

    def test_open_hover_read_and_close_without_any_click_or_purchase(self):
        with self.scans(self.successful_scans()):
            result = status.read_gathering_fatigue(self.host)
        self.assertEqual(result['reading'], [334, 2520])
        self.assertTrue(result['ui_restored'])
        self.assertEqual([call.args[0] for call in self.host.keyboard.press.call_args_list], ['f1', 'f1'])
        self.assertEqual(self.host._mouse_move.call_args.args[0]['x'], 725)
        self.host._mouse_click.assert_not_called()

    def test_already_open_panel_is_not_toggled_before_hover(self):
        with self.scans(self.successful_scans(initially_open=True)):
            result = status.read_gathering_fatigue(self.host)
        self.assertEqual(result['reading'], [334, 2520])
        self.host.keyboard.press.assert_called_once_with('f1')

    def test_full_limit_is_returned_without_mining_input(self):
        values = self.successful_scans(initially_open=True)
        values[1] = [fatigue_items(2520), fatigue_items(2520)]
        with self.scans(values):
            result = status.read_gathering_fatigue(self.host)
        self.assertEqual(result['reading'], [2520, 2520])
        self.host.keyboard.press.assert_called_once_with('f1')

    def test_checkout_and_package_warning_never_send_f1(self):
        for label in ('选择数量', '兑换成功', '确定要使用', '是否购买'):
            with self.subTest(label=label):
                self.host.reset_mock()
                with self.scans([[[{'text': label}]]]):
                    result = status.read_gathering_fatigue(self.host)
                self.assertIsNone(result['reading'])
                self.assertFalse(result['ui_restored'])
                self.host.keyboard.press.assert_not_called()
                self.host._mouse_move.assert_not_called()

    def test_missing_panel_has_only_one_opening_attempt_no_blind_mouse(self):
        with self.scans([[[]], [[]]]):
            result = status.read_gathering_fatigue(self.host)
        self.assertIsNone(result['reading'])
        self.assertFalse(result['ui_restored'])
        self.host.keyboard.press.assert_called_once_with('f1')
        self.host._mouse_move.assert_not_called()

    def test_unreadable_tooltip_tries_three_hover_points_then_restores(self):
        values = [[panel_items()]] + [[[], []]] * 3 + [
            ([panel_items(), panel_items()], bytes([0]) * 120),
            ([[], []], bytes([100]) * 120),
        ]
        with self.scans(values):
            result = status.read_gathering_fatigue(self.host)
        self.assertIsNone(result['reading'])
        self.assertTrue(result['ui_restored'])
        self.assertEqual(self.host._mouse_move.call_count, 3)

    def test_conflicting_tooltip_values_are_unknown(self):
        values = self.successful_scans(initially_open=True)
        values[1] = [fatigue_items(334), fatigue_items(335)]
        with self.scans(values):
            result = status.read_gathering_fatigue(self.host)
        self.assertIsNone(result['reading'])
        self.assertIn('冲突', result['reason'])
        self.assertTrue(result['ui_restored'])

    def test_full_window_chat_counter_is_never_accepted_as_tooltip(self):
        values = [[panel_items() + fatigue_items()]] + [[[], []]] * 3 + [
            ([panel_items(), panel_items()], bytes([0]) * 120),
            ([[], []], bytes([100]) * 120),
        ]
        with self.scans(values):
            result = status.read_gathering_fatigue(self.host)
        self.assertIsNone(result['reading'])
        self.assertEqual(self.host._mouse_move.call_count, 3)

    def test_ocr_disappearance_with_unchanged_pixels_does_not_prove_closure(self):
        values = self.successful_scans(initially_open=True)
        values[-1] = ([[], []], bytes([0]) * 120)
        with self.scans(values):
            result = status.read_gathering_fatigue(self.host)
        self.assertIsNone(result['reading'])
        self.assertFalse(result['ui_restored'])

    def test_partial_tab_label_after_close_does_not_prove_closure(self):
        values = self.successful_scans(initially_open=True)
        values[-1] = ([[{'text': '角色信息'}], []], bytes([100]) * 120)
        with self.scans(values):
            result = status.read_gathering_fatigue(self.host)
        self.assertIsNone(result['reading'])
        self.assertFalse(result['ui_restored'])

    def test_moved_panel_is_not_blindly_closed(self):
        values = self.successful_scans(initially_open=True)[:2]
        moved = [{'text': '角色信息', 'center': [509, 306]},
                 {'text': '角色抗性', 'center': [592, 308]}]
        values += [([moved, moved], bytes([0]) * 120)]
        with self.scans(values):
            result = status.read_gathering_fatigue(self.host)
        self.assertIsNone(result['reading'])
        self.assertFalse(result['ui_restored'])
        self.host.keyboard.press.assert_not_called()

    def test_failed_activation_does_not_send_keys_or_capture(self):
        self.host._activate_bound_window.return_value = False
        with patch.object(status, '_scan') as scan:
            result = status.read_gathering_fatigue(self.host)
        self.assertIsNone(result['reading'])
        self.host.keyboard.press.assert_not_called()
        scan.assert_not_called()

    def test_capture_failure_after_hover_is_unknown_and_attempts_verified_cleanup(self):
        values = [[panel_items()], RuntimeError('截图失败'),
                  ([panel_items(), panel_items()], bytes([0]) * 120),
                  ([[], []], bytes([100]) * 120)]
        with self.scans(values):
            result = status.read_gathering_fatigue(self.host)
        self.assertIsNone(result['reading'])
        self.assertTrue(result['ui_restored'])

    def test_dry_run_does_not_focus_capture_or_move(self):
        self.host.dry_run = True
        with patch.object(status, '_scan') as scan:
            result = status.read_gathering_fatigue(self.host)
        self.assertIsNone(result['reading'])
        scan.assert_not_called()
        self.host._activate_bound_window.assert_not_called()
        self.host.keyboard.press.assert_not_called()
        self.host._mouse_move.assert_not_called()

    def test_scan_releases_only_own_temporary_frame_and_offsets_geometry(self):
        self.host.frames = {'previous': object()}

        def capture(params, temporary=False):
            self.assertTrue(temporary)
            self.host.frames['temporary'] = SimpleNamespace(tobytes=lambda: b'123')
            return {'id': 'temporary', 'width': 30, 'height': 40}

        self.host._capture_window.side_effect = capture
        self.host._ocr_recognize.return_value = [{'text': '角色信息', 'center': [3, 4],
                                                  'box': [[0, 0], [6, 0], [6, 8], [0, 8]]}]
        scans, width, height, pixels = status._scan(self.host, (10, 20, 30, 40), signature=True)
        self.assertEqual(scans[0][0]['center'], [13, 24])
        self.assertEqual(scans[0][0]['box'][0], [10, 20])
        self.assertEqual((width, height, pixels), (30, 40, b'123'))
        self.assertEqual(list(self.host.frames), ['previous'])
        self.assertEqual(self.host._validate_bound_window_foreground.call_count, 2)

    def test_scan_failure_releases_temporary_frame(self):
        def capture(params, temporary=False):
            self.host.frames['temporary'] = object()
            return {'id': 'temporary', 'width': 30, 'height': 40}

        self.host._capture_window.side_effect = capture
        self.host._ocr_recognize.side_effect = RuntimeError('OCR 错误')
        with self.assertRaises(RuntimeError):
            status._scan(self.host)
        self.assertEqual(self.host.frames, {})

    def test_foreground_loss_refuses_capture(self):
        self.host._validate_bound_window_foreground.side_effect = RuntimeError('已失去焦点')
        with self.assertRaises(RuntimeError):
            status._scan(self.host)
        self.host._capture_window.assert_not_called()


class F1HostContractTests(unittest.TestCase):
    def test_sdk_uses_single_coordinate_free_rpc(self):
        call = Mock(return_value={'reading': [334, 2520], 'ui_restored': True})
        result = WindowAPI(call).read_gathering_fatigue()
        call.assert_called_once_with('window.gathering_fatigue', {})
        self.assertEqual(result['reading'], [334, 2520])

    def test_f1_rpc_is_one_foreground_operation(self):
        method, _ = load_host_method('_uses_foreground_input')
        self.assertTrue(method('window.gathering_fatigue', {}))

    def test_dispatch_checks_all_permissions_and_uses_one_coordinator_operation(self):
        dispatch, _ = load_host_method('dispatch')
        host = Mock()
        required = {'window.bind', 'screen.capture', 'mouse.foreground', 'keyboard.foreground'}
        host.permissions = required.copy()
        host.input_coordinator.run.side_effect = lambda operation: operation()
        host._window_gathering_fatigue.return_value = {'reading': [334, 2520]}
        host._dispatch_foreground.side_effect = lambda handler, params: handler(params)
        result = dispatch(host, 'window.gathering_fatigue', {})
        self.assertEqual(result, {'reading': [334, 2520]})
        host.input_coordinator.run.assert_called_once()
        for permission in required:
            with self.subTest(permission=permission):
                host.reset_mock()
                host.permissions = required - {permission}
                with self.assertRaises(PermissionError):
                    dispatch(host, 'window.gathering_fatigue', {})
                host.input_coordinator.run.assert_not_called()

    def test_foreground_validation_checks_binding_and_live_foreground(self):
        validate, namespace = load_host_method('_validate_bound_window_foreground')
        host = Mock()
        host._current_window.return_value = SimpleNamespace(hwnd=42)
        namespace['win32gui'].GetForegroundWindow.return_value = 42
        validate(host)
        host._validate_bound_window_identity.assert_called_once()
        namespace['win32gui'].GetForegroundWindow.return_value = 43
        with self.assertRaises(RuntimeError):
            validate(host)


if __name__ == '__main__':
    unittest.main()
