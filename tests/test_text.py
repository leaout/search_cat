import unittest

from core.text import repair_utf8_gbk_mojibake
from core.window_titles import is_qqsg_game_window_title


class WindowsTextTests(unittest.TestCase):
    def test_repairs_game_title_with_surrogateescaped_gbk_bytes(self):
        original = 'QQ三国1.0Beta83Build32 抚琴退敌 7线'
        mojibake = original.encode('utf-8').decode('gbk', errors='surrogateescape')

        self.assertEqual(repair_utf8_gbk_mojibake(mojibake), original)

    def test_preserves_normal_chinese_and_ascii(self):
        self.assertEqual(repair_utf8_gbk_mojibake('QQ三国'), 'QQ三国')
        self.assertEqual(repair_utf8_gbk_mojibake('Search Cat 1.0'), 'Search Cat 1.0')

    def test_recognizes_real_qqsg_client_title(self):
        title = 'QQ三国1.0Beta83Build32 抚琴退敌 7线'
        self.assertTrue(is_qqsg_game_window_title(title))

    def test_recognizes_mojibake_qqsg_client_title(self):
        title = 'QQ三国1.0Beta83Build32 抚琴退敌 7线'
        mojibake = title.encode('utf-8').decode('gbk', errors='surrogateescape')
        self.assertTrue(is_qqsg_game_window_title(mojibake))

    def test_rejects_pages_and_tools_that_only_mention_qqsg(self):
        self.assertFalse(is_qqsg_game_window_title('QQ三国答题 - Google Chrome'))
        self.assertFalse(is_qqsg_game_window_title('QQ三国官爵任务调试器'))
        self.assertFalse(is_qqsg_game_window_title(''))


if __name__ == '__main__':
    unittest.main()
