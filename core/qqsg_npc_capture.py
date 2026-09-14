"""Parse NPC names and coordinates from QQSG's in-game navigation panel."""
import re
from statistics import median


COORDINATE_RE = re.compile(r'[（(]\s*(\d{1,3})\s*[,，]\s*(\d{1,3})\s*[)）]')


def detect_navigation_map(rows: list[dict], map_catalog: dict) -> dict | None:
    """Match the selected navigation tab against names parsed from MapData.txt."""
    heading = ''.join(row.get('text', '') for row in rows[:4])
    compact = re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]', '', heading).casefold()
    matches = []
    for normalized, value in map_catalog.items():
        candidate = re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]', '', str(normalized)).casefold()
        if candidate and candidate in compact:
            matches.append((len(candidate), value))
    return max(matches, default=(0, None), key=lambda item: item[0])[1]


def _box_metrics(box) -> tuple[float, float, float]:
    xs = [float(point[0]) for point in box]
    ys = [float(point[1]) for point in box]
    return min(xs), (min(ys) + max(ys)) / 2, max(ys) - min(ys)


def group_ocr_lines(items: list) -> list[dict]:
    """Join horizontally split PaddleOCR boxes that belong to the same row."""
    parts = []
    for item in items or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        box, value = item[0], item[1]
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        text = str(value[0] if isinstance(value, (list, tuple)) else value).strip()
        confidence = float(value[1]) if isinstance(value, (list, tuple)) and len(value) > 1 else 1.0
        if not text:
            continue
        x, y, height = _box_metrics(box)
        parts.append({'x': x, 'y': y, 'height': height, 'text': text, 'confidence': confidence})
    if not parts:
        return []
    tolerance = max(7.0, median(part['height'] for part in parts) * 0.65)
    rows: list[list[dict]] = []
    for part in sorted(parts, key=lambda value: (value['y'], value['x'])):
        row = next((candidate for candidate in rows
                    if abs(sum(p['y'] for p in candidate) / len(candidate) - part['y']) <= tolerance), None)
        if row is None:
            rows.append([part])
        else:
            row.append(part)
    result = []
    for row in sorted(rows, key=lambda value: sum(p['y'] for p in value) / len(value)):
        row.sort(key=lambda value: value['x'])
        result.append({
            'text': ' '.join(part['text'] for part in row),
            'confidence': min(part['confidence'] for part in row),
            'y': sum(part['y'] for part in row) / len(row),
        })
    return result


def parse_npc_rows(items: list, map_name: str, map_id: int) -> tuple[list[dict], list[dict]]:
    """Return validated NPC records plus the grouped OCR rows used to derive them."""
    rows = group_ocr_lines(items)
    records = []
    seen = set()
    for row in rows:
        text = row['text'].replace('（', '(').replace('）', ')').replace('，', ',')
        match = COORDINATE_RE.search(text)
        if not match:
            continue
        x, y = int(match.group(1)), int(match.group(2))
        prefix = text[:match.start()].strip(' :-：|')
        prefix = re.sub(r'^.*?名称\s*[:：]?\s*', '', prefix)
        prefix = re.sub(r'坐标\s*[:：]?\s*$', '', prefix).strip(' :-：|')
        # Navigation rows contain a short NPC name immediately before the coordinate.
        name = re.sub(r'\s+', '', prefix)
        if not name or len(name) > 24 or any(character.isdigit() for character in name):
            continue
        key = (name, x, y)
        if key in seen:
            continue
        seen.add(key)
        records.append({
            'name': name, 'map': map_name, 'map_id': int(map_id), 'x': x, 'y': y,
            'confidence': round(float(row['confidence']), 4),
        })
    return records, rows
