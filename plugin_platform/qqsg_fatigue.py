"""Locate the native-scale F1 panel and parse its gathering-fatigue tooltip."""

import math
import re


_STATUS_OFFSETS = {
    '角色信息': (69, 68), '角色抗性': (152, 70),
    '恶行': (173, 209), '声望': (173, 230),
}
_STATUS_ANCHOR_TOLERANCE = 8


def _status_item_center(item: dict) -> tuple[float, float] | None:
    """Read a finite, nonnegative OCR center without silently coercing junk."""
    center = item.get('center')
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        coordinates = center[:2]
    else:
        box = item.get('box')
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            return None
        if any(not isinstance(point, (list, tuple)) or len(point) < 2 for point in box):
            return None
        values = [value for point in box for value in point[:2]]
        if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
               for value in values):
            return None
        coordinates = (sum(point[0] for point in box) / 4, sum(point[1] for point in box) / 4)
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
           for value in coordinates):
        return None
    return float(coordinates[0]), float(coordinates[1])


def status_panel_anchor(items: list[dict]) -> tuple[int, int] | None:
    """Locate one F1 panel using two agreeing, native-pixel tab labels.

    Both tabs are mandatory. Duplicate OCR detections must agree with the same
    origin; optional stat labels, when detected, must also agree. Scaled,
    translated-offscreen, conflicting, and ambiguous layouts fail closed.
    """
    origins = []
    labels = set()
    for item in items:
        label = re.sub(r'\s+', '', str(item.get('text') or ''))
        if label not in _STATUS_OFFSETS:
            continue
        center = _status_item_center(item)
        if center is None:
            return None
        dx, dy = _STATUS_OFFSETS[label]
        origin = center[0] - dx, center[1] - dy
        if origin[0] < 0 or origin[1] < 0:
            return None
        origins.append(origin)
        labels.add(label)
    if not {'角色信息', '角色抗性'} <= labels:
        return None
    if any(max(origin[axis] for origin in origins) - min(origin[axis] for origin in origins)
           > _STATUS_ANCHOR_TOLERANCE for axis in (0, 1)):
        return None
    return tuple(round(sum(origin[axis] for origin in origins) / len(origins)) for axis in (0, 1))


def _valid_status_anchor(anchor: tuple[int, int]) -> bool:
    return (isinstance(anchor, (tuple, list)) and len(anchor) == 2
            and all(type(value) is int and value >= 0 for value in anchor))


def fatigue_hover_points(anchor: tuple[int, int]) -> list[tuple[int, int]]:
    """Return a small, bounded probe of the screenshot-calibrated fatigue icon."""
    if not _valid_status_anchor(anchor):
        return []
    return [(anchor[0] + dx, anchor[1] + 211) for dx in (295, 290, 300)]


def _clip_status_region(anchor: tuple[int, int], client_width: int, client_height: int,
                        relative: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    if (not _valid_status_anchor(anchor)
            or type(client_width) is not int or type(client_height) is not int
            or client_width <= 0 or client_height <= 0):
        return None
    dx, dy, width, height = relative
    left, top = max(0, anchor[0] + dx), max(0, anchor[1] + dy)
    right = min(client_width, anchor[0] + dx + width)
    bottom = min(client_height, anchor[1] + dy + height)
    if left >= right or top >= bottom:
        return None
    return left, top, right - left, bottom - top


def fatigue_tooltip_region(anchor: tuple[int, int], client_width: int,
                           client_height: int) -> tuple[int, int, int, int] | None:
    """Cover the icon and either-side tooltip, clipped to the bound client."""
    return _clip_status_region(anchor, client_width, client_height, (105, 111, 430, 190))


def status_tabs_region(anchor: tuple[int, int], client_width: int,
                       client_height: int) -> tuple[int, int, int, int] | None:
    """Limit a close-time verification capture to the two status tabs."""
    return _clip_status_region(anchor, client_width, client_height, (24, 47, 185, 44))


def parse_gathering_fatigue(items: list[dict]) -> tuple[int, int] | None:
    """Return a unique used/limit pair with an explicit gathering-fatigue label."""
    texts = [re.sub(r'\s+', '', str(item.get('text', ''))).replace('：', ':').replace('／', '/')
             for item in items]
    readings = set()
    for index, text in enumerate(texts):
        if not text.startswith('采集疲劳度'):
            continue
        candidate = text
        # The label and tiny counter may be split into separate OCR items.
        # Only adjacent numeric fragments may extend it, never life/durability labels.
        for fragment in texts[index + 1:index + 4]:
            if re.fullmatch(r'采集疲劳度:?(\d{1,6})/(\d{1,6})', candidate):
                break
            if re.fullmatch(r'[0-9/]+', fragment):
                candidate += fragment
            else:
                break
        match = re.fullmatch(r'采集疲劳度:?(\d{1,6})/(\d{1,6})', candidate)
        if match is None:
            return None
        used, limit = map(int, match.groups())
        if limit <= 0 or not 0 <= used <= limit:
            return None
        readings.add((used, limit))
    return next(iter(readings)) if len(readings) == 1 else None
