import importlib.util
import unittest
from pathlib import Path


PLUGIN_MAIN = Path(__file__).resolve().parents[1] / 'plugins' / 'qqsg-alt-leveling' / 'main.py'
SPEC = importlib.util.spec_from_file_location('qqsg_alt_leveling_main', PLUGIN_MAIN)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class QQSGAltLevelingTests(unittest.TestCase):
    def test_stage_boundaries(self):
        self.assertEqual(MODULE._stage_for_level(1)['id'], 'level_1_10')
        self.assertEqual(MODULE._stage_for_level(10)['id'], 'level_1_10')
        self.assertEqual(MODULE._stage_for_level(11)['id'], 'level_11_20')
        self.assertEqual(MODULE._stage_for_level(50)['id'], 'level_41_50')

    def test_extracts_level_from_ocr_text(self):
        self.assertEqual(MODULE._extract_level(['LV 12']), 12)
        self.assertEqual(MODULE._extract_level(['等级：7']), 7)
        self.assertIsNone(MODULE._extract_level(['当前经验 12/50']))

    def test_task_signature_and_completion(self):
        lines = [{'text': 'NPC：刘备'}, {'text': '主线任务[已完成]'}]
        self.assertEqual(MODULE._task_signature(lines), 'NPC：刘备|主线任务[已完成]')
        self.assertTrue(MODULE._has_completion_marker('主线任务[已完成]'))

    def test_reads_task_progress(self):
        self.assertEqual(MODULE._read_progress('消灭益州兵 3/10'), (3, 10))
        self.assertIsNone(MODULE._read_progress('任务已接取'))


if __name__ == '__main__':
    unittest.main()
