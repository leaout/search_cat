"""Batch cancellation integration checks using actual Qt worker threads."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    from PyQt5.QtCore import QCoreApplication
    from feature.script_platform_feature import BatchLineSwitchWorker, ScriptPlatformFeature
except ModuleNotFoundError:
    QCoreApplication = None


@unittest.skipIf(QCoreApplication is None, 'Windows GUI dependencies unavailable')
class BatchLineSwitchQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_cancelled_thread_keeps_stop_state_for_completion_log(self):
        worker = BatchLineSwitchWorker(Mock(), [{'hwnd': 1}, {'hwnd': 2}], 14, False)
        host = Mock()
        original_dispatch = host.dispatch

        def recognize(method, params):
            worker.requestInterruption()
            return []

        original_dispatch.side_effect = recognize
        worker._window_state = Mock(return_value=(7, 'QQ三国 7线'))

        def switch_once(current_host, info):
            current_host.dispatch('ocr.recognize', {})
            current_host.dispatch('mouse.click', {'x': 10, 'y': 10})

        worker._switch_one_once = Mock(side_effect=switch_once)
        results = []
        worker.finished_result.connect(lambda success, failed: results.append((success, failed)))
        with patch('feature.script_platform_feature.AutomationHost', return_value=host):
            worker.start()
            finished = worker.wait(3000)
            if not finished:
                worker.requestInterruption()
                worker.wait(3000)
            self.assertTrue(finished, 'Cancelled worker did not finish')
        self.app.processEvents()
        self.assertEqual(results, [(0, 0)])
        self.assertTrue(worker.isInterruptionRequested())
        worker._switch_one_once.assert_called_once()
        self.assertEqual([call.args[0] for call in original_dispatch.call_args_list], ['ocr.recognize'])
        host.release_all_keys.assert_called_once()
        ui = SimpleNamespace(switch_line_worker=worker, switching_lines=True, _log=Mock(), _sync_running_ui=Mock())
        ScriptPlatformFeature._on_batch_line_switch_finished(ui, 0, 0)
        self.assertIn('已停止', ui._log.call_args.args[0])
        self.assertFalse(ui.switching_lines)
        self.assertIsNone(ui.switch_line_worker)


if __name__ == '__main__':
    unittest.main()
