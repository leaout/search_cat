"""Independent QQSG daily-task plugin entry point.

The task handlers intentionally keep navigation and combat controls explicit in
the configuration.  This makes the first real run observable and recoverable
instead of silently sending an unknown key sequence to the game.
"""

import re
import time
from difflib import SequenceMatcher

from plugin_platform.task_answering import anti_fraud_answer, match_question, parse_feedback_answer, parse_options


PROGRESS_RE = re.compile(r'(?<!\d)(\d{1,4})\s*/\s*(\d{1,4})(?!\d)')
COMPLETION_MARKERS = ('任务完成', '已完成', '完成')
TASK_ALIASES = {
    'gai_xia_xue_yi': 'gai_xia_xue_yi',
    'gai_xia': 'gai_xia_xue_yi',
    '垓下学艺': 'gai_xia_xue_yi',
    'mie_shu_jing_cang': 'mie_shu_jing_cang',
    'mie_shu': 'mie_shu_jing_cang',
    '灭鼠靖仓': 'mie_shu_jing_cang',
    'ju_xiao_lian': 'ju_xiao_lian',
    '举孝廉': 'ju_xiao_lian',
    'transport': 'transport',
    '运送物资': 'transport',
}


def _wait(context, seconds=0.8):
    context.sleep(0.1 if context.dry_run else seconds)


def _scan_task(context):
    region = context.config.get('task_region', [520, 70, 270, 430])
    frame = context.capture.window(area='client', region=tuple(int(value) for value in region))
    items = context.ocr.recognize(frame, min_confidence=0.45, preprocess='task_scale')
    lines = [item for item in items if str(item.get('text', '')).strip()]
    return region, lines


def _box_center(box):
    points = [point for point in (box or []) if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not points:
        return None
    return round(sum(float(point[0]) for point in points) / len(points)), round(
        sum(float(point[1]) for point in points) / len(points)
    )


def _task_snapshot(context):
    """Read the configured task panel and return its text plus OCR boxes."""
    region, lines = _scan_task(context)
    text = ' '.join(str(item.get('text', '')).strip() for item in lines).strip()
    return region, lines, text


def _activate(context):
    """Activate the bound game before foreground keyboard or mouse input."""
    if context.dry_run:
        return
    result = context.windows.activate()
    if isinstance(result, dict) and not result.get('active', True):
        raise RuntimeError('游戏窗口激活失败，未发送任务操作')


def _press(context, key: str, count: int = 1, delay: float = 0.35):
    """Press a key repeatedly while keeping simulated runs side-effect free."""
    for _ in range(max(0, int(count))):
        if not context.dry_run:
            context.keyboard.press(key, mode='foreground')
        _wait(context, delay)


def _talk_to_npc(context, label: str, enter_count: int = 6):
    """Open a nearby NPC dialogue and advance its common task choices.

    The plugin cannot infer an NPC's world position from the task panel alone;
    callers must either place the character nearby or configure a navigation
    route in a future revision.
    """
    context.log(f'{label}：尝试与附近 NPC 对话；请确认角色已经到达 NPC 附近')
    _activate(context)
    if not context.dry_run:
        context.keyboard.press('g', mode='foreground')
    _wait(context, 0.6)
    _press(context, 'enter', enter_count, float(context.config.get('dialog_key_interval', 0.35)))


def _click_task_npc(context, names: tuple[str, ...]) -> bool:
    """Click a named NPC in the task panel to invoke game auto-navigation."""
    region, lines, _ = _task_snapshot(context)
    item = next(
        (entry for entry in lines
         if any(name in str(entry.get('text', '')) for name in names)),
        None,
    )
    if item is None:
        return False
    center = _box_center(item.get('box'))
    if center is None:
        context.log('识别到任务 NPC，但没有可用点击坐标', 'warning')
        return False
    click_x = int(region[0]) + center[0]
    click_y = int(region[1]) + center[1]
    context.log(f'点击任务栏 NPC：客户区 ({click_x}, {click_y})')
    _activate(context)
    if not context.dry_run:
        context.mouse.click(click_x, click_y, mode='foreground', coordinate_space='client')
        # Do not leave the pointer over the OCR target; it can cover the next
        # capture and change the task-panel recognition result.
        context.mouse.move(10, 10, coordinate_space='client')
    return True


def _read_progress(text: str):
    """Return the first ``current/total`` counter visible in task OCR."""
    match = PROGRESS_RE.search(str(text or ''))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _has_completion_marker(text: str) -> bool:
    value = str(text or '')
    return any(marker in value for marker in COMPLETION_MARKERS)


def _resolve_task_sequence(config: dict) -> list[str]:
    """Resolve the configured run mode into canonical task identifiers.

    ``task_mode=single`` intentionally bypasses ``task_sequence`` so one
    task can be tested without accidentally running the remaining dailies.
    The function is kept pure so the UI/configuration behavior can be tested
    without starting a game or OCR engine.
    """
    mode = str(config.get('task_mode', 'sequence')).strip().lower()
    if mode in {'single', 'debug', 'one'}:
        selected = str(config.get('single_task', '')).strip()
        canonical = TASK_ALIASES.get(selected)
        if not canonical:
            raise ValueError(
                '单任务调试未选择有效任务，请设置 single_task 为 gai_xia_xue_yi、'
                'mie_shu_jing_cang、ju_xiao_lian 或 transport'
            )
        return [canonical]

    sequence = config.get(
        'task_sequence',
        ['gai_xia_xue_yi', 'mie_shu_jing_cang', 'ju_xiao_lian', 'transport'],
    )
    if not isinstance(sequence, (list, tuple)) or not sequence:
        raise ValueError('task_sequence 不能为空；如需调试单项，请使用 task_mode=single')
    resolved = []
    for value in sequence:
        canonical = TASK_ALIASES.get(str(value).strip())
        if not canonical:
            raise ValueError(f'不支持的任务类型：{value}')
        resolved.append(canonical)
    return resolved


def _normalize_map_name(value: str) -> str:
    return re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]', '', str(value or '')).lower()


def _scan_minimap(context):
    """Read the current integer coordinate from the configured mini-map crop."""
    region = context.config.get('minimap_region', [540, 0, 250, 90])
    if not isinstance(region, (list, tuple)) or len(region) != 4:
        raise ValueError('minimap_region 必须是 [x, y, width, height]')
    frame = context.capture.window(
        area='client', region=tuple(int(value) for value in region),
    )
    minimum = float(context.config.get('minimap_ocr_confidence', 0.45))
    passes = [context.ocr.recognize(frame, min_confidence=minimum)]
    for variant in ('minimap_scale', 'minimap_yellow'):
        passes.append(context.ocr.recognize(frame, min_confidence=minimum, preprocess=variant))
    patterns = (
        r'[（(\[]?(\d{1,3})\s*[,，、:：.]\s*(\d{1,3})[）)\]]?',
        r'[Xx][:：]?(\d{1,3}).{0,4}[Yy][:：]?(\d{1,3})',
    )
    all_lines = []
    for lines in passes:
        all_lines.extend(line for line in lines or [] if str(line.get('text', '')).strip())
        compact = re.sub(r'\s+', '', ' '.join(str(line.get('text', '')) for line in lines or []))
        match = next((re.search(pattern, compact) for pattern in patterns
                      if re.search(pattern, compact)), None)
        if match:
            values = [str(line.get('text', '')).strip() for line in lines or []]
            map_name = ''
            for value in values:
                candidate = re.sub(r'[（(\[]?\d{1,3}\s*[,，、:：.]\s*\d{1,3}[）)\]]?', '', value)
                if re.search(r'[\u4e00-\u9fff]', candidate) and len(candidate) > len(map_name):
                    map_name = candidate.strip(' -_·.()（）[]【】')
            position = (int(match.group(1)), int(match.group(2)))
            context.log(f'小地图定位：地图 {map_name or "未识别"}，坐标 {position}')
            return {'map': map_name, 'position': position}
    raw_text = ' '.join(str(line.get('text', '')) for line in all_lines)
    context.log(f'小地图 OCR：{raw_text or "<空>"}；未解析出坐标', 'warning')
    return None


def _navigate_to_npc(context, npc_name: str):
    """Walk to a configured NPC coordinate before pressing G.

    This first version intentionally handles a same-map coordinate route.  A
    cross-map route must be supplied through the existing task-link navigation
    or a future map-transition route; it is never guessed from an NPC name.
    """
    routes = context.config.get('navigation_routes', {})
    route = routes.get(npc_name) if isinstance(routes, dict) else None
    if not isinstance(route, dict):
        legacy = context.config.get('npc_routes', {})
        value = legacy.get(npc_name) if isinstance(legacy, dict) else None
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            route = {'map': '', 'waypoints': [[value[-2], value[-1]]], 'map_id': value[0]}
    if not isinstance(route, dict):
        raise RuntimeError(f'没有配置 {npc_name} 的 NPC 坐标，请先导入或配置 navigation_routes')
    waypoints = route.get('waypoints', [])
    if not isinstance(waypoints, list) or not waypoints:
        raise RuntimeError(f'{npc_name} 没有可执行的寻路点')
    target = waypoints[-1]
    if isinstance(target, dict):
        target_x, target_y = int(target['x']), int(target['y'])
    elif isinstance(target, (list, tuple)) and len(target) >= 2:
        target_x, target_y = int(target[0]), int(target[1])
    else:
        raise RuntimeError(f'{npc_name} 的寻路点格式无效')
    expected_map = str(route.get('map', '')).strip()
    context.log(f'前往 NPC {npc_name}：目标 ({target_x}, {target_y})'
                + (f'，地图 {expected_map}' if expected_map else ''))
    if context.dry_run:
        context.log('模拟运行：记录寻路目标，不发送移动按键')
        return
    _activate(context)
    tolerance = int(context.config.get('npc_arrival_tolerance', 1))
    max_attempts = int(context.config.get('npc_navigation_max_attempts', 60))
    seconds_per_coordinate = float(context.config.get('npc_seconds_per_coordinate', 0.18))
    for attempt in range(1, max_attempts + 1):
        state = _scan_minimap(context)
        if not state:
            _wait(context, 0.5)
            continue
        actual_map = _normalize_map_name(state.get('map', ''))
        wanted_map = _normalize_map_name(expected_map)
        if wanted_map and actual_map and actual_map != wanted_map:
            if SequenceMatcher(None, actual_map, wanted_map).ratio() < 0.75:
                raise RuntimeError(f'当前地图“{state.get("map", "") }”与 NPC 地图“{expected_map}”不一致')
        current_x, current_y = state['position']
        dx, dy = target_x - current_x, target_y - current_y
        context.log(f'前往 {npc_name}：第 {attempt}/{max_attempts} 次，当前位置 '
                    f'({current_x}, {current_y})，偏差 ({dx}, {dy})')
        if abs(dx) <= tolerance and abs(dy) <= tolerance:
            context.log(f'已到达 {npc_name} 附近，可开始 NPC 对话')
            return
        if abs(dx) >= abs(dy):
            direction, distance = ('right' if dx > 0 else 'left'), abs(dx)
        else:
            direction, distance = ('down' if dy > 0 else 'up'), abs(dy)
        duration = max(0.12, min(0.8, distance * seconds_per_coordinate))
        context.log(f'移动到 {npc_name}：{direction} {duration:.2f}s')
        context.keyboard.hold_combo(direction, duration=duration, mode='foreground')
        _wait(context, float(context.config.get('npc_navigation_scan_interval', 0.65)))
    raise RuntimeError(f'在 {max_attempts} 次检测内未到达 NPC {npc_name}')


def _run_gai_xia(context):
    """Run the active 垓下学艺 dialogue and start 静修.

    Public guides describe the flow as 大司马 → 霸王城 → 资深学艺导师，
    selecting the third option to领取静修凭证 and the first option to开始静修.
    """
    with context.step('垓下学艺：前往大司马'):
        _navigate_to_npc(context, '大司马')

    with context.step('垓下学艺：进入霸王城'):
        _talk_to_npc(
            context, '大司马',
            int(context.config.get('gai_xia_start_enter_count', 6)),
        )
        _wait(context, float(context.config.get('gai_xia_transition_wait', 4)))

    with context.step('垓下学艺：领取静修凭证'):
        # If the task panel exposes the mentor, use the game's own navigation;
        # otherwise keep the operator in control rather than guessing a route.
        if not _click_task_npc(context, ('资深学艺导师', '学艺导师')):
            context.log('任务栏未找到资深学艺导师；请人工走到导师附近后继续', 'warning')
        _wait(context, float(context.config.get('gai_xia_mentor_wait', 3)))
        _activate(context)
        if not context.dry_run:
            context.keyboard.press('g', mode='foreground')
        _wait(context, 0.6)
        _press(context, 'down', 2, 0.25)
        _press(context, 'enter', 1, 0.5)
        _press(context, 'enter', 2, 0.45)

    with context.step('垓下学艺：开始静修'):
        _activate(context)
        if not context.dry_run:
            context.keyboard.press('g', mode='foreground')
        _wait(context, 0.6)
        _press(context, 'enter', int(context.config.get('gai_xia_start_meditation_enter_count', 2)), 0.45)
        _wait(context, float(context.config.get('gai_xia_completion_wait', 5)))
        _, _, task_text = _task_snapshot(context)
        if _has_completion_marker(task_text):
            context.log('垓下学艺任务已显示完成')
        else:
            context.log('已执行开始静修；任务栏未出现完成文字，按已进入静修处理', 'warning')


def _run_mie_shu(context):
    """Enter 灭鼠靖仓, attack mice, pick up drops, and submit the task."""
    with context.step('灭鼠靖仓：前往太仓尉'):
        _navigate_to_npc(context, '太仓尉')

    with context.step('灭鼠靖仓：进入地鼠区域'):
        _talk_to_npc(
            context, '太仓尉',
            int(context.config.get('mie_shu_start_enter_count', 6)),
        )
        _wait(context, float(context.config.get('mie_shu_transition_wait', 4)))

    attack_key = str(context.config.get('mie_shu_attack_key', 'a'))
    target_key = str(context.config.get('mie_shu_target_key', 'tab'))
    pickup_key = str(context.config.get('mie_shu_pickup_key', 'c'))
    interval = float(context.config.get('mie_shu_attack_interval', 0.8))
    timeout = float(context.config.get('mie_shu_timeout_seconds', 600))
    started = time.monotonic()
    last_progress = None
    stagnant_cycles = 0
    dry_cycles = 0
    with context.step('灭鼠靖仓：击杀并拾取地鼠'):
        while time.monotonic() - started < timeout:
            dry_cycles += 1
            _, _, text = _task_snapshot(context)
            progress = _read_progress(text)
            if progress:
                current, total = progress
                context.log(f'灭鼠靖仓进度：{current}/{total}')
                if total > 0 and current >= total:
                    break
                if progress == last_progress:
                    stagnant_cycles += 1
                else:
                    stagnant_cycles = 0
                last_progress = progress
            elif _has_completion_marker(text):
                break
            if not context.dry_run:
                _activate(context)
                context.keyboard.press(target_key, mode='foreground')
                context.keyboard.press(attack_key, mode='foreground')
                context.keyboard.press(pickup_key, mode='foreground')
            if stagnant_cycles and stagnant_cycles % 10 == 0:
                context.log('灭鼠进度暂未变化，继续锁定目标、攻击并拾取', 'warning')
            if context.dry_run and dry_cycles >= int(context.config.get('dry_run_combat_cycles', 3)):
                context.log('模拟运行已执行若干轮攻击循环，跳过真实战斗等待', 'warning')
                break
            _wait(context, interval)
        else:
            raise RuntimeError('灭鼠靖仓在限定时间内没有完成，请人工确认战斗状态')

    with context.step('灭鼠靖仓：返回 NPC 提交'):
        if not _click_task_npc(context, ('太仓尉', '太仓卫')):
            context.log('任务栏未找到太仓尉；请人工走回提交 NPC 附近', 'warning')
        _wait(context, float(context.config.get('mie_shu_submit_wait', 3)))
        _talk_to_npc(
            context, '太仓尉交任务',
            int(context.config.get('mie_shu_submit_enter_count', 4)),
        )
        context.log('灭鼠靖仓提交流程已执行')


def _run_transport(context):
    keyword = str(context.config.get('transport_keyword', '运送'))
    max_cycles = int(context.config.get('transport_max_cycles', 20))
    empty_count = 0
    completed = 0
    for cycle in range(1, max_cycles + 1):
        with context.step(f'运送物资 {cycle}/{max_cycles}'):
            region, lines = _scan_task(context)
            full_text = ' '.join(str(item.get('text', '')) for item in lines)
            if keyword not in full_text:
                empty_count += 1
                context.log(f'未发现运送任务（连续 {empty_count} 次）')
                if completed and empty_count >= 2:
                    context.log('运送物资任务完成：任务栏卡片已消失')
                    return
                _wait(context, 1.5)
                continue
            empty_count = 0
            npc_item = next(
                (item for item in lines if re.search(r'(?:NPC|NＰC|NPC：|NPC:)', str(item.get('text', '')), re.I)),
                None,
            )
            if npc_item is None:
                raise RuntimeError('运送任务已出现，但没有识别到目的地 NPC')
            center = _box_center(npc_item.get('box'))
            if center is None:
                raise RuntimeError('无法定位任务栏 NPC 点击坐标')
            click_x = int(region[0]) + center[0]
            click_y = int(region[1]) + center[1]
            context.log(f'点击运送目的地 NPC：客户区 ({click_x}, {click_y})')
            if not context.dry_run:
                activation = context.windows.activate()
                if not activation.get('active'):
                    raise RuntimeError('游戏窗口激活失败')
                context.mouse.click(click_x, click_y, mode='foreground', coordinate_space='client')
                context.mouse.move(10, 10, coordinate_space='client')
            _wait(context, float(context.config.get('transport_navigation_wait', 8)))
            context.log('自动寻路等待结束，开始提交运送任务')
            if not context.dry_run:
                context.keyboard.press('g', mode='foreground')
            _wait(context, 0.8)
            for _ in range(int(context.config.get('transport_dialog_enter_count', 4))):
                if not context.dry_run:
                    context.keyboard.press('enter', mode='foreground')
                _wait(context, 0.35)
            completed += 1
            context.log(f'运送物资第 {completed} 轮已提交')
    raise RuntimeError('运送物资超过最大任务轮数')


def _answer_questions(context):
    region = context.config.get('answer_region', [30, 70, 470, 430])
    bank = context.config.get('question_bank', [])
    if not bank:
        bank = context.storage.read_json('question_bank.json', default=[])
    threshold = float(context.config.get('answer_match_threshold', 0.72))
    auto_threshold = float(context.config.get('answer_auto_click_confidence', 0.72))
    for number in range(1, int(context.config.get('answer_max_questions', 20)) + 1):
        with context.step(f'举孝廉答题 {number}'):
            frame = context.capture.window(area='client', region=tuple(region))
            items = context.ocr.recognize(frame, min_confidence=0.45, preprocess='task_scale')
            lines = [item for item in items if str(item.get('text', '')).strip()]
            options = parse_options([str(item.get('text', '')) for item in lines])
            question = ' '.join(str(item.get('text', '')) for item in lines
                                if not any(str(item.get('text', '')).startswith(option['letter']) for option in options))
            if not question or len(options) < 2:
                context.log('答题窗口内容尚未完整，继续等待', 'warning')
                _wait(context)
                continue
            answer_record = match_question(question, bank, threshold)
            answer = str(answer_record.get('ans', '')).upper() if answer_record else ''
            confidence = float(answer_record.get('_score', 0)) if answer_record else 0
            if not answer:
                answer, confidence = anti_fraud_answer(question, options)
            if not answer or confidence < auto_threshold:
                context.log(f'答案置信度不足，暂停点击：{question}', 'warning')
                _wait(context)
                continue
            target = next((option for option in options if option['letter'] == answer), None)
            if not target:
                continue
            context.log(f'自动答题：{question} → {answer}（{confidence:.3f}）')
            if not context.dry_run:
                context.windows.activate()
                context.mouse.click(int(region[0] + region[2] * 0.2),
                                    int(region[1] + region[3] * (0.4 + 0.12 * 'ABCD'.index(answer))),
                                    mode='foreground', coordinate_space='client')
            _wait(context)
            if any(marker in ' '.join(str(item.get('text', '')) for item in lines)
                   for marker in ('答题完成', '任务完成')):
                return
    raise RuntimeError('举孝廉答题超过最大题数')


def on_start(context):
    context.log('QQ三国日常任务独立插件已加载')
    sequence = _resolve_task_sequence(context.config)
    if str(context.config.get('task_mode', 'sequence')).strip().lower() in {'single', 'debug', 'one'}:
        context.log(f'单任务调试模式：只运行 {sequence[0]}')
    else:
        context.log(f'完整流程模式：共 {len(sequence)} 个任务')
    for task_name in sequence:
        if task_name == 'gai_xia_xue_yi':
            context.log('日常任务：进入垓下学艺')
            _run_gai_xia(context)
        elif task_name == 'mie_shu_jing_cang':
            context.log('日常任务：进入灭鼠靖仓')
            _run_mie_shu(context)
        elif task_name == 'ju_xiao_lian':
            context.log('日常任务：进入举孝廉答题')
            _answer_questions(context)
        elif task_name == 'transport':
            context.log('日常任务：进入运送物资')
            _run_transport(context)
        else:
            raise ValueError(f'不支持的任务类型：{task_name}')
    context.storage.write_json('progress.json', {'status': 'completed', 'task_sequence': sequence})
    context.log('QQ三国日常任务独立插件流程结束')


def on_stop(context):
    context.log('QQ三国日常任务独立插件已停止')
