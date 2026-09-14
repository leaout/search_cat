"""Read-only experimental SRV inspection; field meanings are hypotheses."""
import argparse
import json
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plugin_platform.qqsg_data import QQSGPackage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=Path)
    parser.add_argument('--map', default='15-1.map')
    parser.add_argument('--output', type=Path, default=Path('analysis/qqsg_map'))
    args = parser.parse_args()
    data = QQSGPackage(args.package).read('map/' + args.map + '.srv')
    header = struct.unpack_from('<26I', data)
    sections = list(zip(header[6:22:2], header[7:22:2]))
    for offset, size in sections:
        if offset + size > len(data):
            raise ValueError('Section exceeds file bounds')
    offset, size = sections[0]
    cells = list(struct.iter_unpack('<2I', data[offset:offset + size]))
    offset, size = sections[2]
    if size % 32:
        raise ValueError('Candidate geometry section not divisible by 32')
    records = list(struct.iter_unpack('<8I', data[offset:offset + size]))
    ids = {row[0]: row for row in records}
    refs = [(row, target) for row in records for target in (row[7] & 65535, row[7] >> 16) if target]
    def endpoints(row):
        return {tuple(row[3:5]), tuple(row[5:7])}
    connectivity = {
        'references': len(refs),
        'resolved': sum(target in ids for row, target in refs),
        'shared_endpoint': sum(bool(endpoints(row) & endpoints(ids[target])) for row, target in refs if target in ids),
        'reciprocal': sum(row[0] in (ids[target][7] & 65535, ids[target][7] >> 16) for row, target in refs if target in ids),
    }
    report = {
        'source': str(args.package), 'map': args.map, 'srv_bytes': len(data),
        'header': header, 'sections': sections, 'candidate_grid_dimensions': header[2:4],
        'candidate_cell_size': header[4:6], 'cell_records': len(cells),
        'candidate_geometry_count': len(records),
        'candidate_geometry_types': dict(Counter(row[1] for row in records)),
        'geometry_raw_records': records,
        'candidate_link_validation': connectivity,
        'caution': 'Geometry endpoints inferred as fields 3..6. Types, links and collision semantics unverified.',
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    width, height = header[2] * header[4], header[3] * header[5]
    colors = {2: '#1565c0', 4: '#e65100', 8: '#2e7d32'}
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-50 -50 {width+100} {height+100}">',
           f'<rect x="-50" y="-50" width="{width+100}" height="{height+100}" fill="white"/>']
    for row in records:
        ident, kind, _, x1, y1, x2, y2, links = row
        color = colors.get(kind, '#8e24aa')
        svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="5"/>')
        svg.append(f'<text x="{x1}" y="{y1-8}" font-size="22">{ident}:t{kind}</text>')
    svg.append('</svg>')
    (args.output / 'candidate_geometry.svg').write_text('\n'.join(svg), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'geometry_raw_records'}, indent=2))


if __name__ == '__main__':
    main()
