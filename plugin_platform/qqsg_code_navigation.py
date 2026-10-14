"""QQSG's text-link navigation protocol and native-scale social-panel anchors."""

import re
import time

from plugin_platform.qqsg_data import normalize_map_name


LINK_LABEL = '123456'
SOCIAL_TABS = {'好友': 0, '队伍': 43, '军团': 85, '师徒': 127,
               '结拜': 169, '情侣': 212, '敌对': 254, '黑名单': 298}
MINING_MAPS = {55: '江陵', 57: '江陵东郊', 131: '荆山之南',
               906: '黄石矿洞一层', 907: '黄石矿洞二层', 908: '黄石矿洞三层'}


def navigation_code(map_id: int, x: int, y: int) -> str:
    """Generate only a coordinate hyperlink, never arbitrary UI commands.

    X/Y are raw terrain units. Minimap (13,16) corresponds to (1300,1600).
    Already-raw portal coordinates must NOT be multiplied by 100 again.
    """
    if type(map_id) is not int or not 1 <= map_id <= 65535:
        raise ValueError('寻路地图 ID 必须是 1..65535 的整数')
    if any(type(value) is not int or not 0 <= value <= 100000 for value in (x, y)):
        raise ValueError('寻路原始坐标必须是 0..100000 的整数')
    return f'/<DnpcWalkEx={map_id}|{x}|{y}>/{LINK_LABEL}</C04>'


def _text(item: dict) -> str:
    return re.sub(r'\s+', '', str(item.get('text', ''))).replace('：', ':')


def _center(item: dict) -> tuple[int, int] | None:
    point = item.get('center')
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        return None
    if any(type(value) not in (int, float) or not 0 <= value <= 100000 for value in point):
        return None
    return round(point[0]), round(point[1])


def social_anchor(items: list[dict]) -> tuple[int, int] | None:
    """Locate one native-scale tab row, ignoring unrelated labels elsewhere.

    A missing friend/guild tab is common in full-frame OCR. Use all eight tabs
    but require at least two different labels agreeing on a translation. A
    second coherent row, or duplicate label inside our row, is ambiguous.
    """
    candidates = []
    for item in items:
        label, point = _text(item), _center(item)
        if label in SOCIAL_TABS and point is not None:
            candidates.append((label, (point[0] - SOCIAL_TABS[label], point[1])))
    groups = set()
    for _, origin in candidates:
        group = tuple(index for index, (_, point) in enumerate(candidates)
                      if all(abs(a - b) <= 8 for a, b in zip(origin, point)))
        if len({candidates[index][0] for index in group}) >= 2:
            groups.add(group)
    # All valid candidates must describe the same row. Do not choose a random
    # maximum when OCR supplies incompatible positions or two social panels.
    if len(groups) != 1:
        return None
    group = next(iter(groups))
    labels = [candidates[index][0] for index in group]
    if len(labels) != len(set(labels)):
        return None
    origins = [candidates[index][1] for index in group]
    return tuple(round(sum(origin[k] for origin in origins) / len(origins)) for k in (0, 1))


def input_anchor(items: list[dict]) -> tuple[int, int] | None:
    matches = [_center(item) for item in items if _text(item).rstrip(':') == '请输入添加好友的名称']
    return matches[0] if len(matches) == 1 else None


def link_point(items: list[dict], prompt: tuple[int, int]) -> tuple[int, int] | None:
    points = [_center(item) for item in items if _text(item) == LINK_LABEL]
    points = [point for point in points if point and abs(point[0] - prompt[0]) <= 105
              and 10 <= point[1] - prompt[1] <= 55]
    return points[0] if len(points) == 1 else None


def minimap_state(items: list[dict], names: list[str], allow_bare: bool = False) -> dict | None:
    """Require a known map and an unambiguous coordinate pair in a small ROI."""
    text = ''.join(_text(item) for item in items).replace('．', '.').replace('·', '.')
    if allow_bare:
        # Only used for the isolated minimap label strip, never full-screen OCR.
        text = re.sub(r'\s+', '', text)
        matches = [name for name in names if text.startswith(normalize_map_name(name))
                   and re.fullmatch(r'[（(\[]?\d{1,3}[,，、:：]\d{1,3}[）)\]]?',
                                    text[len(normalize_map_name(name)):])]
        if len(matches) == 1:
            suffix = text[len(normalize_map_name(matches[0])):]
            numbers = re.findall(r'\d+', suffix)
            return {'map_name': matches[0], 'position': [int(value) for value in numbers]}
    known = [name for name in names if any(
        normalize_map_name(_text(item)) == normalize_map_name(name) for item in items
    ) or re.search(re.escape(normalize_map_name(name)) + r'(?=[（(\[]|$)', normalize_map_name(text))]
    # 江陵 is a substring of 江陵东郊; retain only the most specific match.
    known = [name for name in known if not any(name != other and name in other for other in known)]
    if len(known) != 1:
        return None
    pairs = set((int(x), int(y)) for x, y in re.findall(
        r'[（(\[]\s*(\d{1,3})\s*[,，、:：]\s*(\d{1,3})\s*[）)\]]', text))
    if len(pairs) != 1:
        return None
    return {'map_name': known[0], 'position': list(pairs.pop())}


def navigate_and_wait(context, map_id: int, x: int, y: int, map_name: str,
                      start_map: str = '', timeout: float = 120, interval: float = 0.7,
                      tolerance: float = 150) -> None:
    """Invoke native navigation once and require two fresh arrival observations.

    Saved records are diagnostics, not authorization to resume/reuse an arrival.
    No automatic direction/G presses, purchases, chat, or friend confirmation.
    """
    code = navigation_code(map_id, x, y)
    if not isinstance(map_name, str) or not map_name.strip():
        raise ValueError('代码寻路必须指定目标地图名称，用于到达校验')
    if not 1 <= timeout <= 600 or not 0.2 <= interval <= 10 or not 0 <= tolerance <= 300:
        raise ValueError('寻路检测参数超出允许范围')
    context.log(f'代码寻路：{map_name}，原始坐标 ({x},{y})，命令 {code}')
    if context.dry_run:
        context.log('模拟运行：不打开交流、不输入、不点击；未确认真实到达')
        return
    names = list(dict.fromkeys([*MINING_MAPS.values(), map_name, start_map]))
    names = [name for name in names if name]
    record = {'code': code, 'target': {'map_id': map_id, 'map_name': map_name, 'raw': [x, y]}}

    def checkpoint(state: str, observed=None, detail: str = '') -> None:
        context.storage.write_json('navigation/current.json', {
            **record, 'state': state, 'observed': observed,
            'detail': detail, 'updated_at': time.time(),
        })

    def arrived(observed) -> bool:
        if not isinstance(observed, dict) or normalize_map_name(str(observed.get('map_name', ''))) \
                != normalize_map_name(map_name):
            return False
        point = observed.get('position')
        return (isinstance(point, list) and len(point) == 2
                and all(type(value) is int and 0 <= value <= 999 for value in point)
                and abs(point[0] * 100 - x) <= tolerance
                and abs(point[1] * 100 - y) <= tolerance)

    try:
        observed = context.windows.read_navigation_state(names)
        if start_map and (not isinstance(observed, dict) or
                          normalize_map_name(str(observed.get('map_name', ''))) not in
                          {normalize_map_name(start_map), normalize_map_name(map_name)}):
            raise RuntimeError(f'未确认起点 {start_map} 或目标地图 {map_name}；拒绝生成链接')
        checkpoint('starting', observed)
        if arrived(observed):
            context.sleep(interval)
            verified = context.windows.read_navigation_state(names)
            if arrived(verified):
                checkpoint('arrived', verified)
                context.log('两次实时小地图检测确认已在目标附近，无需再次生成链接')
                return
        result = context.windows.navigate_by_code(map_id, x, y)
        if not isinstance(result, dict) or result.get('clicked') is not True \
                or result.get('ui_restored') is not True:
            reason = result.get('reason', '') if isinstance(result, dict) else '结果无效'
            raise RuntimeError(f'代码寻路未确认启动并关闭面板：{reason}')
        context.log('已点击生成的寻路链接；开始校验地图和坐标，不等同于已到达')
        deadline = time.monotonic() + timeout
        confirmations = 0
        for scan in range(180):
            if time.monotonic() >= deadline:
                break
            if not context.windows.is_alive():
                raise RuntimeError('代码寻路期间游戏窗口已关闭')
            observed = context.windows.read_navigation_state(names)
            confirmations = confirmations + 1 if arrived(observed) else 0
            checkpoint('moving' if observed else 'unknown', observed)
            if scan % 5 == 0 or confirmations:
                context.log(f'寻路检测：{observed or "小地图未识别，不能视为到达"}')
            if confirmations >= 2:
                checkpoint('arrived', observed)
                context.log(f'已确认到达 {map_name} 目标附近：{observed["position"]}')
                return
            context.sleep(interval)
        raise RuntimeError('代码寻路检测超时；不按 G、不猜测过图、不自动重复点击。请检查路径和等级限制')
    except (RuntimeError, ValueError) as error:
        checkpoint('failed', detail=str(error))
        raise
