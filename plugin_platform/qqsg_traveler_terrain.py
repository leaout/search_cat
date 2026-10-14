"""Read local traveler geometry and execute bounded feedback-driven input pulses."""

import math
import struct
from pathlib import Path

from core.terrain_navigation import plan_route
from plugin_platform.qqsg_data import QQSGPackage, find_installation


def _geometry(payload: bytes) -> list[tuple]:
    if len(payload) < 104:
        raise ValueError('行脚地形文件头不完整')
    header = struct.unpack_from('<26I', payload)
    offset, length = header[10:12]
    if header[:2] != (196608, 104) or offset < 104 or offset + length > len(payload) or length % 32:
        raise ValueError('行脚地形段格式无效')
    width, height = header[2] * header[4], header[3] * header[5]
    records = list(struct.iter_unpack('<8I', payload[offset:offset + length]))
    if not records or len(records) > 1000 or not 0 < width <= 10000 or not 0 < height <= 10000:
        raise ValueError('行脚地形尺寸或记录数异常')
    if any(r[3] > width or r[5] > width or r[4] > height or r[6] > height for r in records):
        raise ValueError('行脚地形坐标越界')
    return records


def load_terrain(config: dict) -> list[tuple]:
    map_id = config.get('map_id', 456)
    if type(map_id) is not int or not 456 <= map_id <= 461:
        raise ValueError('入口版本ID必须为456至461')
    directory = str(config.get('game_directory', '')).strip()
    installation = Path(directory) if directory else find_installation()
    if installation is None:
        raise RuntimeError('未找到QQ三国安装目录，请配置游戏目录')
    package = QQSGPackage(installation / 'data' / 'objects.pkg')
    models = [_geometry(package.read(f'map/84-{index}.map.srv')) for index in range(1, 7)]
    shapes = [sorted((r[1], *r[3:7]) for r in records) for records in models]
    if any(shape != shapes[0] for shape in shapes[1:]):
        raise RuntimeError('本机六张同名行脚地图布局不同，无法安全确认当前地形；停止')
    return models[map_id - 456]


def movement_settings(config: dict) -> dict:
    result = {}
    for name, default, low, high in (
        ('jump_x', 180, 20, 400), ('jump_up', 120, 20, 300), ('drop_limit', 250, 20, 500),
        ('seconds_per_coordinate', 0.28, 0.05, 1), ('move_pulse_max', 0.6, 0.1, 1),
        ('jump_lead_time', 0.1, 0, 0.3), ('jump_hold_time', 0.12, 0.03, 0.3),
        ('jump_follow_time', 0.25, 0.05, 0.8),
    ):
        value = config.get(name, default)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{name}超出允许范围')
        result[name] = float(value)
    return result


class TerrainPilot:
    """Advance one input pulse per fresh entry-map observation, never blind replay."""

    def __init__(self, context, records: list, target_raw: list):
        self.context = context
        self.records = records
        self.target_raw = target_raw
        self.settings = movement_settings(context.config)
        self.steps = None
        self.pending_transfer = None
        self.replans = 0
        self.active_climb = False
        self.pending_observation = None
        self.best_distance = float('inf')
        self.stalled = 0
        self.step_token = None

    def plan(self, position: list) -> dict:
        settings = self.settings
        route = plan_route(self.records, [(v + 0.5) * 100 for v in position], self.target_raw,
                           scale=100, jump_x=settings['jump_x'], jump_up=settings['jump_up'],
                           drop=settings['drop_limit'], allow_climb=True, snap=150)
        # The shared planner's historical default map name is not traveler metadata.
        route['map'] = '行脚商行馆入口'
        return route

    def _replan(self, position: list, reason: str) -> None:
        if self.steps is not None:
            self.replans += 1
        if self.replans > 8:
            raise RuntimeError('地形落点偏离/卡住已纠偏8次，停止，不继续盲跳')
        try:
            route = self.plan(position)
        except ValueError as error:
            raise RuntimeError(f'无法从实时坐标 {position} 规划到出口：{error}') from error
        self.steps = list(route['steps'])
        self.pending_transfer = None
        self.pending_observation = None
        self.active_climb = False
        self.stalled = 0
        self.best_distance = float('inf')
        self.step_token = None
        self.context.log(f'行脚地形规划：{position} → {self.target_raw}，'
                         f'{len(self.steps)}步，重规划 {self.replans}/8；{reason}')

    @staticmethod
    def _cell(point: list) -> list:
        return [math.floor(value) for value in point]

    def _walk(self, dx: float) -> None:
        if abs(dx) < 0.05:
            return
        duration = min(self.settings['move_pulse_max'],
                       max(0.10, abs(dx) * self.settings['seconds_per_coordinate']))
        self.context.keyboard.hold_combo('right' if dx > 0 else 'left', duration=duration)

    def drive(self, position: list) -> None:
        if self.context.dry_run:
            return
        if self.steps is None:
            self._replan(position, '从当前坐标开始')
        if self.pending_transfer is not None:
            expected = self._cell(self.pending_transfer['to'])
            if position == expected:
                self.steps.pop(0)
                self.pending_transfer = None
                self.pending_observation = None
            else:
                if self.pending_observation != position:
                    self.pending_observation = list(position)
                    return
                self._replan(position, f'转移实际落点 {position}，预期 {expected}')
        # A route may contain very short joins within the same observable cell.
        while self.steps:
            step = self.steps[0]
            target_cell = self._cell(step['to'])
            if position == target_cell:
                self.steps.pop(0)
                continue
            break
        if not self.steps:
            return
        step = self.steps[0]
        token = (step['action'], tuple(step['to']))
        if token != self.step_token:
            self.active_climb = False
            self.step_token = token
            self.best_distance = float('inf')
            self.stalled = 0
        distance = math.dist(position, self._cell(step['to']))
        self.stalled = self.stalled + 1 if distance >= self.best_distance - 0.05 else 0
        self.best_distance = min(self.best_distance, distance)
        if self.stalled >= 6:
            self._replan(position, '连续6次没有靠近路点')
            return
        action = step['action']
        self.context.log(f'地形反馈：{position}，{action} {step["from"]} → {step["to"]}')
        if action == 'walk':
            # Falling to another level invalidates the route immediately. Do not
            # spend six more scans walking at the X of an unreachable platform.
            start, end = step['from'], step['to']
            fraction = ((position[0] + 0.5 - start[0]) / (end[0] - start[0])
                        if abs(end[0] - start[0]) > 1e-6 else 0)
            fraction = max(0, min(1, fraction))
            expected_y = start[1] + fraction * (end[1] - start[1])
            if abs(position[1] + 0.5 - expected_y) > 1.25:
                self._replan(position, f'已离开行走平台，实际高度 {position[1]}，平台高度 {expected_y:.2f}')
                return
            dx = step['to'][0] - (position[0] + 0.5)
            if abs(dx) < 0.05:
                self._replan(position, '行走端点高度偏离')
            else:
                self._walk(dx)
            return
        if action not in ('jump', 'drop', 'climb'):
            raise RuntimeError(f'未知地形动作：{action}')
        # Reach the source cell before attempting a platform connection.
        source = self._cell(step['from'])
        if action == 'climb' and self.active_climb:
            if abs(position[0] - source[0]) > 1:
                self._replan(position, '攀爬偏离连接位置')
                return
        elif position != source:
            if abs(position[1] - source[1]) > 1:
                self._replan(position, '不在转移起点平台')
            else:
                self._walk(step['from'][0] - (position[0] + 0.5))
            return
        dx = step['to'][0] - step['from'][0]
        if action == 'jump':
            if abs(dx) > 1e-6:
                self.context.keyboard.directional_jump(
                    'right' if dx > 0 else 'left', lead_time=self.settings['jump_lead_time'],
                    jump_hold=self.settings['jump_hold_time'], follow_time=self.settings['jump_follow_time'])
            else:
                self.context.keyboard.hold_combo('space', duration=self.settings['jump_hold_time'])
            self.pending_transfer = step
        elif action == 'drop':
            if abs(dx) > 1e-6:
                self._walk(dx)
            else:
                self.context.keyboard.hold_combo('down', 'space', duration=0.15)
            self.pending_transfer = step
        else:
            self.active_climb = True
            self.context.keyboard.hold_combo('up' if step['to'][1] < step['from'][1] else 'down',
                                             duration=min(0.3, self.settings['move_pulse_max']))
