"""Read candidate map exits without treating unverified fields as movement instructions."""

import struct

from plugin_platform.qqsg_data import normalize_map_name


def _label_name(value: str) -> str:
    name = normalize_map_name(value).removeprefix('至').replace('第', '').replace('.', '')
    return name.replace('东门', '东郊').replace('西门', '西郊')


def parse_portals(payload: bytes, source_id: int, catalog: dict[int, dict]) -> list[dict]:
    """Decode the observed 64-byte exit section, retaining conflicting evidence.

    Position fields are raw terrain units, not client pixels or verified minimap
    coordinates. The seventh integer is a candidate destination ID; labels are
    checked independently so stale or conditional destinations cannot be hidden.
    """
    if len(payload) < 104:
        raise ValueError('SRV 文件头不完整')
    header = struct.unpack_from('<26I', payload)
    if header[0:2] != (196608, 104):
        raise ValueError('不支持的 SRV 出口格式')
    offset, length = header[12:14]
    if offset < 104 or offset + length > len(payload) or length % 64:
        raise ValueError('SRV 出口段越界或记录长度异常')
    width, height = header[2] * header[4], header[3] * header[5]
    if not 0 < width <= 100000 or not 0 < height <= 100000:
        raise ValueError('SRV 地图尺寸异常')
    result = []
    for cursor in range(offset, offset + length, 64):
        fields = struct.unpack_from('<8I', payload, cursor)
        label = payload[cursor + 32:cursor + 64].split(b'\0', 1)[0].decode('gb18030', errors='strict')
        target_id = fields[6]
        target = catalog.get(target_id)
        matches = [item['id'] for item in catalog.values() if _label_name(item['name']) == _label_name(label)]
        within_bounds = fields[1] <= width and fields[2] <= height
        if not label.strip().startswith('至') or not within_bounds:
            evidence = 'invalid'
        elif target is None:
            evidence = 'unknown_target'
        elif target_id not in matches:
            evidence = 'label_id_conflict'
        elif len(matches) != 1:
            evidence = 'ambiguous_label'
        else:
            evidence = 'consistent'
        result.append({
            'source_id': source_id, 'record_id': fields[0],
            'position_raw': list(fields[1:3]), 'size_raw': list(fields[3:5]),
            'unknown_field_5': fields[5], 'target_id_candidate': target_id,
            'target_name_candidate': target['name'] if target else None,
            'unknown_field_7': fields[7], 'label': label,
            'label_target_ids': matches, 'evidence': evidence,
            'movement_verified': False,
        })
    return result
