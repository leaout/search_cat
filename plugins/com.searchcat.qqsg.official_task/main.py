import re


OPTIONAL_TEMPLATES = {
    'accept': 'images/accept.png',
    'continue': 'images/continue.png',
    'complete': 'images/complete.png',
}


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
    context.keyboard.press('g', mode=context.config.get('input_mode', 'foreground'))
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
    lines = context.ocr.recognize(
        frame,
        min_confidence=float(context.config.get('ocr_confidence', 0.55)),
    )
    for line in lines:
        line['client_center'] = [
            origin_x + int(line['center'][0]),
            origin_y + int(line['center'][1]),
        ]
    text = '\n'.join(line['text'] for line in lines)
    context.log(f'任务栏 OCR（{len(lines)} 行）：{text or "<空>"}')
    return text, lines


def _task_signature(text):
    return re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]', '', text)


def _find_target(text, lines, routes):
    for npc_name in sorted(routes, key=len, reverse=True):
        if npc_name in text:
            return npc_name, routes[npc_name], None
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


def _navigate_by_code(context, npc_name, route):
    if not isinstance(route, list) or len(route) != 3:
        raise ValueError(f'NPC {npc_name} 的路由必须是 [地图ID, X, Y]')
    map_id, mini_x, mini_y = (int(value) for value in route)
    code = f'/<DnpcWalkEx={map_id}|{mini_x * 100}|{mini_y * 100}>/123456</C04>'
    mode = context.config.get('input_mode', 'foreground')
    context.log(f'代码寻路：{npc_name} → 地图 {map_id}，坐标 ({mini_x}, {mini_y})')
    context.keyboard.press('esc', mode=mode)
    context.keyboard.press('f4', mode=mode)
    _wait(context, context.config.get('ui_wait', 0.5))
    _click(context, *_point(context.config, 'friend_tab_point'))
    _click(context, *_point(context.config, 'add_friend_point'))
    _wait(context, context.config.get('ui_wait', 0.5))
    _click(context, *_point(context.config, 'friend_input_point'))
    context.keyboard.hotkey('ctrl', 'a', mode=mode)
    context.keyboard.type_text(code, mode=mode)
    _wait(context, context.config.get('ui_wait', 0.5))
    _click(context, *_point(context.config, 'generated_link_point'))
    context.keyboard.press('esc', mode=mode)
    context.keyboard.press('esc', mode=mode)


def _navigate_to_target(context, npc_name, route, fallback_point):
    if route:
        _navigate_by_code(context, npc_name, route)
    elif fallback_point:
        context.log(f'NPC {npc_name} 不在路由库，点击 OCR 识别到的任务文字回退寻路', 'warning')
        _click(context, *fallback_point)
    else:
        raise RuntimeError('任务栏中没有识别到可寻路的 NPC')
    _wait(context, context.config.get('navigation_wait', 12))


def on_load(context):
    context.log('QQ三国官爵任务插件已加载')


def on_start(context):
    if not context.config.get('calibrated', False) and not context.dry_run:
        raise RuntimeError('尚未校准官爵任务坐标。请先在模拟模式调整坐标，再将 calibrated 改为 true。')
    if not context.config.get('calibrated', False):
        context.log('当前未标记为已校准，仅允许模拟运行。', 'warning')
    if not context.windows.is_alive():
        raise RuntimeError('绑定的游戏窗口已经失效')

    accept_point = _point(context.config, 'accept_point')
    continue_point = _point(context.config, 'continue_point')
    complete_point = _point(context.config, 'complete_point')

    context.log(
        f'开始官爵任务：OCR 状态循环，输入方式 '
        f"{context.config.get('input_mode', 'foreground')}，模拟运行 {context.dry_run}"
    )

    with context.step('向奋威中郎将领取任务'):
        _talk_to_nearest_npc(context)
        _click_dialog_action(context, 'accept', accept_point)
        _wait(context, context.config.get('dialog_wait', 1))

    routes = context.config.get('npc_routes', {})
    if not isinstance(routes, dict):
        raise ValueError('npc_routes 必须是 NPC 名称到 [地图ID, X, Y] 的对象')
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
            if not signature or task_keyword not in text:
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
            npc_name, route, fallback_point = _find_target(text, lines, routes)
            context.log(f'当前目标 NPC：{npc_name or "未识别"}；任务签名：{signature}')
            _navigate_to_target(context, npc_name, route, fallback_point)
            context.keyboard.press('~', mode=context.config.get('input_mode', 'foreground'))
            _talk_to_nearest_npc(context)
            is_return = any(word in text for word in ('领取俸禄', '回复奋威', '回报奋威', '奋威中郎将'))
            action = 'complete' if is_return else 'continue'
            point = complete_point if is_return else continue_point
            _click_dialog_action(context, action, point)
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
