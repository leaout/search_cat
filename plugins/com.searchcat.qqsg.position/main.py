"""Read each bound client's current location, optionally navigate once."""

import time
from pathlib import Path

from plugin_platform.qqsg_code_navigation import navigate_and_wait
from plugin_platform.qqsg_data import MAP_DATA_PATH, QQSGPackage, normalize_map_name, parse_map_catalog


def on_start(context):
    """Publish fresh observations without reusing failed OCR readings."""
    directory = Path(context.config.get('game_directory', r'D:\WeGameApps\QQ三国'))
    catalog = parse_map_catalog(QQSGPackage(directory / 'data' / 'objects.pkg').read(MAP_DATA_PATH))
    names = list(dict.fromkeys(item['name'] for item in catalog.values()))
    interval = float(context.config.get('interval', 3))
    if not 1 <= interval <= 60:
        raise ValueError('读取间隔必须在 1～60 秒之间')
    window = context.windows.current()
    identity = str(window.get('hwnd', window.get('id', window['pid'])))
    if not identity.isdecimal():
        identity = str(window['pid'])
    context.log(f'位置读取：PID {window["pid"]}，已加载 {len(names)} 个地图名称')
    if context.config.get('navigate', False):
        target = catalog.get(normalize_map_name(str(context.config.get('target_map', ''))))
        if target is None:
            raise ValueError('目标地图不在客户端地图目录中')
        x, y = context.config.get('target_x', 6), context.config.get('target_y', 4)
        if any(type(value) is not int or not 0 <= value <= 999 for value in (x, y)):
            raise ValueError('目标必须是小地图整数坐标（0～999）')
        navigate_and_wait(context, target['id'], x * 100, y * 100, target['name'])
    if context.dry_run:
        context.log('模拟运行完成：实际运行将持续 OCR 读取；本次未读取游戏坐标')
        return
    previous = None
    while context.windows.is_alive():
        observed = context.windows.read_navigation_state(names, diagnostics=True)
        valid = isinstance(observed, dict) and 'map_name' in observed and 'position' in observed
        record = {
            'window': window, 'updated_at': time.time(), 'valid': valid,
            'map_name': observed['map_name'] if valid else None,
            'position': observed['position'] if valid else None,
            'diagnostic': observed.get('diagnostic') if isinstance(observed, dict) else None,
        }
        context.storage.write_json(f'positions/{identity}.json', record)
        context.debug.watch('当前位置', record)
        status = (record['map_name'], tuple(record['position'] or []), valid)
        if status != previous:
            context.log(f'当前位置：{record["map_name"]} {record["position"]}' if valid
                        else '当前位置未识别：已清空本次坐标，不沿用旧位置')
            previous = status
        context.sleep(interval)
    context.log('绑定游戏窗口已关闭，结束位置读取')
