import unittest

from core.text import repair_utf8_gbk_mojibake


class WindowsTextTests(unittest.TestCase):
    def test_repairs_game_title_with_surrogateescaped_gbk_bytes(self):
        original = 'QQ三国1.0Beta83Build32 抚琴退敌 7线'
        mojibake = original.encode('utf-8').decode('gbk', errors='surrogateescape')

        self.assertEqual(repair_utf8_gbk_mojibake(mojibake), original)

    def test_preserves_normal_chinese_and_ascii(self):
        self.assertEqual(repair_utf8_gbk_mojibake('QQ三国'), 'QQ三国')
        self.assertEqual(repair_utf8_gbk_mojibake('Search Cat 1.0'), 'Search Cat 1.0')


if __name__ == '__main__':
    unittest.main()
