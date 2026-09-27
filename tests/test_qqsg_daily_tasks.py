import importlib.util
import unittest
from pathlib import Path


PLUGIN_MAIN = Path(__file__).resolve().parents[1] / 'plugins' / 'qqsg-daily-tasks' / 'main.py'
SPEC = importlib.util.spec_from_file_location('qqsg_daily_tasks_main', PLUGIN_MAIN)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class QQSGDailyTaskTests(unittest.TestCase):
    def test_single_task_mode_overrides_sequence(self):
        self.assertEqual(
            MODULE._resolve_task_sequence({
                'task_mode': 'single',
                'single_task': '灭鼠靖仓',
                'task_sequence': ['transport'],
            }),
            ['mie_shu_jing_cang'],
        )

    def test_sequence_mode_keeps_order_and_aliases(self):
        self.assertEqual(
            MODULE._resolve_task_sequence({
                'task_sequence': ['垓下学艺', 'transport'],
            }),
            ['gai_xia_xue_yi', 'transport'],
        )

    def test_single_task_requires_valid_selection(self):
        with self.assertRaises(ValueError):
            MODULE._resolve_task_sequence({'task_mode': 'single', 'single_task': ''})

    def test_reads_kill_progress(self):
        self.assertEqual(MODULE._read_progress('灭鼠靖仓：消灭地鼠 3/5'), (3, 5))
        self.assertEqual(MODULE._read_progress('任务尚未显示'), None)

    def test_completion_markers(self):
        self.assertTrue(MODULE._has_completion_marker('垓下学艺[已完成]'))
        self.assertFalse(MODULE._has_completion_marker('灭鼠靖仓 2/5'))


if __name__ == '__main__':
    unittest.main()
