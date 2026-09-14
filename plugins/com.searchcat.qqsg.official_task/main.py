import re
import math
from difflib import SequenceMatcher

from core.terrain_navigation import plan_route


OPTIONAL_TEMPLATES = {
    'dialog_task': 'images/dialog_task.png',
    'task_entry': 'images/task_entry.png',
    'accept_confirm': 'images/accept_confirm.png',
}

# Baseline movement envelope shared by normal characters. These are internal
# graph limits rather than user-facing character statistics.
DEFAULT_JUMP_X = 180.0
DEFAULT_JUMP_UP = 120.0


def _point(config, name):
    value = config.get(name)
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f'{name} 必须是 [x, y]')
    x, y = int(value[0]), int(value[1])
    if x < 0 or y < 0:
        raise ValueError(f'{name} 不能为负数')
    return x, y


def _click(context, x, y):
    return context.mouse.click(
        x,
        y,
        mode=context.config.get('input_mode', 'foreground'),
        coordinate_space='client',
    )


def _double_click(context, x, y):
    _click(context, x, y)
    _wait(context, context.config.get('double_click_interval', 0.12))
    return _click(context, x, y)


def _wait(context, seconds):
    context.sleep(0.1 if context.dry_run else float(seconds))


def _click_dialog_action(context, action, fallback_point):
    if context.config.get('use_templates', False):
        frame = context.capture.window(
            mode=context.config.get('capture_mode', 'auto'),
            area='client',
        )
        try:
            match = context.vision.find_image(
                frame,
                OPTIONAL_TEMPLATES[action],
                threshold=float(context.config.get('template_threshold', 0.85)),
            )
            context.debug.watch(f'{action}_match_score', match.score)
            if match.found:
                context.log(f'{action} 模板匹配成功，分数 {match.score:.4f}')
                return _click(context, match.center[0], match.center[1])
            context.log(f'{action} 模板未达到阈值', 'warning')
        except RuntimeError as error:
            context.log(f'{action} 模板不可用：{error}', 'warning')
        if not context.config.get('allow_coordinate_fallback', False):
            raise RuntimeError(f'{action} 模板识别失败，已停止以避免误点')
        context.log(f'{action} 使用已配置坐标回退', 'warning')
    return _click(context, *fallback_point)


def _talk_to_nearest_npc(context):
    activation = context.windows.activate()
    if not activation.get('active'):
        raise RuntimeError('游戏窗口激活失败，未发送对话按键')
    context.log('游戏窗口已激活，准备与 NPC 对话')
    _wait(context, context.config.get('window_activation_wait', 0.2))
    interaction = context.config.get('npc_interaction', 'keyboard_g')
    if interaction == 'mouse_double_click':
        point = _point(context.config, 'npc_double_click_point')
        context.log(f'双击 NPC：客户区坐标 {point}')
        _double_click(context, *point)
    elif interaction == 'keyboard_g':
        context.log('按 G 与附近 NPC 对话')
        context.keyboard.press('g', mode=context.config.get('input_mode', 'foreground'))
    else:
        raise ValueError('npc_interaction 必须是 keyboard_g 或 mouse_double_click')
    _wait(context, context.config.get('dialog_wait', 1))


def _accept_official_task(context):
    """Open the nested NPC menus and accept the selected official task."""
    if context.config.get('accept_mode', 'enter_spam') == 'enter_spam':
        count = int(context.config.get('accept_enter_count', 7))
        interval = float(context.config.get('accept_enter_interval', 0.28))
        if not 1 <= count <= 20:
            raise ValueError('accept_enter_count 应在 1 到 20 之间')
        context.log(f'接取任务：连续按 Enter {count} 次，间隔 {interval:.2f} 秒')
        mode = context.config.get('input_mode', 'foreground')
        for _ in range(count):
            context.keyboard.press('enter', mode=mode)
            _wait(context, interval)
        return
    if context.config.get('accept_mode') != 'guided_click':
        raise ValueError('accept_mode 必须是 enter_spam 或 guided_click')
    steps = (
        ('dialog_task', 'dialog_task_point', '对话/任务'),
        ('task_entry', 'task_entry_point', '官爵任务条目'),
        ('accept_confirm', 'accept_confirm_point', '请交给我吧'),
    )
    for action, point_name, label in steps:
        context.log(f'接取任务：选择“{label}”')
        _click_dialog_action(context, action, _point(context.config, point_name))
        _wait(context, context.config.get('dialog_wait', 1))


def _restore_game_control(context):
    """Click the scene once after Enter-spam leaves focus in a text input."""
    configured = context.config.get('restore_control_click_point')
    if isinstance(configured, list) and len(configured) == 2:
        point = _point(context.config, 'restore_control_click_point')
    else:
        window = context.windows.current()
        width = max(1, int(window.get('width', 800)))
        height = max(1, int(window.get('height', 600)))
        # The upper-middle scene is less likely to overlap the chat box or
        # right-side task controls than the bottom/right portions of the game.
        point = (round(width * 0.50), round(height * 0.35))
    context.log(f'接取任务后点击场景 {point}，退出输入模式并恢复角色操作')
    _click(context, *point)
    _wait(context, context.config.get('restore_control_wait', 0.35))


def _finish_npc_dialog(context):
    """Advance a normal NPC dialog and close it with Enter."""
    mode = context.config.get('input_mode', 'foreground')
    context.keyboard.press('enter', mode=mode)
    _wait(context, context.config.get('dialog_wait', 1))


def _scan_task(context):
    region = context.config.get('task_region', [520, 70, 270, 430])
    if not isinstance(region, list) or len(region) != 4:
        raise ValueError('task_region 必须是 [x, y, width, height]')
    origin_x, origin_y, width, height = (int(value) for value in region)
    frame = context.capture.window(
        mode=context.config.get('capture_mode', 'auto'),
        area='client',
        region=(origin_x, origin_y, width, height),
    )
    minimum = float(context.config.get('ocr_confidence', 0.55))
    passes = [('原图', context.ocr.recognize(frame, min_confidence=minimum))]
    # The task title is small yellow text over a patterned translucent panel.
    # Scale and colour isolation recover it much more reliably than one raw pass.
    for variant in ('task_scale', 'task_yellow'):
        enhanced = context.ocr.recognize(
            frame,
            min_confidence=min(minimum, 0.35),
            preprocess=variant,
        )
        passes.append((variant, enhanced))
    lines = []
    seen = set()
    for label, pass_lines in passes:
        pass_text = ' / '.join(str(line.get('text', '')).strip() for line in pass_lines)
        context.log(f'任务栏 OCR [{label}]：{pass_text or "<空>"}')
        for line in pass_lines:
            value = str(line.get('text', '')).strip()
            key = (_task_signature(value), tuple(line.get('center', ())))
            if value and key not in seen:
                seen.add(key)
                lines.append(line)
    for line in lines:
        line['client_center'] = [
            origin_x + int(line['center'][0]),
            origin_y + int(line['center'][1]),
        ]
        box = line.get('box')
        if isinstance(box, list) and box:
            line['client_box'] = [
                [origin_x + int(point[0]), origin_y + int(point[1])]
                for point in box
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]
    text = '\n'.join(line['text'] for line in lines)
    context.log(f'任务栏 OCR 汇总（{len(lines)} 行）：{text or "<空>"}')
    return text, lines


def _task_signature(text):
    return re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]', '', text)


def _has_official_task(text, keyword='官爵'):
    """Recognize the task even when the decorative panel corrupts a few glyphs."""
    compact = _task_signature(text)
    if keyword and _task_signature(keyword) in compact:
        return True
    # Paddle commonly reads the task detail prefix ``NPC`` as IPC/1PC/lPC.
    return bool(re.search(r'[NI1Il]PC[\u4e00-\u9fffA-Za-z0-9]', compact, re.IGNORECASE))


def _npc_ocr_candidates(text):
    """Extract NPC values, accepting common OCR corruptions of the NPC prefix."""
    return [
        match.strip()
        for match in re.findall(
            r'(?:N|I|1|l)PC\s*[:：]?\s*([\u4e00-\u9fff]{1,8})',
            text,
            flags=re.IGNORECASE,
        )
        if match.strip()
    ]


def _fuzzy_npc_match(text, routes):
    """Resolve noisy OCR against the authoritative captured NPC catalog."""
    candidates = _npc_ocr_candidates(text)
    names = [str(name) for name in routes]
    if not candidates or not names:
        return None, 0.0, candidates, ''

    # A unique preserved first character is strong evidence for two-character
    # Chinese names when decorative backgrounds corrupt the second glyph.
    votes = {}
    for candidate in candidates:
        same_prefix = [name for name in names if name.startswith(candidate[0])]
        if len(same_prefix) == 1:
            votes[same_prefix[0]] = votes.get(same_prefix[0], 0) + 1
    if votes:
        winner, count = max(votes.items(), key=lambda item: item[1])
        if count >= 2 or len(candidates) == 1:
            return winner, 100.0, candidates, '当前 NPC 库中姓氏唯一'

    scored = []
    for name in names:
        scores = sorted((SequenceMatcher(None, candidate, name).ratio() * 100
                         for candidate in candidates), reverse=True)
        # Prefer agreement across preprocessing passes over one accidental hit.
        consensus = scores[0] + (scores[1] * 0.25 if len(scores) > 1 else 0)
        scored.append((consensus, scores[0], name))
    scored.sort(reverse=True)
    consensus, best_score, winner = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0
    if best_score >= 60 and consensus - runner_up >= 12:
        return winner, best_score, candidates, f'领先次选 {consensus - runner_up:.1f} 分'
    return None, best_score, candidates, '候选区分度不足'


def _npc_line_center(lines):
    choices = []
    for line in lines:
        value = str(line.get('text', ''))
        match = re.search(
            r'(?:N|I|1|l)PC\s*[:：]?\s*([\u4e00-\u9fff]{1,8})',
            value,
            re.IGNORECASE,
        )
        if not match:
            continue
        center = line.get('client_center')
        client_box = line.get('client_box')
        click_point = center
        if isinstance(client_box, list) and client_box:
            xs = [int(point[0]) for point in client_box]
            ys = [int(point[1]) for point in client_box]
            left, right = min(xs), max(xs)
            top, bottom = min(ys), max(ys)
            # Paddle returns a box for the complete line. Estimate the centre
            # of the captured NPC-name substring within that line.
            name_start, name_end = match.span(1)
            text_length = max(1, len(value))
            name_ratio = ((name_start + name_end) / 2) / text_length
            click_point = [round(left + (right - left) * name_ratio), round((top + bottom) / 2)]
        if not isinstance(click_point, list) or len(click_point) != 2:
            continue
        confidence = float(line.get('confidence', 0))
        name_length = len(match.group(1))
        choices.append((confidence + min(name_length, 4) * 0.03,
                        confidence, name_length, click_point, client_box, value))
    if not choices:
        return None
    _rank, confidence, _length, point, box, value = max(choices, key=lambda item: item[0])
    return {
        'point': point,
        'box': box,
        'text': value,
        'confidence': confidence,
    }


def _find_target(text, lines, routes, context=None):
    npc_click = _npc_line_center(lines)
    npc_center = npc_click['point'] if npc_click else None
    if npc_click and context:
        context.log(
            f'NPC 点击定位：OCR“{npc_click["text"]}”，置信度 '
            f'{npc_click["confidence"]:.3f}，边界框 {npc_click["box"]}，'
            f'名称中心 {npc_center}'
        )
    for npc_name in sorted(routes, key=len, reverse=True):
        if npc_name in text:
            return npc_name, routes[npc_name], npc_center
    fuzzy_name, score, ocr_candidates, reason = _fuzzy_npc_match(text, routes)
    if ocr_candidates and context:
        context.log(
            f'NPC OCR 候选：{ocr_candidates}；路由库纠错：'
            f'{fuzzy_name or "未确定"}（{reason}，相似度 {score:.1f}%）',
            'info' if fuzzy_name else 'warning',
        )
    if fuzzy_name:
        return fuzzy_name, routes[fuzzy_name], npc_center
    markers = ('寻找', '找', '拜访', '访问', '对话', '回复', '回报')
    candidates = [line for line in lines if any(marker in line['text'] for marker in markers)]
    if not candidates:
        return None, None, None
    line = candidates[-1]
    value = line['text']
    match = re.search(r'(?:寻找|找|拜访|访问|与|回复|回报)\s*([\u4e00-\u9fff]{2,8})', value)
    npc_name = match.group(1) if match else value
    for suffix in ('进行对话', '对话', '交谈', '回复', '回报', '领取'):
        npc_name = npc_name.replace(suffix, '')
    return npc_name, None, line['client_center']


def _navigate_by_task_click(context, npc_name, route, point):
    """Use QQSG's task tracker link and monitor its built-in navigation."""
    context.log(f'点击任务栏 NPC“{npc_name or "未识别"}” {point}，启动游戏自动寻路')
    _click(context, *point)
    _wait(context, context.config.get('task_click_confirm_wait', 0.12))
    configured_park = context.config.get('task_cursor_park_point')
    if isinstance(configured_park, list) and len(configured_park) == 2:
        park_point = _point(context.config, 'task_cursor_park_point')
    else:
        window = context.windows.current()
        park_point = (
            round(max(1, int(window.get('width', 800))) * 0.35),
            round(max(1, int(window.get('height', 600))) * 0.55),
        )
    context.mouse.move(*park_point, duration=0.08, coordinate_space='client')
    context.log(f'鼠标已移出任务栏并停放到客户区 {park_point}，避免悬停影响下次 OCR')
    _wait(context, context.config.get('native_navigation_start_wait', 0.8))
    target = None
    if isinstance(route, (list, tuple)) and len(route) >= 3:
        target = (int(route[-2]), int(route[-1]))
    previous = None
    moved = False
    stable = 0
    maximum_scans = int(context.config.get('native_navigation_max_scans', 45))
    for scan in range(1, maximum_scans + 1):
        state = _scan_minimap(context)
        if not state:
            _wait(context, 0.5)
            continue
        position = tuple(state['position'])
        if target and abs(position[0] - target[0]) <= 1 and abs(position[1] - target[1]) <= 1:
            context.log(f'游戏自动寻路已进入 {npc_name} 邻域：{position}，目标 {target}')
            return
        if previous is not None and position != previous:
            moved = True
            stable = 0
        elif moved and position == previous:
            stable += 1
        previous = position
        context.log(
            f'游戏自动寻路监控 {scan}/{maximum_scans}：当前位置 {position}'
            + (f'，目标 {target}' if target else '')
        )
        if moved and stable >= 3:
            context.log(f'游戏自动寻路坐标已稳定在 {position}，准备尝试 NPC 对话')
            return
        _wait(context, context.config.get('native_navigation_scan_interval', 0.7))
    raise RuntimeError(f'点击任务栏 NPC 后，游戏自动寻路在 {maximum_scans} 次检测内未结束')


def _scan_minimap(context):
    region = context.config.get('minimap_region', [540, 0, 250, 90])
    if not isinstance(region, list) or len(region) != 4:
        raise ValueError('minimap_region 必须是 [x, y, width, height]')
    x, y, width, height = (int(value) for value in region)
    frame = context.capture.window(
        mode=context.config.get('capture_mode', 'auto'),
        area='client',
        region=(x, y, width, height),
    )
    lines = context.ocr.recognize(
        frame,
        min_confidence=float(context.config.get('minimap_ocr_confidence', 0.45)),
    )
    values = [str(line.get('text', '')).strip() for line in lines if str(line.get('text', '')).strip()]
    raw_text = ' '.join(values)
    compact = re.sub(r'\s+', '', raw_text)
    patterns = (
        r'[（(\[]?(\d{1,3})\s*[,，、:：.]\s*(\d{1,3})[）)\]]?',
        r'[Xx][:：]?(\d{1,3}).{0,4}[Yy][:：]?(\d{1,3})',
    )
    match = next((re.search(pattern, compact) for pattern in patterns if re.search(pattern, compact)), None)
    if not match:
        original_values = values
        for variant in ('minimap_scale', 'minimap_yellow'):
            enhanced_lines = context.ocr.recognize(
                frame, min_confidence=float(context.config.get('minimap_ocr_confidence', 0.45)),
                preprocess=variant,
            )
            enhanced_values = [str(line.get('text', '')).strip() for line in enhanced_lines
                               if str(line.get('text', '')).strip()]
            enhanced_text = ' '.join(enhanced_values)
            context.log(f'小地图增强 OCR [{variant}]：{enhanced_text or "<空>"}')
            enhanced_compact = re.sub(r'\s+', '', enhanced_text)
            match = next((re.search(pattern, enhanced_compact) for pattern in patterns
                          if re.search(pattern, enhanced_compact)), None)
            if match:
                # Preserve map-name evidence from the same frame's first pass.
                values = list(dict.fromkeys(original_values + enhanced_values))
                raw_text = ' '.join(values)
                lines = enhanced_lines
                break
    if not match:
        context.log(f'小地图 OCR：{raw_text or "<空>"}；未解析出坐标', 'warning')
        return None
    position = (int(match.group(1)), int(match.group(2)))
    map_name = ''
    for value in values:
        candidate = re.sub(r'[（(\[]?\d{1,3}\s*[,，、:：.]\s*\d{1,3}[）)\]]?', '', value)
        candidate = re.sub(r'[XxYy坐标][:：]?\d+', '', candidate).strip(' -_·.()（）[]【】')
        if re.search(r'[\u4e00-\u9fff]', candidate) and len(candidate) > len(map_name):
            map_name = candidate
    confidence = min((float(line.get('confidence', 0)) for line in lines), default=0)
    context.log(
        f'小地图定位：地图 {map_name or "未识别"}，坐标 {position}，'
        f'OCR {raw_text or "<空>"}，最低置信度 {confidence:.3f}'
    )
    context.debug.watch('minimap_position', list(position))
    context.debug.watch('minimap_map', map_name)
    return {'map': map_name, 'position': position, 'raw_text': raw_text}


def _normalize_map_name(value):
    return re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]', '', str(value)).lower()


def _terrain_model_for_map(config, map_name):
    models = config.get('terrain_models', {})
    if not isinstance(models, dict):
        return None
    wanted = _normalize_map_name(map_name)
    for name, model in models.items():
        if _normalize_map_name(name) == wanted and isinstance(model, dict):
            return model
    return None


def _route_waypoints(context, npc_name, legacy_route):
    routes = context.config.get('navigation_routes', {})
    definition = routes.get(npc_name) if isinstance(routes, dict) else None
    route_map = ''
    raw_waypoints = []
    if isinstance(definition, dict):
        route_map = str(definition.get('map', '')).strip()
        raw_waypoints = definition.get('waypoints', [])
    elif isinstance(definition, list):
        raw_waypoints = definition
    if not raw_waypoints and isinstance(legacy_route, list) and len(legacy_route) == 3:
        raw_waypoints = [[legacy_route[1], legacy_route[2]]]
        context.log(f'{npc_name} 没有定制路线，暂用 NPC 坐标作为单一路点', 'warning')
    waypoints = []
    for index, item in enumerate(raw_waypoints, 1):
        if isinstance(item, list) and len(item) == 2:
            waypoints.append({'x': int(item[0]), 'y': int(item[1]), 'map': route_map, 'jump': False})
        elif isinstance(item, dict) and 'x' in item and 'y' in item:
            waypoints.append({
                'x': int(item['x']), 'y': int(item['y']),
                'map': str(item.get('map', route_map)).strip(),
                'jump': bool(item.get('jump', False)),
            })
        else:
            raise ValueError(f'{npc_name} 的第 {index} 个路点格式无效')
    if not waypoints:
        raise RuntimeError(f'没有配置 {npc_name} 的定制路线或 NPC 坐标')
    return waypoints


def _hold_direction(context, key, duration):
    mode = context.config.get('input_mode', 'foreground')
    context.keyboard.key_down(key, mode=mode)
    try:
        _wait(context, duration)
    finally:
        context.keyboard.key_up(key, mode=mode)


def _move_to_waypoint(context, waypoint, waypoint_number, waypoint_total):
    tolerance = int(context.config.get('arrival_tolerance', 1))
    maximum_attempts = int(context.config.get('waypoint_max_attempts', 30))
    seconds_per_unit = float(context.config.get('seconds_per_coordinate', 0.18))
    minimum_pulse = float(context.config.get('minimum_move_pulse', 0.12))
    maximum_pulse = float(context.config.get('maximum_move_pulse', 0.8))
    stuck_limit = int(context.config.get('stuck_scan_limit', 3))
    last_position = None
    stuck_count = 0
    for attempt in range(1, maximum_attempts + 1):
        state = _scan_minimap(context)
        if not state:
            if attempt >= int(context.config.get('position_read_retries', 3)):
                raise RuntimeError('连续无法识别小地图坐标，请检查 minimap_region')
            _wait(context, context.config.get('position_scan_interval', 0.35))
            continue
        current_x, current_y = state['position']
        expected_map = waypoint.get('map', '')
        if expected_map and state['map']:
            actual = _normalize_map_name(state['map'])
            expected = _normalize_map_name(expected_map)
            if actual and expected and actual != expected and actual not in expected and expected not in actual:
                raise RuntimeError(f'当前地图“{state["map"]}”与路点地图“{expected_map}”不一致')
        dx, dy = waypoint['x'] - current_x, waypoint['y'] - current_y
        context.log(
            f'路点 {waypoint_number}/{waypoint_total}，尝试 {attempt}/{maximum_attempts}：'
            f'当前位置 ({current_x},{current_y}) → ({waypoint["x"]},{waypoint["y"]})，偏差 ({dx},{dy})'
        )
        if abs(dx) <= tolerance and abs(dy) <= tolerance:
            if waypoint.get('jump'):
                context.keyboard.press('space', mode=context.config.get('input_mode', 'foreground'))
                _wait(context, context.config.get('jump_wait', 0.4))
            return
        position = (current_x, current_y)
        stuck_count = stuck_count + 1 if position == last_position else 0
        last_position = position
        if stuck_count >= stuck_limit:
            context.log('坐标连续不变，执行跳跃脱困', 'warning')
            context.keyboard.press('space', mode=context.config.get('input_mode', 'foreground'))
            _wait(context, context.config.get('jump_wait', 0.4))
            stuck_count = 0
        if abs(dx) >= abs(dy) and abs(dx) > tolerance:
            key, distance = ('right' if dx > 0 else 'left'), abs(dx)
        else:
            key, distance = ('down' if dy > 0 else 'up'), abs(dy)
        duration = max(minimum_pulse, min(maximum_pulse, distance * seconds_per_unit))
        context.log(f'移动：按住 {key} {duration:.2f} 秒')
        _hold_direction(context, key, duration)
        _wait(context, context.config.get('position_scan_interval', 0.35))
    raise RuntimeError(f'在最大尝试次数内未能到达路点 ({waypoint["x"]},{waypoint["y"]})')


def _navigate_route(context, npc_name, legacy_route):
    waypoints = _route_waypoints(context, npc_name, legacy_route)
    context.log(f'路线寻路：{npc_name}，共 {len(waypoints)} 个路点')
    if context.dry_run:
        state = _scan_minimap(context)
        if not state:
            raise RuntimeError('模拟运行无法读取小地图坐标，请先校准 minimap_region')
        context.log(f'模拟路线：当前 {state}；路点 {waypoints}')
        return
    if len(waypoints) == 1:
        route_map = waypoints[0].get('map', '')
        model = _terrain_model_for_map(context.config, route_map)
        if isinstance(model, dict) and model.get('terrain_records'):
            dynamic_plan = dict(model)
            dynamic_plan['target'] = [waypoints[0]['x'], waypoints[0]['y']]
            dynamic_plan['steps'] = []
            context.log(f'使用 {route_map} 地形模型，从人物实时坐标规划到 {npc_name}')
            _execute_terrain_route(context, dynamic_plan, f'前往 NPC {npc_name}')
            return
    for index, waypoint in enumerate(waypoints, 1):
        _move_to_waypoint(context, waypoint, index, len(waypoints))


def _navigate_to_target(context, npc_name, route, fallback_point):
    if route:
        _navigate_route(context, npc_name, route)
    elif npc_name:
        _navigate_route(context, npc_name, None)
    elif fallback_point:
        context.log(f'NPC {npc_name} 不在路由库，点击 OCR 识别到的任务文字回退寻路', 'warning')
        _click(context, *fallback_point)
    else:
        raise RuntimeError('任务栏中没有识别到可寻路的 NPC')
    _wait(context, context.config.get('arrival_wait', 0.8))


def on_load(context):
    context.log('QQ三国官爵任务插件已加载')


def _terrain_cell(point):
    """Experimental truncation model: integer OCR cannot resolve sub-cell position."""
    return tuple(math.floor(float(value)) for value in point)


def _minimap_cell_center(position, scale):
    """Convert integer minimap OCR to the centre of its terrain coordinate cell."""
    return [(float(position[0]) + 0.5) * scale, (float(position[1]) + 0.5) * scale]


def _align_to_connection(context, read_position, point, mode, step_index):
    """Walk onto a jump/drop connection cell before executing the transfer."""
    wanted = _terrain_cell(point)
    last_position = None
    unchanged = 0
    for attempt in range(10):
        position = tuple(read_position())
        # The minimap exposes integer coordinates only. On slopes the visible
        # Y value can differ by one from the parsed platform connection even
        # when the character is already at the correct take-off X position.
        # Platform topology comes from the terrain model, so Y is diagnostic
        # here rather than a reason to reject an otherwise valid route.
        if position[0] == wanted[0]:
            if position[1] != wanted[1]:
                context.log(
                    f'连接点横向已对齐：实测 {position}，规划整数格 {wanted}；'
                    '忽略小地图 Y 取整差异并继续执行',
                    'warning',
                )
            else:
                context.log(f'连接点已对齐：{position}，准备执行步骤 {step_index}')
            return position
        dx, dy = wanted[0] - position[0], wanted[1] - position[1]
        key = 'right' if dx > 0 else 'left'
        duration = min(0.32, max(0.12, abs(dx) * 0.16))
        context.log(
            f'起跳前对齐：当前位置 {position} → 连接点整数格 {wanted}，'
            f'执行 {key} {duration:.2f}s'
        )
        context.keyboard.key_down(key, mode=mode)
        try:
            _wait(context, duration)
        finally:
            context.keyboard.key_up(key, mode=mode)
        _wait(context, 0.3)
        unchanged = unchanged + 1 if position == last_position else 0
        last_position = position
        if unchanged >= 4:
            raise RuntimeError(
                f'无法走到步骤 {step_index} 的连接点 {wanted}，人物停在 {position}；'
                '该平台边界或连接点可能解析错误'
            )
    raise RuntimeError(f'步骤 {step_index} 起跳前对齐超过 10 次，目标连接点 {wanted}')


def _jump_direction(step, next_step, final_target, position, previous_direction=None):
    """Infer traversal direction even when a transfer is vertically aligned."""
    candidates = [
        float(step['to'][0]) - float(step['from'][0]),
        (float(next_step['to'][0]) - float(step['from'][0])) if next_step else 0,
        float(final_target[0]) - float(position[0]),
        1 if previous_direction == 'right' else (-1 if previous_direction == 'left' else 0),
    ]
    delta = next((value for value in candidates if abs(value) > 1e-6), 0)
    return 'right' if delta > 0 else ('left' if delta < 0 else None)


def _walk_endpoint_reached(position, endpoint, horizontal_tolerance=0):
    """Check a walk endpoint with OCR quantization tolerance."""
    endpoint_cell = _terrain_cell(endpoint)
    return (
        abs(position[0] - endpoint_cell[0]) <= horizontal_tolerance
        and abs(position[1] - endpoint_cell[1]) <= 1
    )


def _execute_terrain_route(context, plan, purpose, replan_count=0):
    """Plan from the live position and execute against a saved terrain model."""
    steps = plan.get('steps')
    if not isinstance(steps, list) or 'target' not in plan:
        raise ValueError('请先在地图调试界面规划并载入路线')
    tolerance = float(context.config.get('terrain_test_tolerance', 1.0))
    if not 0 < tolerance <= 2:
        raise ValueError('terrain_test_tolerance 应在 0 到 2 之间')
    mode = context.config.get('input_mode', 'foreground')

    def read_position():
        for _ in range(3):
            state = _scan_minimap(context)
            if state:
                if _normalize_map_name(state['map']) != _normalize_map_name(plan['map']):
                    raise RuntimeError(f'地图未识别或与{purpose}地图不一致，停止执行')
                return state['position']
            _wait(context, 0.35)
        raise RuntimeError('连续无法读取人物坐标，停止测试')

    position = read_position()
    records = plan.get('terrain_records')
    if not isinstance(records, list) or not records:
        raise RuntimeError('旧路线没有保存地形模型，请在地图调试中重新规划并载入一次')
    scale = float(plan.get('scale', 100))
    target = plan['target']
    maximum_replans = int(context.config.get('maximum_route_replans', 8))
    if replan_count > maximum_replans:
        raise RuntimeError(f'实时落点偏离后已重新规划 {maximum_replans} 次，停止执行')
    try:
        dynamic_plan = plan_route(
            [tuple(record) for record in records],
            _minimap_cell_center(position, scale),
            [float(target[0]) * scale, float(target[1]) * scale],
            scale=scale,
            jump_x=DEFAULT_JUMP_X,
            jump_up=DEFAULT_JUMP_UP,
            allow_climb=False,
        )
    except ValueError as error:
        raise RuntimeError(f'无法从当前坐标 {position} 重新规划到 {target}：{error}') from error
    dynamic_plan['map'] = plan['map']
    steps = dynamic_plan['steps']
    context.log(
        f'实时规划：当前坐标 {position} → 目标 {target}，生成 {len(steps)} 个步骤；'
        f'OCR 整数格按中心 ({position[0] + 0.5:.1f}, {position[1] + 0.5:.1f}) 吸附地形；'
        f'不再使用保存时的固定起点 {plan.get("start")}'
    )
    context.log(f'{purpose}：根据人物实时坐标生成几何最短路线（使用默认角色移动能力）')
    context.log('连接点改为同整数格确认，不再允许相邻格提前到达。取整暂按向下截断；格内位置仍不可观测。', 'warning')
    previous_direction = None
    for index, step in enumerate(steps, 1):
        action = step['action']
        if action not in ('walk', 'jump', 'drop', 'climb'):
            raise ValueError(f'未知动作 {action}')
        context.log(f'步骤 {index}/{len(steps)}：{action}，平台 {step["segment"]}，'
                    f'{step["from"]} → {step["to"]}')
        if context.dry_run:
            continue
        aligned_position = None
        if action in ('jump', 'drop', 'climb'):
            aligned_position = _align_to_connection(context, read_position, step['from'], mode, index)
        target_cell = _terrain_cell(step['to'])
        previous, unchanged = None, 0
        obstacle_recoveries = 0
        transfer_executed = False
        for attempt in range(20):
            position = read_position()
            dx, dy = target_cell[0] - position[0], target_cell[1] - position[1]
            context.log(f'地形反馈：当前位置 {position}，规划 {step["to"]}，目标整数格 {target_cell}，'
                        f'偏差 ({dx},{dy})，动作 {action}')
            is_final_step = index == len(steps)
            walk_reached = action == 'walk' and _walk_endpoint_reached(
                position,
                step['to'],
                horizontal_tolerance=1 if is_final_step else 0,
            )
            arrival_radius = float(context.config.get('npc_arrival_radius', 1.5))
            npc_distance = math.dist(
                (float(position[0]), float(position[1])),
                (float(target[0]), float(target[1])),
            )
            npc_neighborhood_reached = is_final_step and npc_distance <= arrival_radius
            transfer_reached = action != 'walk' and transfer_executed and dx == 0 and dy == 0
            if walk_reached or transfer_reached or npc_neighborhood_reached:
                if npc_neighborhood_reached and (dx != 0 or dy != 0):
                    context.log(
                        f'已进入 NPC 目标邻域：当前位置 {position}，NPC 原始坐标 {target}，'
                        f'距离 {npc_distance:.2f} ≤ {arrival_radius:.2f}'
                    )
                elif walk_reached and dy != 0:
                    context.log(
                        f'已进入行走路线端点邻域：实测 {position}，规划 {step["to"]}；'
                        'Y 差异来自斜坡/拱形轨迹或整数显示'
                    )
                else:
                    context.log('到达目标整数格（非精确小数位置），当前步骤完成')
                break
            unchanged = unchanged + 1 if position == previous else 0
            previous = position
            if unchanged >= 3:
                is_slope_walk = (
                    action == 'walk'
                    and abs(float(step['to'][1]) - float(step['from'][1])) > 1e-6
                )
                if is_slope_walk:
                    context.log(
                        '斜坡行走处于同一整数坐标格，继续沿路线方向移动，不执行自动跳跃',
                        'warning',
                    )
                    unchanged = 0
                elif action == 'walk' and dx != 0 and obstacle_recoveries < 2:
                    key = 'right' if dx > 0 else 'left'
                    obstacle_recoveries += 1
                    context.log(
                        f'行走坐标连续不变，判断前方有台阶或小障碍；'
                        f'普通行走失败，执行第 {obstacle_recoveries} 次向前跳跃（{key} + 空格）',
                        'warning',
                    )
                    context.keyboard.directional_jump(
                        key,
                        lead_time=float(context.config.get('jump_direction_lead', 0.10)),
                        jump_hold=float(context.config.get('jump_key_hold', 0.12)),
                        follow_time=float(context.config.get('jump_direction_follow', 0.05)),
                        mode=mode,
                    )
                    _wait(context, 0.7)
                    unchanged = 0
                    previous = None
                    continue
                raise RuntimeError(
                    f'步骤 {index} 在 {position} 连续无位移，规划边 '
                    f'{step["from"]} → {step["to"]} 无法执行；该处地形连接可能解析错误'
                )
            if action == 'jump':
                next_step = steps[index] if index < len(steps) else None
                jump_key = _jump_direction(
                    step, next_step, target, aligned_position or position, previous_direction,
                )
                hold = float(context.config.get('jump_key_hold', 0.12))
                before_jump = tuple(position)
                context.log(f'优先执行原地跳：不按方向，只按住空格 {hold:.2f}s')
                context.keyboard.hold_combo('space', duration=hold, mode=mode)
                transfer_executed = True
                _wait(context, float(context.config.get('jump_landing_wait', 0.75)))
                landing = tuple(read_position())
                if landing != target_cell and landing == before_jump and jump_key:
                    lead = float(context.config.get('jump_direction_lead', 0.10))
                    follow = float(context.config.get('jump_direction_follow', 0.05))
                    context.log(
                        f'原地跳后坐标未变化，改用向前跳：先按 {jump_key} {lead:.2f}s，'
                        f'按住空格 {hold:.2f}s，落地前继续 {jump_key} {follow:.2f}s',
                        'warning',
                    )
                    context.keyboard.directional_jump(
                        jump_key, lead_time=lead, jump_hold=hold,
                        follow_time=follow, mode=mode,
                    )
                    previous_direction = jump_key
                    _wait(context, float(context.config.get('jump_landing_wait', 0.75)))
                    landing = tuple(read_position())
                if landing != target_cell:
                    context.log(
                        f'原地跳/向前跳尝试后的实际落点 {landing}，预期连接格 {target_cell}；'
                        f'立即从实时落点重新规划（第 {replan_count + 1}/{maximum_replans} 次）',
                        'warning',
                    )
                    return _execute_terrain_route(
                        context, plan, purpose, replan_count=replan_count + 1,
                    )
                continue
            if action == 'drop':
                next_step = steps[index] if index < len(steps) else None
                drop_key = _jump_direction(
                    step, next_step, target, aligned_position or position, previous_direction,
                )
                if not drop_key:
                    raise RuntimeError(
                        f'步骤 {index} 是下落连接，但无法从路线推断走出平台的方向：'
                        f'{step["from"]} → {step["to"]}'
                    )
                hold = float(context.config.get('drop_direction_hold', 0.30))
                context.log(f'执行下落：持续按 {drop_key} {hold:.2f}s 走出平台边缘')
                context.keyboard.hold_combo(drop_key, duration=hold, mode=mode)
                previous_direction = drop_key
                transfer_executed = True
                _wait(context, float(context.config.get('drop_landing_wait', 0.75)))
                landing = tuple(read_position())
                if landing != target_cell:
                    context.log(
                        f'下落只执行一次：实际落点 {landing}，预期连接格 {target_cell}；'
                        f'立即从实时落点重新规划（第 {replan_count + 1}/{maximum_replans} 次）',
                        'warning',
                    )
                    return _execute_terrain_route(
                        context, plan, purpose, replan_count=replan_count + 1,
                    )
                continue
            if action == 'climb':
                key = ('right' if dx > 0 else 'left') if dx != 0 else ('down' if dy > 0 else 'up')
            else:
                if dx == 0 and action == 'walk':
                    planned_dx = float(step['to'][0]) - float(step['from'][0])
                    key = 'right' if planned_dx > 0 else ('left' if planned_dx < 0 else None)
                else:
                    key = 'right' if dx > 0 else 'left'
                if dx == 0:
                    key = key if action == 'walk' else None
            duration = min(0.5, max(0.12, abs(dy if action == 'climb' else dx) * 0.18))
            if is_final_step and npc_distance <= 3:
                duration = min(duration, float(context.config.get('near_npc_move_pulse', 0.08)))
            context.log(f'执行 {key} {duration:.2f}s')
            if key:
                if key in ('left', 'right'):
                    previous_direction = key
                context.keyboard.key_down(key, mode=mode)
            try:
                _wait(context, duration)
            finally:
                if key:
                    context.keyboard.key_up(key, mode=mode)
            _wait(context, 0.7 if action in ('jump', 'drop') else 0.35)
        else:
            raise RuntimeError(f'步骤 {index} 超过 20 次尝试，停止测试')
    context.log('模拟路线检查结束，未发送输入' if context.dry_run else f'{purpose}完成')


def _run_terrain_test(context):
    """Run the optional map-debug target without entering the task workflow."""
    plan = context.config.get('terrain_test_plan', {})
    if not isinstance(plan, dict) or 'target' not in plan:
        raise ValueError('请先在地图调试界面规划并载入路线')
    if not plan.get('terrain_records'):
        model = _terrain_model_for_map(context.config, plan.get('map', ''))
        if model and model.get('terrain_records'):
            target = plan['target']
            plan = {**model, 'target': target, 'steps': []}
            context.log('测试目标来自旧路线，已自动装入该地图的持久化地形模型')
    context.log('地图测试模式：只验证所选目标，不执行官爵任务')
    _execute_terrain_route(context, plan, '地图测试')


def on_start(context):
    if context.config.get('terrain_test_enabled', False):
        if not context.windows.is_alive():
            raise RuntimeError('绑定的游戏窗口已经失效')
        _run_terrain_test(context)
        return
    if not context.config.get('calibrated', False) and not context.dry_run:
        raise RuntimeError('尚未校准官爵任务坐标。请先在模拟模式调整坐标，再将 calibrated 改为 true。')
    if not context.config.get('calibrated', False):
        context.log('当前未标记为已校准，仅允许模拟运行。', 'warning')
    if not context.windows.is_alive():
        raise RuntimeError('绑定的游戏窗口已经失效')

    context.log(
        f'开始官爵任务：OCR 状态循环，输入方式 '
        f"{context.config.get('input_mode', 'foreground')}，模拟运行 {context.dry_run}"
    )

    routes = context.config.get('npc_routes', {})
    if not isinstance(routes, dict):
        raise ValueError('npc_routes 必须是 NPC 名称到 [地图ID, X, Y] 的对象')

    issuer_name = str(context.config.get('issuer_npc_name', '奋威中郎将')).strip()
    issuer_route = routes.get(issuer_name)
    navigation_routes = context.config.get('navigation_routes', {})
    has_custom_issuer_route = isinstance(navigation_routes, dict) and issuer_name in navigation_routes
    if not issuer_route and not has_custom_issuer_route:
        raise RuntimeError(
            f'没有“{issuer_name}”的位置或定制路线，请先导入游戏数据或配置 navigation_routes'
        )

    with context.step(f'前往{issuer_name}'):
        _navigate_to_target(context, issuer_name, issuer_route, None)

    with context.step(f'向{issuer_name}领取任务'):
        _talk_to_nearest_npc(context)
        _accept_official_task(context)
        _restore_game_control(context)

    if context.dry_run:
        context.log('模拟运行已完成：已验证前往任务发布 NPC 和接取任务的操作序列。')
        return

    target_catalog = dict(routes)
    if isinstance(navigation_routes, dict):
        for route_name in navigation_routes:
            target_catalog.setdefault(route_name, None)

    previous_signature = ''
    unchanged = 0
    empty_scans = 0
    completed_steps = 0
    seen_task = False
    maximum_cycles = int(context.config.get('maximum_cycles', 10))
    for cycle in range(1, maximum_cycles + 1):
        with context.step(f'识别并处理当前任务 {cycle}/{maximum_cycles}'):
            text, lines = _scan_task(context)
            signature = _task_signature(text)
            task_keyword = str(context.config.get('task_keyword', '官爵'))
            if not signature or not _has_official_task(text, task_keyword):
                empty_scans += 1
                context.log(f'未发现官爵任务（连续 {empty_scans} 次）', 'warning')
                if empty_scans >= int(context.config.get('completion_confirm_scans', 2)):
                    if seen_task:
                        break
                    raise RuntimeError('始终没有识别到官爵任务，请检查 task_region 和 OCR 日志')
                _wait(context, context.config.get('monitor_interval', 1.5))
                continue
            empty_scans = 0
            seen_task = True
            if signature == previous_signature:
                unchanged += 1
            else:
                if previous_signature:
                    completed_steps += 1
                unchanged = 0
                previous_signature = signature
            if unchanged > int(context.config.get('unchanged_retries', 3)):
                raise RuntimeError('任务栏内容连续多次没有变化，寻路或 NPC 对话可能失败')
            npc_name, route, fallback_point = _find_target(
                text, lines, target_catalog, context=context,
            )
            context.log(f'当前目标 NPC：{npc_name or "未识别"}；任务签名：{signature}')
            if fallback_point and context.config.get('prefer_task_click_navigation', True):
                _navigate_by_task_click(context, npc_name, route, fallback_point)
            else:
                _navigate_to_target(context, npc_name, route, fallback_point)
            context.keyboard.press('~', mode=context.config.get('input_mode', 'foreground'))
            _talk_to_nearest_npc(context)
            _finish_npc_dialog(context)
            context.storage.write_json('progress.json', {
                'status': 'monitoring',
                'completed_steps': completed_steps,
                'cycle': cycle,
                'npc': npc_name,
                'task_text': text,
            })
            context.debug.watch('completed_steps', completed_steps)
            _wait(context, context.config.get('monitor_interval', 1.5))
    else:
        raise RuntimeError('达到最大识别轮数，仍未确认官爵任务完成')

    context.storage.write_json('progress.json', {
        'status': 'completed',
        'completed_steps': completed_steps,
    })
    context.log('官爵任务流程执行完毕，请确认游戏内任务已经完成。')


def on_stop(context):
    context.log('QQ三国官爵任务插件已停止')
