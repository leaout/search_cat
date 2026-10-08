"""Mock multi-window automation without loading Qt or sending Windows input."""

import ast
import re
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


def load_worker():
    class Thread:
        def __init__(self):
            pass

        def requestInterruption(self):
            pass

    namespace = {'QThread': Thread, 'pyqtSignal': lambda *args: Mock(), 'Event': Event,
                 'Path': Path, 'AutomationHost': Mock(), 'GLOBAL_FOREGROUND_INPUT': Mock(), 're': re}
    old_tree = ast.parse((ROOT / 'feature/window_key_feature.py').read_text(encoding='utf-8'))
    names = {'_parse_repeat_suffix', 'WindowKeyWorker'}
    old_nodes = [node for node in old_tree.body if getattr(node, 'name', '') in names]
    exec(compile(ast.Module(body=old_nodes, type_ignores=[]), '<key-parser>', 'exec'), namespace)
    tree = ast.parse((ROOT / 'feature/automation_feature.py').read_text(encoding='utf-8'))
    names = {'DEFAULT_PROFILE', '_normalise_profile', 'MultiWindowAutomationWorker'}
    nodes = [node for node in tree.body if getattr(node, 'name', '') in names
             or isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                                                     and target.id in names for target in node.targets)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<multi-automation>', 'exec'), namespace)
    namespace['GLOBAL_FOREGROUND_INPUT'].run.side_effect = lambda operation: operation()
    return namespace['MultiWindowAutomationWorker'], namespace


def load_feature_method(name):
    path = ROOT / 'feature/automation_feature.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'AutomationFeature')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {'win32gui': Mock(), 'MultiWindowAutomationWorker': Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name], namespace


class MultiWindowWorkerTests(unittest.TestCase):
    def setUp(self):
        self.worker_class, self.ns = load_worker()
        self.windows = [{'hwnd': 1, 'pid': 11, 'title': '甲'}, {'hwnd': 2, 'pid': 22, 'title': '乙'}]
        self.profile = {'key_combination': 'q*3->ctrl+a*2', 'execution_mode': 'background',
                        'delay_between_keys': 0, 'loop_interval': 1}

    def worker(self, profile=None):
        return self.worker_class(self.windows, profile or self.profile)

    def test_background_chain_runs_on_both_windows_without_activation(self):
        worker = self.worker()
        hosts = [Mock(), Mock()]
        self.ns['AutomationHost'].side_effect = hosts
        worker._wait = Mock(side_effect=lambda seconds: worker.stop() if seconds == 1 else False)
        worker.run()
        for host, window in zip(hosts, self.windows):
            host.register_window.assert_called_once_with(window)
            self.assertEqual(host._keyboard_press.call_count, 3)
            self.assertEqual(host._keyboard_hotkey.call_count, 2)
            host._activate_bound_window.assert_not_called()
        self.ns['GLOBAL_FOREGROUND_INPUT'].run.assert_not_called()

    def test_foreground_inputs_are_serial_and_waits_do_not_hold_lock(self):
        worker = self.worker({**self.profile, 'execution_mode': 'foreground'})
        hosts = [Mock(), Mock()]
        self.ns['AutomationHost'].side_effect = hosts
        worker._wait = Mock(side_effect=lambda seconds: worker.stop() if seconds == 1 else False)
        worker.run()
        self.assertEqual(self.ns['GLOBAL_FOREGROUND_INPUT'].run.call_count, 10)
        for host in hosts:
            self.assertEqual(host._activate_bound_window.call_count, 5)
            self.assertEqual(host.keyboard.press.call_count, 3)
            self.assertEqual(host.keyboard.press_combination.call_count, 2)
            self.assertEqual(host._validate_bound_window_foreground.call_count, 5)

    def test_stop_inside_repeat_skips_remaining_chain_and_second_window(self):
        worker = self.worker()
        hosts = [Mock(), Mock()]
        hosts[0]._keyboard_press.side_effect = lambda params: worker.stop()
        self.ns['AutomationHost'].side_effect = hosts
        worker.run()
        hosts[0]._keyboard_press.assert_called_once()
        hosts[0]._keyboard_hotkey.assert_not_called()
        hosts[1]._keyboard_press.assert_not_called()

    def test_stop_before_thread_start_is_not_reset(self):
        worker = self.worker()
        worker.stop()
        worker.run()
        self.ns['AutomationHost'].assert_not_called()

    def test_stop_interrupts_long_wait_immediately(self):
        worker = self.worker()
        worker.stop()
        self.assertTrue(worker._wait(300))

    def test_closed_or_reused_window_is_skipped_but_other_window_runs(self):
        worker = self.worker()
        hosts = [Mock(), Mock()]
        hosts[0]._validate_bound_window_identity.side_effect = RuntimeError('PID 已变化')
        self.ns['AutomationHost'].side_effect = hosts
        worker._wait = Mock(side_effect=lambda seconds: worker.stop() if seconds == 1 else False)
        worker.run()
        hosts[0]._keyboard_press.assert_not_called()
        self.assertEqual(hosts[1]._keyboard_press.call_count, 3)
        worker.error_occurred.emit.assert_called_once()

    def test_failed_activation_does_not_send_foreground_input(self):
        worker = self.worker({**self.profile, 'execution_mode': 'foreground'})
        host = Mock()
        host._activate_bound_window.return_value = False
        with self.assertRaises(RuntimeError):
            worker._execute_window(host)
        host.keyboard.press.assert_not_called()

    def test_combo_failure_releases_own_keys_before_propagating(self):
        worker = self.worker({**self.profile, 'key_combination': 'ctrl+a', 'execution_mode': 'foreground'})
        host = Mock()
        host.keyboard.press_combination.side_effect = RuntimeError('输入失败')
        with self.assertRaises(RuntimeError):
            worker._execute_window(host)
        self.assertEqual([call.args[0] for call in host.keyboard.release_key.call_args_list], ['a', 'ctrl'])

    def test_mouse_uses_same_relative_client_point_for_both_windows(self):
        worker = self.worker({'action_mode': 'mouse', 'execution_mode': 'background',
                              'mouse_x': 100, 'mouse_y': 200, 'mouse_clicks': 2,
                              'mouse_interval': 0.1, 'loop_interval': 1})
        hosts = [Mock(), Mock()]
        self.ns['AutomationHost'].side_effect = hosts
        worker._wait = Mock(side_effect=lambda seconds: worker.stop() if seconds == 1 else False)
        worker.run()
        for host in hosts:
            self.assertEqual(host._mouse_click.call_count, 2)
            params = host._mouse_click.call_args.args[0]
            self.assertEqual((params['x'], params['y'], params['coordinate_space']), (100, 200, 'client'))

    def test_stop_after_first_click_prevents_remaining_clicks(self):
        worker = self.worker({'action_mode': 'mouse', 'execution_mode': 'background', 'mouse_clicks': 99})
        host = Mock()
        host._mouse_click.side_effect = lambda params: worker.stop()
        worker._execute_window(host)
        host._mouse_click.assert_called_once()

    def test_worker_has_private_copies_of_windows_and_profile(self):
        worker = self.worker()
        self.windows[0]['pid'] = 99
        self.profile['key_combination'] = 'delete'
        self.assertEqual(worker.windows[0]['pid'], 11)
        self.assertEqual(worker.profile['key_combination'], 'q*3->ctrl+a*2')


class MultiWindowFeatureTests(unittest.TestCase):
    def test_add_windows_deduplicates_handles_and_discards_window_objects(self):
        add, _ = load_feature_method('_add_windows')
        feature = Mock()
        feature.target_windows = [{'hwnd': 1, 'pid': 11, 'title': '甲'}]
        feature.saved_config = {}
        add(feature, [{'hwnd': 1, 'pid': 11, 'title': '甲'},
                      {'hwnd': 2, 'pid': 22, 'title': '乙', 'window': object()}])
        self.assertEqual([info['hwnd'] for info in feature.target_windows], [1, 2])
        self.assertNotIn('window', feature.target_windows[1])
        feature._refresh_windows.assert_called_once()

    def test_start_uses_all_valid_windows_in_one_worker(self):
        start, namespace = load_feature_method('start')
        feature = Mock()
        feature.is_running = False
        feature.worker = None
        feature.target_windows = [{'hwnd': 1}, {'hwnd': 2}, {'hwnd': 3}]
        profile = {'action_mode': 'key', 'execution_mode': 'background'}
        feature._capture_profile.return_value = profile
        namespace['win32gui'].IsWindow.side_effect = lambda hwnd: hwnd != 3
        start(feature)
        namespace['MultiWindowAutomationWorker'].assert_called_once_with([{'hwnd': 1}, {'hwnd': 2}], profile)
        self.assertTrue(feature.is_running)
        feature._set_editing_enabled.assert_called_once_with(False)
        feature.worker.start.assert_called_once()

    def test_start_rejects_empty_valid_window_list(self):
        start, namespace = load_feature_method('start')
        feature = Mock()
        feature.is_running = False
        feature.worker = None
        feature.target_windows = [{'hwnd': 1}]
        namespace['win32gui'].IsWindow.return_value = False
        start(feature)
        namespace['MultiWindowAutomationWorker'].assert_not_called()

    def test_stop_keeps_worker_and_controls_locked_while_input_returns(self):
        stop, _ = load_feature_method('stop')
        feature = Mock()
        feature.is_running = True
        original = feature.worker
        feature.worker.wait.return_value = False
        stop(feature)
        self.assertTrue(feature.is_running)
        self.assertIs(feature.worker, original)
        feature.worker.stop.assert_called_once()
        feature.start_btn.setEnabled.assert_called_once_with(False)
        feature._set_editing_enabled.assert_not_called()

    def test_late_finished_signal_from_old_worker_cannot_reset_new_run(self):
        finish, _ = load_feature_method('_worker_finished')
        feature = Mock()
        feature.is_running = True
        finish(feature, Mock())
        self.assertTrue(feature.is_running)
        feature._set_editing_enabled.assert_not_called()

    def test_finished_after_stop_reports_stopped_and_reenables_editing(self):
        finish, _ = load_feature_method('_worker_finished')
        feature = Mock()
        feature.is_running = True
        feature._stop_requested = True
        feature._worker_error = False
        finish(feature, feature.worker)
        self.assertFalse(feature.is_running)
        feature.status_label.setText.assert_called_once_with('状态: 已停止')
        feature._set_editing_enabled.assert_called_once_with(True)


if __name__ == '__main__':
    unittest.main()
