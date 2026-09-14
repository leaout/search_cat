import unittest

from core.qqsg_npc_capture import detect_navigation_map, group_ocr_lines, parse_npc_rows


def item(text, x, y, width=60, height=18, confidence=0.96):
    return [
        [[x, y], [x + width, y], [x + width, y + height], [x, y + height]],
        [text, confidence],
    ]


class QQSGNpcCaptureTests(unittest.TestCase):
    def test_detects_selected_map_from_navigation_heading(self):
        rows = [{'text': '成都·子城 蜀国城市'}, {'text': '名称 坐标'}]
        catalog = {
            '成都子城': {'name': '成都.子城', 'id': 23},
            '成都': {'name': '成都', 'id': 24},
        }
        self.assertEqual(detect_navigation_map(rows, catalog), {'name': '成都.子城', 'id': 23})

    def test_joins_name_and_coordinate_boxes_on_same_row(self):
        source = [item('黄月英', 10, 20), item('(34, 9)', 150, 21)]
        rows = group_ocr_lines(source)
        self.assertEqual(rows[0]['text'], '黄月英 (34, 9)')

    def test_parses_navigation_rows_and_ignores_player_coordinate(self):
        source = [
            item('成都·子城', 10, 0),
            item('黄月英', 10, 30), item('（34，9）', 150, 31),
            item('刘备', 10, 60), item('(20, 4)', 150, 60),
            item('坐标：28 16', 10, 100),
        ]
        records, _rows = parse_npc_rows(source, '成都.子城', 23)
        self.assertEqual(records, [
            {'name': '黄月英', 'map': '成都.子城', 'map_id': 23, 'x': 34, 'y': 9, 'confidence': 0.96},
            {'name': '刘备', 'map': '成都.子城', 'map_id': 23, 'x': 20, 'y': 4, 'confidence': 0.96},
        ])


if __name__ == '__main__':
    unittest.main()
