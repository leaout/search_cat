"""QQ 三国 multi-window mining plugin.

Each bound game window gets its own worker process from the script platform. The
default flow switches to line 14, follows configured movement actions to the
mine, then patrols and presses G at each configured point. Travel is kept as
explicit data because different characters can start on different maps.
"""

from __future__ import annotations

import re
import time
from typing import Any


ORE_RESOURCE = "images/ore.png"


def _valid_region(value: Any) -> tuple[int, int, int, int] | None:
    if value in (None, [], ()):
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("mining_region 必须是 [x, y, width, height]，或留空")
    x, y, width, height = (int(item) for item in value)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("mining_region 的宽高必须大于 0，坐标不能为负数")
    return x, y, width, height


def _fallback_points(value: Any) -> list[tuple[int, int]]:
    if not isinstance(value, (list, tuple)):
        return []
    points = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            x, y = int(item[0]), int(item[1])
        except (TypeError, ValueError):
            continue
        if x >= 0 and y >= 0:
            points.append((x, y))
    return points


def _activate(context) -> None:
    if context.dry_run:
        return
    result = context.windows.activate()
    if isinstance(result, dict) and not result.get("active", True):
        raise RuntimeError("游戏窗口激活失败")


def _capture_and_find(context, region):
    frame = context.capture.window(area="client", region=region)
    match = context.vision.find_image(
        frame,
        ORE_RESOURCE,
        threshold=float(context.config.get("template_threshold", 0.82)),
        grayscale=True,
    )
    return frame, match


def _match_point(match, region) -> tuple[int, int] | None:
    if not getattr(match, "found", False):
        return None
    center = getattr(match, "center", None)
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        return None
    offset_x, offset_y = (region[0], region[1]) if region else (0, 0)
    return int(center[0]) + offset_x, int(center[1]) + offset_y


def _click_mining_point(context, point, button, coordinate_space):
    x, y = point
    context.log(f"采集矿点：客户区 ({x}, {y})，鼠标 {button}")
    _activate(context)
    if context.dry_run:
        return
    context.mouse.click(
        x,
        y,
        button=button,
        mode="foreground",
        coordinate_space=coordinate_space,
    )
    # Moving the cursor away avoids covering the next template match.
    context.mouse.move(8, 8, coordinate_space="client")


def _wait(context, seconds: float) -> None:
    context.sleep(0.1 if context.dry_run else max(0.05, seconds))


def _compact(text: Any) -> str:
    return str(text or "").replace(" ", "").replace("\u3000", "").replace("：", ":")


def _item_center(item: dict[str, Any]) -> tuple[int, int] | None:
    center = item.get("center")
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        return int(center[0]), int(center[1])
    box = item.get("box")
    if not isinstance(box, (list, tuple)):
        return None
    points = [point for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not points:
        return None
    return (
        round(sum(float(point[0]) for point in points) / len(points)),
        round(sum(float(point[1]) for point in points) / len(points)),
    )


def _ocr_client(context) -> list[dict[str, Any]]:
    """Read the complete client area for line-switch controls."""
    frame = context.capture.window(area="client")
    base_items = list(context.ocr.recognize(frame, min_confidence=0.35, preprocess="none") or [])
    try:
        yellow_items = list(context.ocr.recognize(frame, min_confidence=0.30, preprocess="task_yellow") or [])
    except Exception:
        yellow_items = []
    merged = []
    seen = set()
    for item in base_items + yellow_items:
        text = _compact(item.get("text"))
        center = _item_center(item)
        key = (text, center)
        if not text or key in seen:
            continue
        seen.add(key)
        merged.append(item)
    for item in merged:
        item["_frame_width"] = int(frame.width)
        item["_frame_height"] = int(frame.height)
    return merged


def _find_server_button(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for item in items:
        text = _compact(item.get("text"))
        if not text or "客服" in text or _item_center(item) is None:
            continue
        score = 0
        if "服务器选线" in text:
            score = 4
        elif "服务器" in text and "选线" in text:
            score = 3
        elif text in {"选线", "服务器"}:
            score = 2
        if score:
            candidates.append((score, item))
    return max(candidates, key=lambda value: value[0])[1] if candidates else None


def _find_target_line(items: list[dict[str, Any]], target_line: int) -> dict[str, Any] | None:
    number = str(int(target_line))
    pattern = re.compile(rf"(?<!\d){re.escape(number)}(?:线|号线|线路)(?!\d)")
    candidates = []
    for item in items:
        text = _compact(item.get("text"))
        if text and _item_center(item) is not None and (pattern.search(text) or text in {number, f"线路{number}"}):
            candidates.append(item)
    if candidates:
        return min(candidates, key=lambda item: len(_compact(item.get("text"))))
    number_pattern = re.compile(r"(?<!\d)(\d{1,2})\s*(?:线|号线|线路)")
    numbered = []
    for item in items:
        text = _compact(item.get("text"))
        center = _item_center(item)
        match = number_pattern.search(text)
        if match and center is not None:
            numbered.append((int(match.group(1)), center, item))
    target_row = (int(target_line) - 1) // 2
    target_column = (int(target_line) - 1) % 2
    row_items = [entry for entry in numbered if (entry[0] - 1) // 2 == target_row]
    if not row_items:
        return None
    frame_width = max(int(entry[2].get("_frame_width", 0)) for entry in numbered)
    if frame_width <= 0:
        return None
    x_by_column = {}
    for column in (0, 1):
        values = [entry[1][0] for entry in numbered if (entry[0] - 1) % 2 == column]
        if values:
            x_by_column[column] = round(sum(values) / len(values))
    if 0 not in x_by_column:
        return None
    x_by_column.setdefault(1, round(frame_width * 0.66))
    y = round(sum(entry[1][1] for entry in row_items) / len(row_items))
    return {"text": f"{target_line}线（网格定位）", "center": [x_by_column[target_column], y], "_grid_fallback": True}


def _available_lines(items: list[dict[str, Any]]) -> list[int]:
    found = set()
    pattern = re.compile(r"(?<!\d)(\d{1,2})\s*(?:线|号线|线路)")
    for item in items:
        text = _compact(item.get("text"))
        for match in pattern.finditer(text):
            found.add(int(match.group(1)))
        if text.isdigit() and 1 <= int(text) <= 99:
            found.add(int(text))
    return sorted(found)


def _find_confirm(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred = ("确定", "确认", "进入游戏", "换线")
    candidates = []
    for item in items:
        text = _compact(item.get("text"))
        if not text or _item_center(item) is None:
            continue
        for rank, keyword in enumerate(preferred):
            if keyword in text:
                candidates.append((rank, len(text), item))
                break
    return min(candidates, key=lambda value: (value[0], value[1]))[2] if candidates else None


def _click_ocr_item(context, item: dict[str, Any]) -> None:
    center = _item_center(item)
    if center is None:
        raise RuntimeError("OCR 项目没有可点击坐标")
    context.mouse.click(center[0], center[1], mode="foreground", coordinate_space="client")
    if not context.dry_run:
        context.mouse.move(8, 8, coordinate_space="client")


def _switch_line(context, target_line: int) -> None:
    """Switch one bound window through the game's own server-line dialog."""
    context.log(f"准备切换到 {target_line} 线")
    _activate(context)
    if context.dry_run:
        context.log(f"模拟运行：打开选线界面并切换到 {target_line} 线")
        return
    # QQSG renders a large hand cursor; move it away before every OCR pass so
    # it cannot cover a line label in the selector.
    context.mouse.move(8, 8, coordinate_space="client")
    context.keyboard.press("esc", mode="foreground")
    _wait(context, float(context.config.get("line_switch_scan_wait", 0.8)))
    server_button = _find_server_button(_ocr_client(context))
    if server_button is None:
        raise RuntimeError("未识别到“服务器选线/选线”按钮")
    context.log(f"点击换线入口：{server_button.get('text', '') or '服务器选线'}")
    _click_ocr_item(context, server_button)
    _wait(context, float(context.config.get("line_switch_scan_wait", 0.8)))
    line_items = _ocr_client(context)
    target = _find_target_line(line_items, target_line)
    if target is None:
        available = _available_lines(line_items)
        visible = "、".join(f"{line}线" for line in available) if available else "无"
        raise RuntimeError(f"当前选线窗口没有目标线路：{target_line}线；当前可见线路：{visible}")
    if target.get("_grid_fallback"):
        context.log(f"未直接识别到 {target_line} 线，按选线网格定位点击", "warning")
    context.log(f"点击目标线路：{target.get('text', '') or f'{target_line}线'}")
    _click_ocr_item(context, target)
    _wait(context, 0.6)
    confirm = _find_confirm(_ocr_client(context))
    if confirm is not None:
        context.log(f"点击确认：{confirm.get('text', '') or '确定'}")
        _click_ocr_item(context, confirm)
    else:
        context.log("未发现确认按钮，按回车提交换线", "warning")
        context.keyboard.press("enter", mode="foreground")
    _wait(context, float(context.config.get("line_switch_wait", 3)))
    context.log(f"已提交换线到 {target_line} 线")


def _normalize_actions(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} 必须是动作数组")
    actions = []
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            raise ValueError(f"{name}[{index}] 必须是对象")
        direction = str(item.get("direction", "")).lower().strip()
        if direction and direction not in {"left", "right", "up", "down"}:
            raise ValueError(f"{name}[{index}].direction 只能是 left/right/up/down")
        seconds = float(item.get("seconds", item.get("duration", 0)))
        if seconds < 0 or seconds > 120:
            raise ValueError(f"{name}[{index}].seconds 必须在 0 到 120 之间")
        actions.append({
            "direction": direction,
            "seconds": seconds,
            "jump": bool(item.get("jump", False)),
            "g_count": max(0, int(item.get("g_count", 0))),
        })
    return actions


def _hold_direction(context, direction: str, seconds: float, jump: bool) -> None:
    if not direction or seconds <= 0:
        return
    _activate(context)
    if jump:
        context.keyboard.hold_combo(direction, "space", duration=min(3.0, max(0.03, seconds)), mode="foreground")
        remaining = seconds - min(3.0, max(0.03, seconds))
        if remaining > 0:
            _hold_direction(context, direction, remaining, False)
        return
    remaining = seconds
    while remaining > 0:
        pulse = min(2.5, remaining)
        if not context.dry_run:
            context.keyboard.key_down(direction, mode="foreground")
        try:
            _wait(context, pulse)
        finally:
            if not context.dry_run:
                context.keyboard.key_up(direction, mode="foreground")
        remaining -= pulse


def _press_g(context, count: int, interval: float) -> None:
    _activate(context)
    for _ in range(max(1, count)):
        if not context.dry_run:
            context.keyboard.press("g", mode="foreground")
        _wait(context, interval)


def _wait_for_refresh(context) -> None:
    mode = str(context.config.get("refresh_wait_mode", "next_hour"))
    if mode == "interval":
        seconds = max(60.0, float(context.config.get("refresh_interval", 3600)))
    else:
        now = time.time()
        seconds = 3600.0 - (now % 3600.0)
        if seconds < 5:
            seconds += 3600.0
    context.log(f"本轮巡逻完成，等待矿区刷新约 {round(seconds / 60, 1)} 分钟")
    if context.dry_run:
        context.log("模拟运行：跳过实际整点等待")
        return
    remaining = seconds
    while remaining > 0:
        if not context.windows.is_alive():
            raise RuntimeError("等待刷新期间游戏窗口已关闭")
        chunk = min(30.0, remaining)
        _wait(context, chunk)
        remaining -= chunk


def _run_patrol_g(context, actions: list[dict[str, Any]]) -> None:
    loops = max(0, int(context.config.get("patrol_loops", 0)))
    default_g = max(1, int(context.config.get("g_count", 1)))
    g_interval = max(0.1, float(context.config.get("g_interval", 0.8)))
    refresh_enabled = bool(context.config.get("refresh_wait_enabled", True))
    loop = 0
    while loops == 0 or loop < loops:
        loop += 1
        with context.step(f"矿区巡逻 {loop}"):
            for index, action in enumerate(actions, 1):
                direction = action["direction"]
                if direction:
                    context.log(
                        f"巡逻点 {index}/{len(actions)}：{direction} {action['seconds']:.2f}s"
                        + (" + 空格" if action["jump"] else "")
                    )
                    _hold_direction(context, direction, action["seconds"], action["jump"])
                count = action["g_count"] or default_g
                context.log(f"巡逻点 {index}：按 G {count} 次")
                _press_g(context, count, g_interval)
        if refresh_enabled and (loops == 0 or loop < loops):
            _wait_for_refresh(context)


def _run_template_loop(context, region) -> None:
    max_cycles = max(0, int(context.config.get("max_cycles", 30)))
    max_misses = max(1, int(context.config.get("max_misses", 3)))
    interval = max(0.05, float(context.config.get("mine_interval", 8)))
    button = str(context.config.get("mine_button", "right")).lower()
    coordinate_space = str(context.config.get("click_coordinate_space", "client")).lower()
    allow_fallback = bool(context.config.get("allow_coordinate_fallback", False))
    fallback_points = _fallback_points(context.config.get("fallback_points"))
    misses = 0
    cycles = 0
    point_index = 0
    while max_cycles == 0 or cycles < max_cycles:
        if not context.windows.is_alive():
            raise RuntimeError("绑定的游戏窗口已关闭")
        cycles += 1
        with context.step(f"挖矿 {cycles}"):
            point = None
            score = None
            try:
                _frame, match = _capture_and_find(context, region)
                score = float(getattr(match, "score", 0.0))
                point = _match_point(match, region)
            except (FileNotFoundError, ValueError, RuntimeError) as error:
                if not allow_fallback:
                    raise RuntimeError(f"矿点模板识别失败：{error}") from error
                context.log(f"模板识别失败，尝试备用坐标：{error}", "warning")
            if point is None and allow_fallback and fallback_points:
                point = fallback_points[point_index % len(fallback_points)]
                point_index += 1
            if point is None:
                misses += 1
                context.log(f"未识别到矿点（匹配分数 {score or 0:.3f}，连续 {misses}/{max_misses}）", "warning")
                if misses >= max_misses:
                    context.log("连续找不到矿点，安全结束当前窗口的挖矿")
                    return
                _wait(context, min(interval, 1.0))
                continue
            misses = 0
            context.log(f"矿点匹配分数：{score:.3f}" if score is not None else "使用备用采集点")
            _click_mining_point(context, point, button, coordinate_space)
            _wait(context, interval)


def on_load(context) -> None:
    context.log("QQ三国多窗口挖矿插件已加载")


def on_start(context) -> None:
    config = context.config
    region = _valid_region(config.get("mining_region"))
    mode = str(config.get("mining_mode", "patrol_g")).lower()
    if mode not in {"patrol_g", "template"}:
        raise ValueError("mining_mode 只能是 patrol_g 或 template")
    use_templates = bool(config.get("use_templates", True))

    window = context.windows.current()
    title = str(window.get("title", "")) if isinstance(window, dict) else ""
    context.log(
        f"开始挖矿：窗口 {title or '未命名'}，"
        f"目标线路 {int(config.get('target_line', 14))}，方式 {mode}，模拟运行 {context.dry_run}"
    )

    started_at = time.monotonic()
    with context.step("切换到目标线路"):
        if bool(config.get("switch_line_enabled", True)):
            _switch_line(context, int(config.get("target_line", 14)))
        else:
            context.log("已关闭自动换线，使用当前线路", "warning")
    with context.step("前往矿区"):
        if bool(config.get("skip_travel", False)):
            context.log("配置为跳过前往矿区，假定角色已经在矿区")
        else:
            travel = _normalize_actions(config.get("travel_actions", []), "travel_actions")
            if not travel:
                raise RuntimeError("没有配置 travel_actions；请先录入从当前起点到矿区的移动路线，或开启 skip_travel")
            _activate(context)
            for index, action in enumerate(travel, 1):
                context.log(f"前往矿区动作 {index}/{len(travel)}：{action['direction'] or '停留'} {action['seconds']:.2f}s")
                _hold_direction(context, action["direction"], action["seconds"], action["jump"])
                _wait(context, float(config.get("travel_action_pause", 0.3)))
    _wait(context, float(config.get("mine_entry_wait", 2)))

    if mode == "patrol_g":
        patrol = _normalize_actions(config.get("patrol_route", []), "patrol_route")
        if not patrol:
            raise RuntimeError("没有配置 patrol_route；请录入矿区四处巡逻动作")
        _run_patrol_g(context, patrol)
    else:
        if not use_templates:
            raise RuntimeError("template 模式必须启用 use_templates 并导入矿点模板")
        context.log("矿点识别方式：模板匹配（请确认已导入矿点模板）")
        _run_template_loop(context, region)

    elapsed = round(time.monotonic() - started_at, 1)
    context.debug.watch("mining_elapsed_seconds", elapsed)
    context.log(f"挖矿流程结束，耗时 {elapsed} 秒")

