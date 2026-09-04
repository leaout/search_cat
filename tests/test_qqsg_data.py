import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from plugin_platform.qqsg_data import MAP_DATA_PATH, QQSGPackage, build_routes, parse_map_data


def write_package(path: Path, name: str, payload: bytes):
    compressed = zlib.compress(payload)
    encoded_name = name.encode('gb18030')
    data_offset = 16
    table_offset = data_offset + len(compressed)
    table = struct.pack('<H', len(encoded_name)) + encoded_name
    table += struct.pack('<4I', 0, data_offset, len(payload), len(compressed))
    header = struct.pack('<4I', 100, 1, table_offset, len(table))
    path.write_bytes(header + compressed + table)


class QQSGPackageTests(unittest.TestCase):
    def test_reads_compressed_map_data_from_package_index(self):
        payload = '2\n23 maps\\23 成都.子城 0 0\n3 maps\\3 巴郡 0 0\n'.encode('gb18030')
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_path = Path(temporary_directory) / 'objects.pkg'
            write_package(package_path, MAP_DATA_PATH, payload)
            result = QQSGPackage(package_path).read(MAP_DATA_PATH)

        self.assertEqual(result, payload)
        self.assertEqual(parse_map_data(result)['成都.子城'], 23)

    def test_route_join_normalizes_middle_dot_and_reports_conflicts(self):
        maps = {'成都.子城': 23, '巴郡': 3}
        locations = [
            {'name': '奋威中郎将', 'map': '成都·子城', 'x': 11, 'y': 7},
            {'name': '驿站马夫', 'map': '成都·子城', 'x': 12, 'y': 15},
            {'name': '驿站马夫', 'map': '巴郡', 'x': 8, 'y': 5},
            {'name': '未知', 'map': '不存在', 'x': 1, 'y': 2},
        ]

        routes, report = build_routes(maps, locations)

        self.assertEqual(routes['奋威中郎将'], [23, 11, 7])
        self.assertNotIn('驿站马夫', routes)
        self.assertIn('驿站马夫', report['conflicts'])
        self.assertEqual(report['unmatched'], ['未知@不存在'])

    def test_location_asset_is_valid_json(self):
        path = (
            Path(__file__).resolve().parent.parent
            / 'plugins' / 'com.searchcat.qqsg.official_task' / 'assets' / 'data' / 'npc_locations.json'
        )
        value = json.loads(path.read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(value), 30)


if __name__ == '__main__':
    unittest.main()
