"""One bounded pass through six local exit candidates; no purchase/chat input."""

import json
import math
import time
from pathlib import Path

from plugin_platform.qqsg_traveler_terrain import TerrainPilot, load_terrain, movement_settings


ENTRY_MAP = '行脚商行馆入口'
DESTINATION = '行脚商行馆'
NAMES = [ENTRY_MAP, DESTINATION]


def _state(context) -> dict | None:
    observed = context.windows.read_navigation_state(NAMES, diagnostics=True)
    if isinstance(observed, dict) and 'diagnostic' in observed:
        context.log(f'小地图OCR诊断：{observed["diagnostic"]}', 'warning')
    if not isinstance(observed, dict) or observed.get('map_name') not in NAMES:
        return None
    position = observed.get('position')
    if not isinstance(position, list) or len(position) != 2 or any(
        type(value) is not int or not 0 <= value <= 999 for value in position
    ):
        return None
    return observed


def _near(position: list, target: list, radius: float) -> bool:
    return math.dist(position, target) <= radius


def _confirm_start(context, interval: float) -> dict:
    """Require consecutive known observations, tolerate bounded transient OCR misses."""
    previous = None
    observations = []
    for index in range(6):
        observed = _state(context)
        observations.append(observed)
        context.log(f'起点检测 {index + 1}/6：{observed or "地图名或坐标未识别（不发送移动按键）"}')
        if previous and observed and previous['map_name'] == observed['map_name']:
            if observed['map_name'] == DESTINATION or _near(previous['position'], observed['position'], 1):
                return observed
        previous = observed
        if index < 5:
            context.sleep(interval)
    raise RuntimeError(f'6次检测未连续确认行脚起点；实际读数：{observations}。'
                       '请关闭全景地图并停在起点；None表示地图名/坐标识别失败，不代表角色在移动')


def _settings(config: dict) -> tuple:
    map_id = config.get('map_id', 456)
    if type(map_id) is not int or not 456 <= map_id <= 461:
        raise ValueError('行脚入口版本ID只能是456..461')
    values = []
    for name, default, lower, upper in (
        ('attempt_timeout', 300, 10, 600), ('scan_interval', 0.7, 0.2, 5),
        ('arrival_radius', 1.2, 0.5, 2),
    ):
        value = config.get(name, default)
        if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f'{name}超出允许范围')
        values.append(float(value))
    key = config.get('trigger_key', 'up')
    if key not in ('up', ''):
        raise ValueError('出口触发按键只允许up或空字符串')
    return map_id, *values, key


def on_start(context) -> None:
    mode = context.config.get('mode', 'navigate')
    target_exit = context.config.get('target_exit', 0)
    if mode not in ('navigate', 'preview') or type(target_exit) is not int or not 0 <= target_exit <= 6:
        raise ValueError('模式必须为navigate或preview；目标出口必须为0～6（0表示全部）')
    map_id, timeout, interval, radius, trigger_key = _settings(context.config)
    movement_settings(context.config)
    data = json.loads(Path(__file__).with_name('exits.json').read_text(encoding='utf-8'))
    exits = data['maps'][str(map_id)]
    if len(exits) != 6 or any(len(point) != 2 or any(type(value) is not int or value < 0
                                                    for value in point) for point in exits):
        raise ValueError('出口数据异常，拒绝移动')
    terrain = load_terrain(context.config)
    selected = [(index, raw) for index, raw in enumerate(exits, 1)
                if target_exit == 0 or index == target_exit]
    if mode == 'preview':
        position = [context.config.get('preview_x', 8), context.config.get('preview_y', 21)]
        if any(type(value) is not int or not 0 <= value <= 999 for value in position):
            raise ValueError('预览起点必须为小地图整数坐标0～999')
        routes = []
        for index, raw in selected:
            try:
                route = TerrainPilot(context, terrain, raw).plan(position)
                routes.append({'exit': index, 'raw': raw, 'route': route})
                context.log(f'出口 {index} 路线预览：{len(route["steps"])}步；'
                            f'动作 {[step["action"] for step in route["steps"]]}')
            except ValueError as error:
                routes.append({'exit': index, 'raw': raw, 'error': str(error)})
                context.log(f'出口 {index} 暂无连通路线：{error}', 'warning')
        context.storage.write_json('routes/preview.json', {
            'map_id': map_id, 'start': position, 'updated_at': time.time(),
            'experimental': True, 'routes': routes,
        })
        context.log('路线预览已保存：routes/preview.json；预览起点为配置坐标，未读取游戏位置')
        return
    context.log(f'行脚六出口测试：入口版本 {map_id}，最多一轮；本机六版本地形已核对一致')
    context.log('使用本地地形+方向键/跳跃/攀爬；不调用好友框代码寻路或游戏自动寻路')
    if context.dry_run:
        for index, point in selected:
            context.log(f'模拟运行：出口 {index}/6 原始坐标 {point}；不发送输入，不记成功')
        return
    record = {'map_id': map_id, 'status': 'starting', 'attempts': [], 'last_observed': None}

    def save(status: str, **details) -> None:
        record.update(status=status, updated_at=time.time(), **details)
        context.storage.write_json('progress.json', record)

    try:
        second = _confirm_start(context, interval)
        if second['map_name'] == DESTINATION:
            save('completed', reason='两次实时检测确认已在行脚商行馆', last_observed=second)
            return
        spawn = second['position'][:]
        save('running', spawn=spawn, last_observed=second)
        for index, raw in selected:
            with context.step(f'尝试行脚出口 {index}/6'):
                target = [value / 100 for value in raw]
                save('running', current_exit=index, target_raw=raw)
                context.log(f'尝试出口 {index}/6：{raw}，回起点后尝试下一个')
                pilot = TerrainPilot(context, terrain, raw)
                departed = False
                triggered = False
                reset_count = success_count = unknown_count = 0
                outcome = 'timeout'
                deadline = time.monotonic() + timeout
                for _ in range(math.ceil(timeout / interval)):
                    if time.monotonic() >= deadline:
                        break
                    if not context.windows.is_alive():
                        raise RuntimeError('游戏窗口已关闭')
                    observed = _state(context)
                    record['last_observed'] = observed
                    if observed is None:
                        unknown_count += 1
                        reset_count = success_count = 0
                        if unknown_count >= 5:
                            raise RuntimeError('连续5次未识别到小地图；无法确认过图或回起点，停止')
                    else:
                        unknown_count = 0
                        success_count = success_count + 1 if observed['map_name'] == DESTINATION else 0
                        if observed['map_name'] == DESTINATION:
                            reset_count = 0
                        if success_count >= 2:
                            record['attempts'].append({'exit': index, 'raw': raw, 'result': 'success'})
                            save('completed', reason='两次实时检测确认进入行脚商行馆')
                            context.log(f'出口 {index} 成功：已进入行脚商行馆')
                            return
                        if observed['map_name'] == ENTRY_MAP:
                            position = observed['position']
                            departed = departed or not _near(position, spawn, 1)
                            reset_count = reset_count + 1 if departed and _near(position, spawn, 1) else 0
                            if reset_count >= 2:
                                outcome = 'returned_to_start'
                                break
                            if not triggered and _near(position, target, radius):
                                triggered = True
                                context.log(f'已接近出口 {index}，等待过图/回起点反馈')
                                if trigger_key:
                                    context.keyboard.press(trigger_key)
                            if reset_count == 0 and not triggered:
                                pilot.drive(position)
                    save('running', departed=departed, exit_triggered=triggered)
                    context.sleep(interval)
                # Without a fresh known entry state, do not launch another route.
                last = record['last_observed']
                if not last or last['map_name'] != ENTRY_MAP:
                    raise RuntimeError('单次过图读数或未知状态未确认，停止，不尝试下一出口')
                record['attempts'].append({'exit': index, 'raw': raw, 'result': outcome})
                save('running')
                context.log(f'出口 {index}：{"已返回起点" if outcome == "returned_to_start" else "等待超时"}')
        raise RuntimeError(('六个出口' if target_exit == 0 else f'指定出口 {target_exit}') +
                           '已尝试一轮，未确认进入行馆；请检查地形移动反馈和触发按键')
    except Exception as error:
        try:
            save('needs_attention', reason=str(error))
        except (RuntimeError, OSError) as save_error:
            context.log(f'执行状态保存失败：{save_error}', 'warning')
        raise
