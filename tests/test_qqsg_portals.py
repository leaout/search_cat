import struct
import unittest

from plugin_platform.qqsg_portals import parse_portals


def sample(label='至 黄石矿洞一层', target=906, x=2160):
    header = [196608, 104, 240, 180, 10, 10] + [0] * 20
    header[12:14] = [104, 64]
    text = label.encode('gb18030')
    return struct.pack('<26I', *header) + struct.pack('<8I', 11, x, 1527, 81, 65, 1985, target, 0) + text.ljust(32, b'\0')


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {906: {'id': 906, 'name': '黄石矿洞一层'},
                        908: {'id': 908, 'name': '黄石矿洞三层'},
                        57: {'id': 57, 'name': '江陵东郊'}}

    def test_consistent_but_not_movement_verified(self):
        row = parse_portals(sample(), 131, self.catalog)[0]
        self.assertEqual(row['evidence'], 'consistent')
        self.assertEqual(row['position_raw'], [2160, 1527])
        self.assertFalse(row['movement_verified'])

    def test_actual_mine_conflict_is_retained(self):
        row = parse_portals(sample(target=908), 131, self.catalog)[0]
        self.assertEqual(row['evidence'], 'label_id_conflict')
        self.assertEqual(row['target_id_candidate'], 908)
        self.assertEqual(row['label_target_ids'], [906])

    def test_gate_and_floor_label_alias(self):
        for label, target in [('至 江陵 东门', 57), ('至 黄石矿洞第三层', 908)]:
            self.assertEqual(parse_portals(sample(label, target), 55, self.catalog)[0]['evidence'], 'consistent')

    def test_unknown_target(self):
        self.assertEqual(parse_portals(sample(target=9999), 55, self.catalog)[0]['evidence'], 'unknown_target')

    def test_invalid_bounds_and_label(self):
        for data in [sample(x=3000), sample(label='普通文本')]:
            self.assertEqual(parse_portals(data, 55, self.catalog)[0]['evidence'], 'invalid')

    def test_ambiguous_label(self):
        self.catalog[999] = {'id': 999, 'name': '黄石矿洞一层'}
        self.assertEqual(parse_portals(sample(), 55, self.catalog)[0]['evidence'], 'ambiguous_label')

    def test_reject_malformed_sections_and_version(self):
        data = sample()
        for changed in [b'', data[:150], struct.pack('<I', 0) + data[4:]]:
            with self.assertRaises(ValueError):
                parse_portals(changed, 55, self.catalog)
        header = list(struct.unpack_from('<26I', data))
        header[13] = 63
        with self.assertRaises(ValueError):
            parse_portals(struct.pack('<26I', *header) + data[104:], 55, self.catalog)


if __name__ == '__main__':
    unittest.main()
