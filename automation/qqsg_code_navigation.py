"""Bounded foreground transaction for coordinate links in the add-friend UI.

Never clicks the add-friend confirmation or sends a chat message. The host
dispatcher serializes this whole transaction across all plugin windows.
"""

import time

from automation.qqsg_status import _blocked_dialog, _focus, _scan
from plugin_platform.qqsg_code_navigation import (
    MINING_MAPS, SOCIAL_TABS, input_anchor, link_point, minimap_state, navigation_code, social_anchor,
)


def _point_in_client(point: tuple[int, int], width: int, height: int) -> None:
    if not (0 <= point[0] < width and 0 <= point[1] < height):
        raise ValueError('寻路界面相对坐标超出客户区；不支持当前布局')


def _click(host, point: tuple[int, int], width: int, height: int) -> None:
    _point_in_client(point, width, height)
    host._validate_bound_window_foreground()
    host._mouse_click({'x': point[0], 'y': point[1], 'button': 'left',
                       'mode': 'foreground', 'coordinate_space': 'client'})
    host._mouse_move({'x': 8, 'y': 8, 'mode': 'foreground', 'coordinate_space': 'client'})
    time.sleep(0.15)


def _read(host, region=None, variants=('none',)) -> tuple:
    scans, width, height = _scan(host, region, variants)
    # Do not combine two passes into duplicate anchor/link candidates.
    return scans, width, height


def _pick(scans: list, parser):
    found = [parser(items) for items in scans]
    found = [point for point in found if point is not None]
    if not found or any(abs(a - b) > 8 for point in found for a, b in zip(found[0], point)):
        return None
    return found[0]


def _same_anchor(first, second) -> bool:
    return first is not None and second is not None and all(abs(a - b) <= 8 for a, b in zip(first, second))


def start_code_navigation(host, params: dict) -> dict:
    code = navigation_code(params.get('map_id'), params.get('x'), params.get('y'))
    if host.dry_run:
        return {'clicked': False, 'ui_restored': True, 'dry_run': True, 'code': code}
    _focus(host)
    scans, width, height = _read(host)
    if any(_blocked_dialog(items) for items in scans):
        raise RuntimeError('存在道具使用或购买确认窗口，拒绝打开代码寻路界面')
    anchor = _pick(scans, social_anchor)
    prompt = _pick(scans, input_anchor)
    if not anchor and not prompt:
        host._validate_bound_window_foreground()
        host.keyboard.press('f4')
        time.sleep(0.2)
        scans, width, height = _read(host)
        anchor = _pick(scans, social_anchor)
        prompt = _pick(scans, input_anchor)
    if not prompt:
        if anchor is None:
            raise RuntimeError('F4 后未定位到交流页签；不执行固定屏幕点击')
        _click(host, anchor, width, height)  # 好友页
        # Re-read after switching tabs; panel may have moved or be obstructed.
        scans, width, height = _read(host)
        anchor = _pick(scans, social_anchor)
        if anchor is None:
            raise RuntimeError('无法重新确认交流面板位置')
        _click(host, (anchor[0] + 241, anchor[1] + 321), width, height)  # 添加
        scans, width, height = _read(host)
        prompt = _pick(scans, input_anchor)
    if prompt is None:
        raise RuntimeError('未定位到“请输入添加好友的名称”；不输入命令')
    if anchor is None or any(_blocked_dialog(items) for items in scans):
        raise RuntimeError('无法确认输入弹窗所属交流面板，或存在其他确认窗口；不输入命令')
    _click(host, (prompt[0], prompt[1] + 32), width, height)
    host._validate_bound_window_foreground()
    host.keyboard.press_combination('ctrl', 'a')
    host._keyboard_type_text({'text': code, 'mode': 'foreground'})
    time.sleep(0.2)
    region = (prompt[0] - 105, prompt[1] + 10, 210, 50)
    if region[0] < 0 or region[1] + region[3] > height or region[0] + region[2] > width:
        raise RuntimeError('输入框范围异常；不点击未知区域')
    scans, _, _ = _read(host, region, ('none', 'task_scale'))
    link = _pick(scans, lambda items: link_point(items, prompt))
    if link is None:
        raise RuntimeError('没有确认生成 123456 寻路链接；不点击确定、不添加好友')
    _click(host, link, width, height)
    # Cancel only our positively identified dialog, then close the social panel.
    scans, width, height = _read(host)
    current_prompt = _pick(scans, input_anchor)
    if current_prompt is None or not _same_anchor(prompt, current_prompt) \
            or any(_blocked_dialog(items) for items in scans):
        return {'clicked': True, 'ui_restored': False, 'code': code,
                'reason': '链接已点击，但未能重新确认自己的输入弹窗；需人工检查'}
    if current_prompt is not None:
        candidates = []
        for items in scans:
            for item in items:
                text = ''.join(str(item.get('text', '')).split())
                point = item.get('center')
                if text == '取消' and isinstance(point, (list, tuple)) and len(point) == 2 \
                        and abs(point[0] - current_prompt[0] - 53) <= 20 \
                        and abs(point[1] - current_prompt[1] - 82) <= 20:
                    candidates.append(tuple(round(value) for value in point))
        if not candidates:
            return {'clicked': True, 'ui_restored': False, 'code': code,
                    'reason': '已点击寻路链接，但未定位到输入弹窗取消按钮'}
        _click(host, candidates[0], width, height)
        scans, width, height = _read(host)
    if _pick(scans, input_anchor) is not None or any(_blocked_dialog(items) for items in scans):
        return {'clicked': True, 'ui_restored': False, 'code': code, 'reason': '输入弹窗未关闭或出现未知确认'}
    # An OCR miss after cancel is not proof that the parent panel closed.
    # Keep the previously verified position and validate it in a small crop.
    current_anchor = _pick(scans, social_anchor)
    if current_anchor is not None and not _same_anchor(anchor, current_anchor):
        return {'clicked': True, 'ui_restored': False, 'code': code, 'reason': '交流面板位置发生变化，需人工检查'}
    if anchor is not None:
        tabs_region = (anchor[0] - 25, anchor[1] - 14, 344, 28)
        if tabs_region[0] < 0 or tabs_region[1] < 0 \
                or tabs_region[0] + 344 > width or tabs_region[1] + 28 > height:
            return {'clicked': True, 'ui_restored': False, 'code': code, 'reason': '面板页签区域异常'}
        tab_scans, _, _, before = _scan(host, tabs_region, ('none', 'task_scale'), signature=True)
        if not _same_anchor(anchor, _pick(tab_scans, social_anchor)):
            return {'clicked': True, 'ui_restored': False, 'code': code, 'reason': '关闭前面板定位丢失'}
        _click(host, (anchor[0] + 346, anchor[1] - 39), width, height)
        tab_scans, _, _, after = _scan(host, tabs_region, ('none', 'task_scale'), signature=True)
        labels_remain = any(any(label in ''.join(str(item.get('text', '')).split()) for label in SOCIAL_TABS)
                            for items in tab_scans for item in items)
        changed = bool(before) and len(before) == len(after) and (
            sum(abs(a - b) > 25 for a, b in zip(before, after)) / len(before) > 0.20)
        if labels_remain or not changed:
            return {'clicked': True, 'ui_restored': False, 'code': code, 'reason': '未能确认交流面板已关闭'}
    return {'clicked': True, 'ui_restored': True, 'code': code}


def read_navigation_state(host, names=None) -> dict | None:
    """Read a fresh known map/coordinate pair; release every temporary frame."""
    if names is None:
        names = list(MINING_MAPS.values())
    if not isinstance(names, list) or not 1 <= len(names) <= 100 \
            or any(not isinstance(name, str) or not 1 <= len(name) <= 40 for name in names):
        raise ValueError('地图名列表格式无效')
    if host.dry_run:
        return None
    _focus(host)
    # Capture dimensions once without full-window OCR, then only OCR the minimap.
    frame = host._capture_window({'area': 'client', 'mode': 'foreground'}, temporary=True)
    try:
        width, height = frame['width'], frame['height']
    finally:
        host.frames.pop(frame['id'], None)
    region = (max(0, width - 290), 0, min(width, 290), min(height, 185))
    scans, _, _ = _scan(host, region, ('none', 'minimap_scale'))
    states = [minimap_state(items, names) for items in scans]
    states = [state for state in states if state is not None]
    if not states or any(state != states[0] for state in states):
        return None
    return states[0]
