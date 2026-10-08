"""Locate missing QQSG line labels using observed panel geometry."""

import re
from math import isfinite
from statistics import median


def _split_selector_rows(items: list[dict]) -> list[dict]:
    """Recover two labels when OCR groups a complete selector row into one box."""
    result = list(items)
    for item in items:
        text = re.sub(r'\s+', '', str(item.get('text', '')))
        matches = list(re.finditer(r'(\d{1,2})线(?!\d)', text))
        if len(matches) != 2 or matches[0].start() != 0 or '当前所在' in text:
            continue
        left, right = (int(match[1]) for match in matches)
        if left % 2 != 1 or right != left + 1 or not 1 <= left < right <= 16:
            continue
        box = item.get('box')
        if not isinstance(box, (list, tuple)) or len(box) < 4:
            continue
        try:
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
        except (TypeError, ValueError, IndexError):
            continue
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        # A real two-column row is much wider than a single label. Never
        # split chat sentences or boxes covering several vertical rows.
        if not 140 <= width <= 320 or not 8 <= height <= 40:
            continue
        for number, fraction in ((left, 0.25), (right, 0.75)):
            result.append({'text': f'{number}线',
                           'center': [round(min(xs) + width * fraction), round(median(ys))],
                           '_split_row': True})
    return result


def find_line_target(items: list[dict], target: int, center_of) -> dict | None:
    """Validate a recognized target against the other selector rows before clicking."""
    number = str(int(target))
    pattern = re.compile(rf'^{number}(?:线|号线|线路)(?!\d)')
    candidates = []
    for item in items:
        text = re.sub(r'\s+', '', str(item.get('text', '')))
        if '当前所在' in text or len(re.findall(r'\d{1,2}线', text)) > 1 or center_of(item) is None:
            continue
        if pattern.search(text) or text == f'线路{number}':
            candidates.append(item)
    candidate_ids = {id(item) for item in candidates}
    grid = infer_line_grid([item for item in items if id(item) not in candidate_ids], target, center_of)
    if grid is not None:
        pitch = grid['_grid_pitch']
        expected = grid['center']
        aligned = [item for item in candidates
                   if abs(center_of(item)[0] - expected[0]) <= pitch * 0.6
                   and abs(center_of(item)[1] - expected[1]) <= pitch * 0.3]
        if aligned:
            return min(aligned, key=lambda item: len(str(item.get('text', ''))))
        return grid
    if candidates:
        return min(candidates, key=lambda item: len(str(item.get('text', ''))))
    return infer_line_grid(items, target, center_of)


def infer_server_menu_button(items: list[dict], center_of) -> dict | None:
    """Locate the server selector from neighboring system-menu rows."""
    menu_rows = {
        '返回登录窗口': -3, '重新选择角色': -2, '在线客服': -1,
        '数据隐私保护助手': 1, '战斗状态修复': 2, '退出游戏': 3,
    }
    anchors = []
    for item in items:
        label = re.sub(r'\s+', '', str(item.get('text', '')))
        center = center_of(item)
        if center is None:
            continue
        for menu_text, offset in menu_rows.items():
            if menu_text in label:
                anchors.append((offset, center))
                break
    if len({offset for offset, _ in anchors}) < 2:
        return None
    pitches = [(b[1][1] - a[1][1]) / (b[0] - a[0])
               for a in anchors for b in anchors if b[0] > a[0]]
    pitch = median(pitches)
    if not 20 <= pitch <= 55:
        return None
    x = median([point[0] for _, point in anchors])
    y = median([point[1] - offset * pitch for offset, point in anchors])
    if any(abs(point[0] - x) > 45 or abs(point[1] - (y + offset * pitch)) > 12
           for offset, point in anchors):
        return None
    return {'text': '服务器选线（菜单定位）', 'center': [round(x), round(y)], '_menu_fallback': True}


def _consensus_line_grid(anchors: list[tuple], target: int) -> dict | None:
    """Fit the dominant numbered panel, tolerating clipped text and OCR outliers.

    Row numbers constrain the vertical fit. Three distinct rows are required;
    unrelated chat/footers must agree with both a column and the numbered row
    to vote. Horizontal tolerance allows a label missing its status suffix.
    """
    models = []
    for first_number, first in anchors:
        first_row = (first_number - 1) // 2
        for second_number, second in anchors:
            second_row = (second_number - 1) // 2
            if second_row <= first_row:
                continue
            pitch = (second[1] - first[1]) / (second_row - first_row)
            if not 20 <= pitch <= 55:
                continue
            origin = first[1] - first_row * pitch
            vertical = [(n, p) for n, p in anchors
                        if abs(p[1] - origin - ((n - 1) // 2) * pitch) <= pitch * 0.22]
            if len({(n - 1) // 2 for n, _ in vertical}) < 3:
                continue
            columns = [[p[0] for n, p in vertical if (n - 1) % 2 == c] for c in (0, 1)]
            xs = [median(values) if values else None for values in columns]
            inferred = None in xs
            if inferred:
                known = 0 if xs[0] is not None else 1
                xs[1 - known] = xs[known] + (1 if known == 0 else -1) * pitch * 3.5
            if not 2.5 * pitch <= xs[1] - xs[0] <= 4.5 * pitch:
                continue
            inliers = [(n, p) for n, p in vertical
                       if abs(p[0] - xs[(n - 1) % 2]) <= pitch * 0.95]
            # With a wholly unseen column, keep the previous strict safety
            # rule: do not both discard contradictory rows and invent a column.
            if inferred and len(inliers) != len(anchors):
                continue
            numbers = {n for n, _ in inliers}
            rows = {(n - 1) // 2 for n in numbers}
            if len(rows) < 3 or len(numbers) < 3:
                continue
            # An observed second column must retain at least one supporter.
            if not inferred and {n % 2 for n in numbers} != {0, 1}:
                continue
            fitted_origin = median([p[1] - ((n - 1) // 2) * pitch for n, p in inliers])
            fitted_columns = [[p[0] for n, p in inliers if (n - 1) % 2 == c] for c in (0, 1)]
            for column, values in enumerate(fitted_columns):
                if values:
                    xs[column] = median(values)
            if inferred:
                known = 0 if fitted_columns[0] else 1
                xs[1 - known] = xs[known] + (1 if known == 0 else -1) * pitch * 3.5
            point = [round(xs[(target - 1) % 2]), round(fitted_origin + (target - 1) // 2 * pitch)]
            residual = median([abs(p[1] - fitted_origin - ((n - 1) // 2) * pitch)
                               for n, p in inliers])
            models.append((len(numbers), len(rows), residual, point, pitch, inferred))
    if not models:
        return None
    models.sort(key=lambda model: (-model[0], -model[1], model[2]))
    best = models[0]
    # Equally supported but spatially different panels are unsafe to guess.
    if any(model[:2] == best[:2] and
           (abs(model[3][0] - best[3][0]) > best[4] * 0.6 or
            abs(model[3][1] - best[3][1]) > best[4] * 0.3) for model in models[1:]):
        return None
    return {'text': f'{target}线（网格一致定位）', 'center': best[3],
            '_grid_fallback': True, '_consensus_grid': True,
            '_inferred_column': best[5], '_grid_pitch': best[4]}


def infer_line_grid(items: list[dict], target: int, center_of) -> dict | None:
    """Interpolate within a validated two-column, sixteen-line selector."""
    if not 1 <= target <= 16:
        return None
    anchors = []
    for item in _split_selector_rows(items):
        text = re.sub(r'\s+', '', str(item.get('text', '')))
        # Ignore the current-line footer, chat, and merged multi-column text.
        match = re.match(r'^(\d{1,2})线(?!\d)', text)
        point = center_of(item)
        if match and point and len(text) <= 28 and not re.search(r'\d{1,2}线', text[match.end():]) \
                and 1 <= int(match[1]) <= 16:
            try:
                if all(isfinite(float(value)) for value in point[:2]):
                    anchors.append((int(match[1]), point))
            except (TypeError, ValueError):
                continue
    consensus = _consensus_line_grid(anchors, target)
    if consensus is not None:
        return consensus
    # OCR can separate the footer's number from "当前所在", leaving a bare
    # duplicate label. Prefer the occurrence aligned with its paired column
    # and the other labels in the same column, not the footer below the grid.
    grouped = {}
    for number, point in anchors:
        grouped.setdefault(number, []).append(point)
    cleaned = []
    for number, points in grouped.items():
        if len(points) == 1:
            cleaned.append((number, points[0]))
            continue
        peers = [p[0] for n, p in anchors if n != number and n % 2 == number % 2]
        paired = grouped.get(number + 1 if number % 2 else number - 1, [])
        if not peers or not paired:
            # Ambiguous duplicates should not poison an otherwise valid grid.
            continue
        column_x = median(peers)
        point = min(points, key=lambda p: abs(p[0] - column_x)
                    + min(abs(p[1] - other[1]) for other in paired))
        cleaned.append((number, point))
    anchors = cleaned
    # The three neighboring labels provide stronger evidence than a global
    # fit when OCR has accidentally included numbers elsewhere in the game.
    # For 14: 13 is the same row, 15 is directly below it, and 16 gives the
    # right-column x coordinate. No frame-size assumption is involved.
    if target % 2 == 0 and target <= 14:
        left_above = [p for n, p in anchors if n == target - 1]
        left_below = [p for n, p in anchors if n == target + 1]
        right_below = [p for n, p in anchors if n == target + 2]
        for upper in left_above:
            for lower in left_below:
                pitch = lower[1] - upper[1]
                if not 20 <= pitch <= 55 or abs(lower[0] - upper[0]) > pitch * 0.8:
                    continue
                for right in right_below:
                    gap = right[0] - upper[0]
                    if 2.5 * pitch <= gap <= 4.5 * pitch and abs(right[1] - lower[1]) <= pitch * 0.3:
                        return {'text': f'{target}线（邻近线路定位）',
                                'center': [round(right[0]), round(upper[1])],
                                '_grid_fallback': True, '_nearby_fallback': True, '_grid_pitch': pitch}
                # If OCR missed the whole right column, use the measured row
                # pitch and the Build36 panel's 3.5-row column spacing. Both
                # neighboring left labels must agree before using this path.
                if not right_below and 24 <= pitch <= 38:
                    return {'text': f'{target}线（邻近左列定位）',
                            'center': [round(median([upper[0], lower[0]]) + pitch * 3.5), round(upper[1])],
                            '_grid_fallback': True, '_nearby_fallback': True,
                            '_inferred_column': True, '_grid_pitch': pitch}
    columns = [[p[0] for n, p in anchors if (n - 1) % 2 == c] for c in (0, 1)]
    rows = {}
    for n, p in anchors:
        rows.setdefault((n - 1) // 2, []).append(p[1])
    if len(rows) < 2:
        return None
    ys = {r: median(values) for r, values in rows.items()}
    pitches = [(ys[b] - ys[a]) / (b - a) for a in ys for b in ys if b > a]
    pitch = median(pitches)
    if pitch <= 0:
        return None
    inferred_column = not all(columns)
    if inferred_column:
        # Build36 panel in the supplied screenshots: column spacing is
        # about 105 px for a 30 px row pitch. Require three distinct rows
        # spanning the list before applying this panel-specific geometry.
        if len(rows) < 3 or max(rows) - min(rows) < 2:
            return None
        known = 0 if columns[0] else 1
        known_x = median(columns[known])
        gap = pitch * 3.5
        xs = [known_x - known * gap, known_x + (1 - known) * gap]
    else:
        xs = [median(values) for values in columns]
        gap = xs[1] - xs[0]
    if gap <= 0 or any(abs(p[0] - xs[(n - 1) % 2]) > pitch * 0.5 for n, p in anchors):
        return None
    if not gap * 0.12 <= pitch <= gap * 0.65:
        return None
    origin = median([y - r * pitch for r, y in ys.items()])
    if any(abs(p[1] - (origin + ((n - 1) // 2) * pitch)) > pitch * 0.22 for n, p in anchors):
        return None
    row = (target - 1) // 2
    # The selector always has eight rows. Once multiple rows validate its
    # spacing, missing labels above/below them can also be located.
    if not 20 <= pitch <= 55:
        return None
    return {'text': f'{target}线（网格定位）',
            'center': [round(xs[(target - 1) % 2]), round(origin + row * pitch)],
            '_grid_fallback': True, '_inferred_column': inferred_column, '_grid_pitch': pitch}
