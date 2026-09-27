"""QQSG level-1-to-50 starter automation plugin.

The plugin deliberately drives the game's own task-panel navigation instead of
guessing world coordinates.  It is a resumable task engine; client-specific
NPC routes and combat actions can be added to the configuration after observing
the first runs.
"""

import re
import time


DEFAULT_STAGES = [
    {'id': 'level_1_10', 'min_level': 1, 'max_level': 10, 'label': '新手与主线'},
    {'id': 'level_11_20', 'min_level': 11, 'max_level': 20, 'label': '主线任务'},
    {'id': 'level_21_30', 'min_level': 21, 'max_level': 30, 'label': '主线与区域任务'},
    {'id': 'level_31_40', 'min_level': 31, 'max_level': 40, 'label': '中期任务'},
    {'id': 'level_41_50', 'min_level': 41, 'max_level': 50, 'label': '后期任务'},
]
PROGRESS_RE = re.compile(r'(?<!\d)(\d{1,4})\s*/\s*(\d{1,4})(?!\d)')
NPC_RE = re.compile(r'(?:NPC|NＰC)\s*[:：]?\s*([^\s|/，,]+)', re.IGNORECASE)
LEVEL_PATTERNS = (
    re.compile(r'(?:LV|Lv|等级|级别)\s*[:：]?\s*(\d{1,2})', re.IGNORECASE),
    re.compile(r'(\d{1,2})\s*级'),
)
COMPLETION_MARKERS = ('任务完成', '已完成', '完成', '已领取奖励')


def _wait(context, seconds=0.8):
    context.sleep(0.1 if context.dry_run else max(0, float(seconds)))


def _activate(context):
    if context.dry_run:
        return
    result = context.windows.activate()
    if isinstance(result, dict) and not result.get('active', True):
        raise RuntimeError('游戏窗口激活失败')


def _press(context, key, count=1, delay=0.3):
    for _ in range(max(0, int(count))):
        if not context.dry_run:
            context.keyboard.press(str(key), mode='foreground')
        _wait(context, delay)


def _box_center(box):
    points = [point for point in (box or [])
              if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not points:
        return None
    return (
        round(sum(float(point[0]) for point in points) / len(points)),
        round(sum(float(point[1]) for point in points) / len(points)),
    )


def _scan_region(context, region, preprocess='task_scale'):
    frame = context.capture.window(
        area='client', region=tuple(int(value) for value in region),
    )
    return [
        item for item in context.ocr.recognize(
            frame,
            min_confidence=float(context.config.get('ocr_confidence', 0.4)),
            preprocess=preprocess,
        )
        if str(item.get('text', '')).strip()
    ]


def _scan_task(context):
    region = context.config.get('task_region', [520, 70, 270, 430])
    if not isinstance(region, (list, tuple)) or len(region) != 4:
        raise ValueError('task_region 必须是 [x, y, width, height]')
    lines = _scan_region(context, region)
    text = ' '.join(str(item.get('text', '')).strip() for item in lines)
    return [int(value) for value in region], lines, text


def _read_level(context):
    region = context.config.get('level_region', [0, 0, 220, 90])
    if not isinstance(region, (list, tuple)) or len(region) != 4:
        raise ValueError('level_region 必须是 [x, y, width, height]')
    try:
        lines = _scan_region(context, region, preprocess='task_scale')
    except Exception as error:
        context.log(f'等级 OCR 失败：{error}', 'warning')
        return None, ''
    raw = ' '.join(str(item.get('text', '')) for item in lines)
    level = _extract_level([str(item.get('text', '')) for item in lines])
    return level, raw


def _extract_level(values):
    """Extract a level only from explicit LV/等级/级 markers."""
    raw = ' '.join(str(value) for value in values)
    for pattern in LEVEL_PATTERNS:
        match = pattern.search(raw)
        if match:
            level = int(match.group(1))
            if 1 <= level <= 50:
                return level
    return None


def _stage_for_level(level, stages=None):
    value = max(1, int(level))
    candidates = stages or DEFAULT_STAGES
    normalized = sorted(
        (stage for stage in candidates if isinstance(stage, dict)),
        key=lambda item: int(item.get('min_level', 1)),
    )
    for stage in normalized:
        if int(stage.get('min_level', 1)) <= value <= int(stage.get('max_level', 50)):
            return stage
    return normalized[-1] if normalized else DEFAULT_STAGES[-1]


def _find_stage(stages, stage_id):
    return next((stage for stage in stages if str(stage.get('id')) == str(stage_id)), None)


def _task_signature(lines):
    return re.sub(r'\s+', '', '|'.join(str(item.get('text', '')) for item in lines)).strip()


def _has_completion_marker(text):
    return any(marker in str(text or '') for marker in COMPLETION_MARKERS)


def _read_progress(text):
    """Read a task counter such as ``消灭怪物 3/10`` when visible."""
    match = PROGRESS_RE.search(str(text or ''))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _find_task_target(lines, stage, config):
    """Select the most likely clickable NPC row from task OCR."""
    stage_names = stage.get('npc_keywords', []) if isinstance(stage, dict) else []
    configured_names = config.get('npc_keywords', [])
    names = [str(value) for value in list(stage_names or []) + list(configured_names or [])]
    task_keywords = [str(value) for value in config.get('task_keywords', [])]

    scored = []
    for item in lines:
        text = str(item.get('text', '')).strip()
        if not text or not _box_center(item.get('box')):
            continue
        score = 0
        if NPC_RE.search(text):
            score += 5
        score += sum(3 for name in names if name and name in text)
        score += sum(1 for keyword in task_keywords if keyword and keyword in text)
        if _has_completion_marker(text):
            score -= 5
        if score > 0:
            scored.append((score, item))
    if not scored:
        return None
    return max(scored, key=lambda value: value[0])[1]


def _click_task_target(context, region, item):
    center = _box_center(item.get('box'))
    if center is None:
        return False
    x, y = int(region[0]) + center[0], int(region[1]) + center[1]
    context.log(f'点击任务栏目标：客户区 ({x}, {y})，文字：{item.get("text", "")}')
    _activate(context)
    if not context.dry_run:
        context.mouse.click(x, y, mode='foreground', coordinate_space='client')
        # Keep the cursor away from the text so the next OCR frame is not covered.
        context.mouse.move(10, 10, coordinate_space='client')
    return True


def _dialogue(context):
    _activate(context)
    context.log('尝试与当前 NPC 对话：G + 连续回车')
    _press(context, 'g', 1, 0.6)
    _press(
        context,
        'enter',
        int(context.config.get('dialog_enter_count', 8)),
        float(context.config.get('dialog_key_interval', 0.3)),
    )


def _run_task_actions(context, progress):
    """Perform a configurable combat/collection cycle for an active task."""
    current, total = progress
    if total > 0 and current >= total:
        return
    keys = context.config.get('task_action_keys', ['a'])
    if not isinstance(keys, (list, tuple)) or not keys:
        context.log('当前任务有进度计数，但未配置 task_action_keys', 'warning')
        _wait(context, float(context.config.get('task_action_interval', 0.8)))
        return
    count = int(context.config.get('task_action_keys_per_cycle', 3))
    context.log(
        f'任务进行中：{current}/{total}，执行任务动作 '
        f'{list(keys)} × {count}',
    )
    _activate(context)
    for _ in range(max(1, count)):
        for key in keys:
            if not context.dry_run:
                context.keyboard.press(str(key), mode='foreground')
            _wait(context, 0.08)
    _wait(context, float(context.config.get('task_action_interval', 0.8)))


def _load_state(context):
    default = {
        'status': 'new',
        'current_level': int(context.config.get('start_level', 1)),
        'target_level': int(context.config.get('target_level', 50)),
        'current_stage': '',
        'completed_tasks': 0,
        'task_cycles': 0,
        'last_task_signature': '',
        'last_interaction_signature': '',
        'last_completion_signature': '',
        'last_error': '',
    }
    value = context.storage.read_json('leveling_state.json', default=default)
    if not isinstance(value, dict):
        return default
    result = dict(default)
    result.update(value)
    return result


def _save_state(context, state):
    state['updated_at'] = time.time()
    context.storage.write_json('leveling_state.json', state)
    context.debug.watch('leveling_state', state)


def _reset_state(context):
    state = _load_state(context)
    state.update({
        'status': 'new',
        'current_level': int(context.config.get('start_level', 1)),
        'target_level': int(context.config.get('target_level', 50)),
        'current_stage': '',
        'completed_tasks': 0,
        'task_cycles': 0,
        'last_task_signature': '',
        'last_interaction_signature': '',
        'last_completion_signature': '',
        'last_error': '',
    })
    _save_state(context, state)
    return state


def _recover(context, reason):
    context.log(f'任务没有明显进展，执行脱困：{reason}', 'warning')
    _activate(context)
    if not context.dry_run:
        context.keyboard.press('esc', mode='foreground')
        context.mouse.click(20, 20, mode='foreground', coordinate_space='client')
        context.mouse.move(10, 10, coordinate_space='client')
    _wait(context, float(context.config.get('recovery_interval', 1)))


def _run_stage(context, state, stage, stage_target):
    stage_id = str(stage.get('id', 'unknown'))
    label = str(stage.get('label', stage_id))
    state['current_stage'] = stage_id
    _save_state(context, state)
    context.log(f'进入等级阶段：{label}（目标 {stage_target} 级）')
    max_cycles = int(context.config.get('max_task_cycles', 0))
    stagnant = 0

    while int(state.get('current_level', 1)) < stage_target:
        state['task_cycles'] = int(state.get('task_cycles', 0)) + 1
        if max_cycles and state['task_cycles'] > max_cycles:
            raise RuntimeError(f'阶段 {stage_id} 超过 max_task_cycles，已保存断点')
        if context.dry_run and state['task_cycles'] > int(
                context.config.get('dry_run_max_cycles', 3)):
            raise RuntimeError(
                '模拟运行已完成设定的观察轮数；请查看日志后关闭模拟运行进行实测'
            )

        with context.step(f'{label}：任务循环 {state["task_cycles"]}'):
            level, level_text = _read_level(context)
            if level is not None:
                state['current_level'] = level
                context.log(f'当前等级：{level}（OCR：{level_text}）')
                if level >= stage_target:
                    _save_state(context, state)
                    return
            region, lines, task_text = _scan_task(context)
            signature = _task_signature(lines)
            context.log(f'任务栏 OCR（{len(lines)} 行）：{task_text or "<空>"}')
            if signature and signature != state.get('last_task_signature'):
                state['completed_tasks'] = int(state.get('completed_tasks', 0)) + 1
                state['last_task_signature'] = signature
                stagnant = 0
            else:
                stagnant += 1

            progress = _read_progress(task_text)
            completed = _has_completion_marker(task_text)
            target = _find_task_target(lines, stage, context.config)
            if completed:
                context.log('检测到任务完成标记，准备回 NPC 提交')
                should_interact = signature != state.get('last_completion_signature')
                if should_interact and target is not None:
                    _click_task_target(context, region, target)
                    _wait(context, float(context.config.get('auto_navigation_wait', 8)))
                    _dialogue(context)
                    state['last_completion_signature'] = signature
                    state['last_interaction_signature'] = signature
                elif should_interact:
                    context.log('已完成任务没有识别到 NPC 点击框，尝试当前位置对话', 'warning')
                    _dialogue(context)
                    state['last_completion_signature'] = signature
            elif progress is not None and progress[0] < progress[1]:
                # A counter means the character is already inside the task;
                # do not click the same NPC every scan.  Execute the configured
                # Ranger/action keys until the counter changes or completes.
                _run_task_actions(context, progress)
            elif target is not None and signature != state.get('last_interaction_signature'):
                context.log('发现新的待接任务，先前往任务 NPC')
                _click_task_target(context, region, target)
                _wait(context, float(context.config.get('auto_navigation_wait', 8)))
                _dialogue(context)
                state['last_interaction_signature'] = signature
                state['last_completion_signature'] = ''
            elif target is not None:
                context.log('任务 NPC 已处理，等待任务栏刷新状态')
            elif bool(context.config.get('probe_nearby_npc', True)):
                context.log('任务栏没有新的 NPC 目标，尝试当前位置附近 NPC 对话', 'warning')
                _dialogue(context)
            else:
                context.log('没有识别到新的任务 NPC，等待下一轮', 'warning')

            _save_state(context, state)
            if stagnant >= 3:
                _recover(context, '任务文本连续未变化或 OCR 未找到目标')
                state['last_interaction_signature'] = ''
                state['last_completion_signature'] = ''
                stagnant = 0
            else:
                _wait(context, float(context.config.get('task_scan_interval', 1.2)))


def on_start(context):
    context.log('QQ三国小号起号插件已加载')
    country = str(context.config.get('country', '蜀国')).strip()
    role_class = str(context.config.get('role_class', '游侠')).strip()
    if bool(context.config.get('client_first', True)):
        context.log(f'角色配置：{country} · {role_class}；任务 NPC 和路线以当前客户端 OCR 为准')
    else:
        context.log(f'角色配置：{country} · {role_class}；已关闭客户端优先模式', 'warning')
    state = _reset_state(context) if context.config.get('reset_progress', False) else _load_state(context)
    if not context.config.get('resume_progress', True) and state.get('status') in {'running', 'paused'}:
        state = _reset_state(context)
    stages = context.config.get('stage_plan', DEFAULT_STAGES)
    if not isinstance(stages, list) or not stages:
        stages = DEFAULT_STAGES
    target_level = min(50, max(1, int(context.config.get('target_level', 50))))
    state['target_level'] = target_level
    state['status'] = 'running'
    state['last_error'] = ''
    _save_state(context, state)

    try:
        mode = str(context.config.get('run_mode', 'full')).strip().lower()
        if mode == 'single_stage':
            stage = _find_stage(stages, context.config.get('single_stage', 'level_1_10'))
            if stage is None:
                raise ValueError('single_stage 不在 stage_plan 中')
            stage_target = min(target_level, int(stage.get('max_level', target_level)))
            # A selected stage is an explicit debug request.  Start its local
            # progress just before the stage so a previous level-50 completion
            # record cannot make the debug run exit without one OCR pass.
            state['current_level'] = int(stage.get('min_level', 1)) - 1
            _save_state(context, state)
            _run_stage(context, state, stage, stage_target)
        else:
            while int(state.get('current_level', 1)) < target_level:
                # Use the next level when selecting a stage so level 10 moves
                # into 11-20 instead of repeatedly selecting the 1-10 stage.
                next_level = int(state.get('current_level', 1)) + 1
                stage = _stage_for_level(next_level, stages)
                stage_target = min(target_level, int(stage.get('max_level', target_level)))
                _run_stage(context, state, stage, stage_target)
                if int(state.get('current_level', 1)) < stage_target:
                    # Without a reliable level OCR result the engine cannot
                    # claim that the stage ended, so keep the saved state clear.
                    raise RuntimeError('阶段未达到目标等级；请校准 level_region 后继续')
        state['status'] = 'completed'
        state['current_level'] = max(int(state.get('current_level', 1)), target_level)
        _save_state(context, state)
        context.log(f'小号起号流程完成：达到 {state["current_level"]} 级')
    except Exception as error:
        state['status'] = 'paused'
        state['last_error'] = str(error)
        _save_state(context, state)
        context.log(f'小号起号已暂停，断点已保存：{error}', 'error')
        raise


def on_stop(context):
    context.log('QQ三国小号起号插件已停止；下次启动默认读取 leveling_state.json 继续')
