"""Bounded, atomic F1 status interaction using screenshot-relative anchors.

The host dispatcher owns the foreground-input lock for this entire operation.
This module never confirms dialogs and never sends Esc to unknown UI.
"""

import re
import time
from typing import Any

from plugin_platform.qqsg_fatigue import (
    fatigue_hover_points,
    fatigue_tooltip_region,
    parse_gathering_fatigue,
    status_panel_anchor,
    status_tabs_region,
)
from plugin_platform.qqsg_pickaxe_shop import package_use_pending


def _blocked_dialog(items: list[dict]) -> bool:
    """Do not cover a boxed-item confirmation or a currency checkout dialog."""
    text = ''.join(re.sub(r'\s+', '', str(item.get('text', ''))) for item in items)
    return package_use_pending(items) or any(
        label in text for label in ('选择数量', '兑换成功', '确定要使用', '是否兑换', '是否购买')
    )


def _focus(host) -> None:
    host._validate_bound_window_identity()
    if not host._activate_bound_window():
        raise RuntimeError('无法激活绑定窗口，已拒绝 F1 疲劳读取输入')


def _press_f1(host) -> None:
    _focus(host)
    host.keyboard.press('f1')
    time.sleep(0.2)


def _scan(host, region=None, variants=('none',), signature=False) -> tuple:
    """Keep only this transaction's temporary frame, releasing it after OCR."""
    host._validate_bound_window_foreground()
    frame = host._capture_window({'area': 'client', 'mode': 'foreground', 'region': region}, temporary=True)
    frame_id = frame['id']
    scans = []
    try:
        for variant in variants:
            items = host._ocr_recognize({
                'frame_id': frame_id, 'preprocess': variant, 'min_confidence': 0.45,
            })
            if region:
                items = [{
                    **item,
                    'center': [item['center'][0] + region[0], item['center'][1] + region[1]],
                    'box': [[point[0] + region[0], point[1] + region[1]] for point in item.get('box', [])],
                } for item in items]
            scans.append(items)
        host._validate_bound_window_foreground()
        result = scans, int(frame['width']), int(frame['height'])
        return (*result, host.frames[frame_id].tobytes()) if signature else result
    finally:
        host.frames.pop(frame_id, None)


def _same_anchor(first, second) -> bool:
    return second is not None and all(abs(a - b) <= 8 for a, b in zip(first, second))


def _close_verified_status(host, anchor: tuple[int, int], width: int, height: int) -> bool:
    """Only toggle F1 while the same status panel remains positively located."""
    region = status_tabs_region(anchor, width, height)
    if region is None:
        return False
    scans, _, _, before = _scan(host, region, ('none', 'task_scale'), signature=True)
    anchors = [status_panel_anchor(items) for items in scans]
    if not any(_same_anchor(anchor, found) for found in anchors):
        # Failure to recognize an already-open panel is not proof it is closed.
        return False
    if any(found is not None and not _same_anchor(anchor, found) for found in anchors):
        return False
    _press_f1(host)
    scans, _, _, after = _scan(host, region, ('none', 'task_scale'), signature=True)
    # Missing OCR alone is not evidence that F1 actually closed the panel.
    # Require the tab strip to change substantially as well; uncertain cleanup
    # pauses instead of authorizing mining through an obstructing panel.
    labels_remain = any(
        any(label in re.sub(r'\s+', '', str(item.get('text', '')))
            for label in ('角色信息', '角色抗性')) for items in scans for item in items
    )
    changed = (len(before) == len(after) and bool(before)
               and sum(abs(first - second) > 25 for first, second in zip(before, after))
               / len(before) > 0.20)
    return changed and not labels_remain and all(status_panel_anchor(items) is None for items in scans)


def read_gathering_fatigue(host) -> dict[str, Any]:
    """Read dynamic used/limit values and refuse further input if UI is unknown.

    The screenshot calibration is native-scale and translation-only. No user
    coordinates, resize estimates, dialog confirmation, or unbounded retry.
    """
    if host.dry_run:
        return {'reading': None, 'reason': '模拟运行：不打开 F1 或执行 OCR', 'ui_restored': True}
    anchor = None
    reading = None
    reason = '未读取到带完整标签的采集疲劳度'
    restored = False
    width, height = 0, 0
    try:
        _focus(host)
        scans, width, height = _scan(host)
        items = scans[0]
        if _blocked_dialog(items):
            return {'reading': None, 'reason': '存在物品使用或兑换确认，未执行 F1 操作', 'ui_restored': False}
        anchor = status_panel_anchor(items)
        if anchor is None:
            # At most one opening attempt; unknown panels are never blindly closed.
            _press_f1(host)
            scans, width, height = _scan(host)
            items = scans[0]
            if _blocked_dialog(items):
                return {'reading': None, 'reason': '存在物品使用或兑换确认，停止 F1 读取', 'ui_restored': False}
            anchor = status_panel_anchor(items)
        if anchor is None:
            return {'reading': None, 'reason': 'F1 状态页签未能定位，未猜测鼠标坐标', 'ui_restored': False}
        # Full-window OCR is only for locating the panel. Chat/history can also
        # contain fatigue-looking text; require a fresh hovered tooltip crop.
        reading = None
        region = fatigue_tooltip_region(anchor, width, height)
        if region is None:
            reason = '状态窗口疲劳提示区域超出客户区'
        elif reading is None:
            for x, y in fatigue_hover_points(anchor)[:3]:
                if not (0 <= x < width and 0 <= y < height):
                    reason = '状态窗口采集图标超出客户区'
                    break
                _focus(host)
                host._mouse_move({'x': x, 'y': y, 'duration': 0, 'coordinate_space': 'client'})
                time.sleep(0.35)
                scans, _, _ = _scan(host, region, ('none', 'task_scale'))
                values = {value for scan in scans if (value := parse_gathering_fatigue(scan)) is not None}
                if len(values) == 1:
                    reading = next(iter(values))
                    break
                if len(values) > 1:
                    reason = '采集疲劳读数冲突，未采用任意读数'
                    break
        if reading is not None:
            reason = '已从 F1 状态窗口读取采集疲劳度'
    except Exception as error:
        # OCR/capture/focus failures are unknown, never an empty fatigue allowance.
        reading = None
        reason = f'F1 采集疲劳读取失败：{error}'
    finally:
        if anchor is not None:
            try:
                restored = _close_verified_status(host, anchor, width, height)
            except Exception:
                restored = False
            if not restored:
                reading = None
                reason += '；未能确认状态窗口已收起，暂停后续游戏操作'
    return {'reading': list(reading) if reading is not None and restored else None,
            'reason': reason, 'ui_restored': restored}
