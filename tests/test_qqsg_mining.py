import importlib.util
import unittest
from pathlib import Path


PLUGIN_MAIN = Path(__file__).resolve().parents[1] / 'plugins' / 'com.searchcat.qqsg.mining' / 'main.py'
SPEC = importlib.util.spec_from_file_location('qqsg_mining_main', PLUGIN_MAIN)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class QQSGMiningTests(unittest.TestCase):
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

    def test_line_switch_grid_fallback_recovers_even_column(self):
        items = [
            {'text': '13线（繁忙）', 'center': [80, 340], '_frame_width': 313},
            {'text': '15线（繁忙）', 'center': [80, 374], '_frame_width': 313},
        ]
        target = MODULE._find_target_line(items, 14)
        self.assertTrue(target['_grid_fallback'])
        self.assertEqual(target['center'], [207, 340])

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
