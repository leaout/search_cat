"""Read-only inspection of exits on the Jiangling mining corridor."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_platform.qqsg_data import QQSGPackage, parse_map_catalog
from plugin_platform.qqsg_portals import parse_portals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--ids', nargs='+', type=int, default=[55, 56, 57, 58, 130, 131, 906, 907, 908])
    args = parser.parse_args()
    package = QQSGPackage(args.package)
    catalog = {item['id']: item for item in parse_map_catalog(package.read('res/Txt/MapData.txt')).values()}
    maps = []
    for map_id in args.ids:
        item = catalog[map_id]
        terrain = 'map/' + item['resource'].rsplit('/', 1)[-1] + '.srv'
        maps.append({**item, 'terrain_entry': terrain,
                     'portals': parse_portals(package.read(terrain), map_id, catalog)})
    print(json.dumps({'source': str(args.package), 'maps': maps,
                      'caution': '出口字段为静态候选证据；未验证实景过图，不可直接执行移动。'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
