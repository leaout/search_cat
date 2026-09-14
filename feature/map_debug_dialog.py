"""Interactive viewer for the experimentally decoded QQSG terrain."""
import json
import struct
import time
from pathlib import Path

import cv2
import win32api
import win32con
import win32gui
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QGraphicsItem,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout,
)

from plugin_platform.qqsg_data import QQSGPackage
from core.ocr import Ocr
from core.qqsg_npc_capture import detect_navigation_map, parse_npc_rows
from core.terrain_navigation import plan_route


class TerrainView(QGraphicsView):
    point_picked = pyqtSignal(float, float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._picking = False

    def start_pick(self):
        """Switch the next left click from panning to coordinate picking."""
        self._picking = True
        self.setDragMode(QGraphicsView.NoDrag)
        self.setCursor(Qt.CrossCursor)

    def cancel_pick(self):
        self._picking = False
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.unsetCursor()

    def mousePressEvent(self, event):
        if self._picking and event.button() == Qt.LeftButton:
            point = self.mapToScene(event.pos())
            self.cancel_pick()
            self.point_picked.emit(point.x(), point.y())
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        current = self.transform().m11()
        if 0.02 < current * factor < 8:
            self.scale(factor, factor)
        event.accept()


class MapDebugDialog(QDialog):
    plan_selected = pyqtSignal(dict)
    npcs_collected = pyqtSignal(list)
    MAP_NAME = '成都.子城'
    MAP_ID = 23

    def __init__(self, package: Path, npc_file: Path | None = None, captured_npcs=None,
                 map_catalog=None,
                 window_handler=None, hwnd: int | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('地图调试 · 成都·子城')
        self.resize(1120, 760)
        self.setMinimumSize(820, 540)
        self.setStyleSheet(
            'QDialog {background:#f7f8fa;} QPushButton {padding:4px 10px;}'
            'QComboBox, QDoubleSpinBox {min-height:24px;}'
        )
        self.markers = {}
        self.marker_positions = {}
        self.npc_items = []
        self.pending_marker = None
        self.route_items = []
        self.route_plan = None
        self.window_handler = window_handler
        self.hwnd = int(hwnd) if hwnd else None
        self._ocr = None
        self.map_catalog = map_catalog or {
            '成都子城': {'name': self.MAP_NAME, 'id': self.MAP_ID},
        }
        legacy_npcs = self._load_npc_locations(npc_file)
        captured_values = captured_npcs.values() if isinstance(captured_npcs, dict) else (captured_npcs or [])
        npc_by_name = {
            (str(item.get('map', '')).replace('·', '.'), str(item.get('name', ''))): item
            for item in legacy_npcs
        }
        for item in captured_values:
            record = dict(item)
            name = str(record.get('name', '')).strip()
            map_name = str(record.get('map', self.MAP_NAME)).replace('·', '.')
            if not name or map_name != self.MAP_NAME:
                continue
            record['name'] = name
            record['map'] = map_name
            npc_by_name[(map_name, name)] = record
        self.npc_locations = list(npc_by_name.values())

        layout = QVBoxLayout(self)
        hint = QLabel(
            '成都·子城 / 15-1.map · 蓝：水平线  橙：斜线  绿：竖线\n'
            '滚轮缩放，拖动平移；点击“点选人物/目标”后，直接在地图中单击位置。'
        )
        layout.addWidget(hint)

        coordinate_controls = QHBoxLayout()
        self.x = QDoubleSpinBox()
        self.y = QDoubleSpinBox()
        self.factor = QDoubleSpinBox()
        for widget in (self.x, self.y):
            widget.setRange(0, 9999)
            widget.setDecimals(2)
        self.factor.setRange(0.01, 1000)
        self.factor.setValue(100)
        for title, widget in [('地图 X', self.x), ('Y', self.y), ('坐标倍率', self.factor)]:
            coordinate_controls.addWidget(QLabel(title))
            coordinate_controls.addWidget(widget)
        for title, marker, color in (
            ('按坐标标记人物', 'player', '#d32f2f'),
            ('按坐标标记目标', 'target', '#7b1fa2'),
        ):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, n=marker, c=color: self.mark(n, c))
            coordinate_controls.addWidget(button)
        coordinate_controls.addStretch(1)
        layout.addLayout(coordinate_controls)

        action_controls = QHBoxLayout()
        for title, marker in [('点选人物', 'player'), ('点选目标', 'target')]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, n=marker: self.begin_pick(n))
            action_controls.addWidget(button)
        self.show_npcs = QCheckBox(f'显示 NPC（{len(self.npc_locations)}）')
        self.show_npcs.setText('显示旧网络 NPC（不作寻路依据）')
        self.show_npcs.setChecked(False)
        self.show_npcs.toggled.connect(self.refresh_overlays)
        action_controls.addWidget(self.show_npcs)
        self.npc_combo = QComboBox()
        self.npc_combo.setMinimumWidth(190)
        for npc in self.npc_locations:
            self.npc_combo.addItem(f'{npc["name"]}  ({npc["x"]}, {npc["y"]})', npc)
        action_controls.addWidget(self.npc_combo)
        locate_button = QPushButton('定位 NPC')
        locate_button.clicked.connect(self.locate_npc)
        action_controls.addWidget(locate_button)
        capture_button = QPushButton('采集寻路窗口 NPC')
        capture_button.setToolTip('框选完整自动寻路窗口；程序激活列表后用鼠标滚轮逐行采集。')
        capture_button.setEnabled(bool(self.window_handler and self.hwnd))
        capture_button.clicked.connect(self.capture_navigation_npcs)
        action_controls.addWidget(capture_button)
        fit_button = QPushButton('适应窗口')
        fit_button.clicked.connect(self.fit)
        action_controls.addWidget(fit_button)
        action_controls.addStretch(1)
        layout.addLayout(action_controls)

        route_controls = QHBoxLayout()
        self.jump_x, self.jump_up = QDoubleSpinBox(), QDoubleSpinBox()
        for title, widget, value in [('试验跳远（待实测）', self.jump_x, 180),
                                     ('试验跳高（待实测）', self.jump_up, 120)]:
            widget.setRange(0, 1000)
            widget.setValue(value)
            widget.setToolTip('单位为地形原始单位。默认值是实验估计，非客户端解析值，也非一级角色实测能力。')
            widget.valueChanged.connect(self.invalidate_plan)
            route_controls.addWidget(QLabel(title))
            route_controls.addWidget(widget)
        self.climb_enabled = QCheckBox('尝试竖线攀爬（未验证）')
        self.climb_enabled.toggled.connect(self.invalidate_plan)
        route_controls.addWidget(self.climb_enabled)
        plan_button = QPushButton('规划路线')
        plan_button.clicked.connect(self.build_plan)
        route_controls.addWidget(plan_button)
        self.test_button = QPushButton('载入寻路测试')
        self.test_button.setEnabled(False)
        self.test_button.clicked.connect(self.select_plan)
        route_controls.addWidget(self.test_button)
        layout.addLayout(route_controls)

        self.scene = QGraphicsScene(self)
        self.view = TerrainView(self.scene)
        self.view.setBackgroundBrush(QColor('white'))
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.point_picked.connect(self.on_point_picked)
        layout.addWidget(self.view, 1)
        self.status = QLabel('NPC 坐标已叠加。点选位置只用于校准，不会向游戏发送操作。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        data = QQSGPackage(package).read('map/15-1.map.srv')
        if len(data) < 104:
            raise ValueError('SRV 文件头不完整')
        header = struct.unpack_from('<26I', data)
        offset, length = header[10:12]
        if offset < 104 or offset + length > len(data) or length % 32:
            raise ValueError('不支持的 SRV 地形段格式')
        self.width, self.height = header[2] * header[4], header[3] * header[5]
        if not 0 < self.width <= 100000 or not 0 < self.height <= 100000:
            raise ValueError('地图尺寸异常')
        self.scene.setSceneRect(-80, -80, self.width + 160, self.height + 160)
        self.scene.addRect(0, 0, self.width, self.height, QPen(QColor('#cbd5e1'), 2))
        colors = {2: '#1565c0', 4: '#e65100', 8: '#2e7d32'}
        self.terrain_records = list(struct.iter_unpack('<8I', data[offset:offset + length]))
        records = self.terrain_records
        for ident, kind, reserved, x1, y1, x2, y2, links in records:
            line = self.scene.addLine(x1, y1, x2, y2, QPen(QColor(colors.get(kind, '#666666')), 5))
            line.setToolTip(
                f'线段 {ident} · 类型 {kind}\n({x1}, {y1}) → ({x2}, {y2})\n'
                f'候选连接：{links & 65535}, {links >> 16}'
            )
        self.factor.valueChanged.connect(self.refresh_overlays)
        self.factor.valueChanged.connect(self.invalidate_plan)
        self.refresh_overlays()

    def invalidate_plan(self):
        self.route_plan = None
        if hasattr(self, 'test_button'):
            self.test_button.setEnabled(False)
        for item in self.route_items:
            self.scene.removeItem(item)
        self.route_items.clear()

    def build_plan(self):
        self.invalidate_plan()
        if not all(name in self.marker_positions for name in ('player', 'target')):
            QMessageBox.information(self, '先标记位置', '请先点选人物和目标。人物位置需对应游戏当前坐标。')
            return
        scale = self.factor.value()
        start = [v * scale for v in self.marker_positions['player'][:2]]
        target = [v * scale for v in self.marker_positions['target'][:2]]
        try:
            self.route_plan = plan_route(self.terrain_records, start, target, scale,
                                         self.jump_x.value(), self.jump_up.value(),
                                         allow_climb=self.climb_enabled.isChecked())
        except ValueError as error:
            QMessageBox.warning(self, '规划失败', str(error))
            return
        self.route_plan['terrain_records'] = [list(record) for record in self.terrain_records]
        self.route_plan['planner'] = {
            'jump_x': self.jump_x.value(),
            'jump_up': self.jump_up.value(),
            'allow_climb': self.climb_enabled.isChecked(),
        }
        names = {'walk': '行走', 'jump': '跳跃', 'climb': '攀爬', 'drop': '下落'}
        for index, step in enumerate(self.route_plan['steps'], 1):
            a, b = step['from'], step['to']
            line = self.scene.addLine(a[0]*scale, a[1]*scale, b[0]*scale, b[1]*scale,
                                     QPen(QColor('#dc2626'), 7, Qt.DashLine))
            line.setZValue(15)
            line.setToolTip(f'{index}. {names[step["action"]]}：{a} → {b}')
            self.route_items.append(line)
        self.test_button.setEnabled(True)
        self.status.setText('实验路线：' + ' → '.join(names[s['action']] for s in self.route_plan['steps'])
                            + '。红色虚线可悬停查看步骤；跳跃碰撞、倍率及竖线用途仍需实测。')

    def select_plan(self):
        if self.route_plan:
            self.plan_selected.emit(self.route_plan)
            self.accept()

    def terrain_model(self) -> dict:
        """Return reusable geometry; it contains no player start or task target."""
        return {
            'map': self.MAP_NAME,
            'scale': float(self.factor.value()),
            'terrain_records': [list(record) for record in self.terrain_records],
            'planner': {
                'jump_x': float(self.jump_x.value()),
                'jump_up': float(self.jump_up.value()),
                'allow_climb': self.climb_enabled.isChecked(),
            },
        }

    @classmethod
    def _load_npc_locations(cls, npc_file: Path | None) -> list[dict]:
        if not npc_file or not npc_file.is_file():
            return []
        with npc_file.open('r', encoding='utf-8') as handle:
            records = json.load(handle)
        return [record for record in records if str(record.get('map', '')).replace('·', '.') == cls.MAP_NAME]

    def showEvent(self, event):
        super().showEvent(event)
        self.fit()

    def fit(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def begin_pick(self, name: str):
        self.pending_marker = name
        self.view.start_pick()
        marker_name = '人物' if name == 'player' else '目标'
        self.status.setText(f'正在点选{marker_name}：请直接单击地图中的位置，按 Esc 可取消。')

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.pending_marker:
            self.pending_marker = None
            self.view.cancel_pick()
            self.status.setText('已取消点选。')
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        """Release transient OpenCV/graphics state without touching saved models."""
        self.pending_marker = None
        if hasattr(self, 'view'):
            self.view.cancel_pick()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass
        super().closeEvent(event)

    def on_point_picked(self, raw_x: float, raw_y: float):
        if not self.pending_marker:
            return
        name = self.pending_marker
        self.pending_marker = None
        factor = self.factor.value()
        map_x, map_y = raw_x / factor, raw_y / factor
        self.x.setValue(map_x)
        self.y.setValue(map_y)
        self.mark_at(name, '#d32f2f' if name == 'player' else '#7b1fa2', map_x, map_y)

    def mark(self, name: str, color: str):
        self.mark_at(name, color, self.x.value(), self.y.value())

    def mark_at(self, name: str, color: str, map_x: float, map_y: float):
        self.invalidate_plan()
        raw_x, raw_y = map_x * self.factor.value(), map_y * self.factor.value()
        if not 0 <= raw_x <= self.width or not 0 <= raw_y <= self.height:
            QMessageBox.warning(self, '坐标超出地图', '请检查坐标或倍率。')
            return
        self.marker_positions[name] = (map_x, map_y, color)
        self._draw_marker(name, map_x, map_y, color)
        marker_name = '人物' if name == 'player' else '目标'
        self.status.setText(
            f'已标记{marker_name}：地图坐标 ({map_x:.2f}, {map_y:.2f})，'
            f'原始坐标 ({raw_x:.0f}, {raw_y:.0f})。'
        )

    def _draw_marker(self, name: str, map_x: float, map_y: float, color: str):
        for item in self.markers.pop(name, []):
            self.scene.removeItem(item)
        raw_x, raw_y = map_x * self.factor.value(), map_y * self.factor.value()
        dot = self.scene.addEllipse(-7, -7, 14, 14, QPen(QColor('white'), 2), QBrush(QColor(color)))
        dot.setPos(raw_x, raw_y)
        dot.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        marker_name = '人物' if name == 'player' else '目标'
        label = self.scene.addSimpleText(f'{marker_name} ({map_x:.2f}, {map_y:.2f})')
        label.setBrush(QBrush(QColor(color)))
        label.setPos(raw_x + 10, raw_y - 22)
        label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        dot.setZValue(20)
        label.setZValue(20)
        self.markers[name] = [dot, label]

    def refresh_overlays(self):
        if not hasattr(self, 'scene'):
            return
        for item in self.npc_items:
            self.scene.removeItem(item)
        self.npc_items.clear()
        if self.show_npcs.isChecked():
            for npc in self.npc_locations:
                raw_x = float(npc['x']) * self.factor.value()
                raw_y = float(npc['y']) * self.factor.value()
                if not 0 <= raw_x <= self.width or not 0 <= raw_y <= self.height:
                    continue
                dot = self.scene.addEllipse(-4, -4, 8, 8, QPen(QColor('#0f766e')), QBrush(QColor('#14b8a6')))
                dot.setPos(raw_x, raw_y)
                dot.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
                dot.setToolTip(f'{npc["name"]} · ({npc["x"]}, {npc["y"]})')
                label = self.scene.addSimpleText(str(npc['name']))
                label.setBrush(QBrush(QColor('#0f4c5c')))
                label.setPos(raw_x + 7, raw_y - 18)
                label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
                dot.setZValue(10)
                label.setZValue(10)
                self.npc_items.extend((dot, label))
        for name, (map_x, map_y, color) in self.marker_positions.items():
            self._draw_marker(name, map_x, map_y, color)

    def locate_npc(self):
        npc = self.npc_combo.currentData()
        if not npc:
            QMessageBox.information(self, '没有 NPC 数据', '当前地图没有可用的 NPC 坐标。')
            return
        self.x.setValue(float(npc['x']))
        self.y.setValue(float(npc['y']))
        self.mark_at('target', '#7b1fa2', float(npc['x']), float(npc['y']))
        self.view.centerOn(float(npc['x']) * self.factor.value(), float(npc['y']) * self.factor.value())
        self.status.setText(
            f'已定位 NPC：{npc["name"]} ({npc["x"]}, {npc["y"]})。'
            '该点来自现有 NPC 数据，请用游戏实景校准。'
        )

    def capture_navigation_npcs(self):
        """Capture all pages of QQSG's navigation panel using its down control."""
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            QMessageBox.warning(self, '窗口不可用', '绑定的游戏窗口已关闭，请重新绑定。')
            return
        capture_active = False
        previous_cursor = None
        previous_foreground = None
        try:
            def capture_client():
                left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
                image = self.window_handler.capture_window_image(self.hwnd, right - left, bottom - top)
                client_left, client_top = win32gui.ClientToScreen(self.hwnd, (0, 0))
                _, _, client_width, client_height = win32gui.GetClientRect(self.hwnd)
                offset_x, offset_y = client_left - left, client_top - top
                client = image[offset_y:offset_y + client_height, offset_x:offset_x + client_width].copy()
                return cv2.cvtColor(client, cv2.COLOR_RGB2BGR)

            preview = capture_client()
            region = cv2.selectROI('Select QQSG navigation NPC list', preview,
                                   showCrosshair=True, fromCenter=False)
            cv2.destroyWindow('Select QQSG navigation NPC list')
            if region == (0, 0, 0, 0):
                return
            x, y, width, height = (int(value) for value in region)
            crop = preview[y:y + height, x:x + width]
            if crop.size == 0:
                raise ValueError('框选区域为空')
            self.status.setText('正在分页识别寻路列表，首次加载 OCR 可能需要一些时间……')
            if self._ocr is None:
                self._ocr = Ocr()
            # QQSG's DirectX UI ignores a parent-window PostMessage while inactive.
            # Temporarily expose and activate the game, then send real mouse clicks.
            previous_cursor = win32api.GetCursorPos()
            previous_foreground = win32gui.GetForegroundWindow()
            self.hide()
            capture_active = True
            try:
                if win32gui.IsIconic(self.hwnd):
                    win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(self.hwnd)
            except win32gui.error:
                pass
            time.sleep(0.25)
            # The in-game navigation list only accepts scrolling after a real
            # click gives the panel focus.
            center_client = (x + width // 2, y + height // 2)
            center_screen = win32gui.ClientToScreen(self.hwnd, center_client)
            win32api.SetCursorPos(center_screen)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.04)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.12)

            def scroll_navigation(delta: int):
                win32api.SetCursorPos(center_screen)
                win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)

            # Normalize to the top. Wheel messages clamp harmlessly when the
            # first row has already been reached.
            for _ in range(30):
                scroll_navigation(120)
                time.sleep(0.018)
            time.sleep(0.18)
            collected = {}
            rows = []
            selected_map = None
            previous_signature = None
            unchanged_pages = 0
            page_count = 0
            for page in range(80):
                current = capture_client()[y:y + height, x:x + width]
                items = self._ocr.do_ocr_ext(current)
                if selected_map is None:
                    provisional_records, rows = parse_npc_rows(items, self.MAP_NAME, self.MAP_ID)
                    selected_map = detect_navigation_map(rows, self.map_catalog)
                    if selected_map is None:
                        recognized = '\n'.join(row['text'] for row in rows)
                        raise ValueError(f'没有识别出寻路窗口当前地图。OCR：{recognized[:500]}')
                page_records, rows = parse_npc_rows(
                    items, str(selected_map['name']), int(selected_map['id'])
                )
                signature = tuple((item['name'], item['x'], item['y']) for item in page_records)
                before = len(collected)
                for record in page_records:
                    collected[(record['name'], record['x'], record['y'])] = record
                page_count = page + 1
                unchanged_pages = unchanged_pages + 1 if len(collected) == before else 0
                self.status.setText(
                    f'正在采集第 {page_count} 页：本页 {len(page_records)} 个，累计 {len(collected)} 个……'
                )
                from PyQt5.QtWidgets import QApplication
                QApplication.processEvents()
                # A single wheel notch can move less than one text row, so the
                # same OCR set may legitimately repeat several times mid-list.
                if unchanged_pages >= 5 and signature == previous_signature:
                    break
                previous_signature = signature
                # One notch keeps substantial overlap between adjacent frames,
                # including rows that were only half visible in the last frame.
                scroll_navigation(-120)
                time.sleep(0.22)
            records = list(collected.values())
        except Exception as error:
            cv2.destroyAllWindows()
            if capture_active:
                if previous_cursor is not None:
                    win32api.SetCursorPos(previous_cursor)
                self.show()
                self.raise_()
                self.activateWindow()
                capture_active = False
            QMessageBox.warning(self, 'NPC 采集失败', str(error))
            self.status.setText(f'NPC 采集失败：{error}')
            return
        finally:
            if capture_active:
                if previous_cursor is not None:
                    win32api.SetCursorPos(previous_cursor)
                self.show()
                self.raise_()
                self.activateWindow()
                if previous_foreground and previous_foreground != self.hwnd:
                    # Qt activation above is preferred; this is best-effort only.
                    try:
                        win32gui.SetForegroundWindow(int(self.winId()))
                    except win32gui.error:
                        pass
        if not records:
            recognized = '\n'.join(row['text'] for row in rows) or '<空>'
            QMessageBox.information(
                self, '没有解析到 NPC',
                'OCR 已运行，但没有找到“NPC名称 (X, Y)”格式。请框选完整自动寻路窗口。\n\n'
                f'本次 OCR：\n{recognized[:1200]}',
            )
            self.status.setText('没有解析到 NPC；请查看弹窗中的 OCR 原文并重新框选。')
            return
        self.npcs_collected.emit(records)
        if str(selected_map['name']).replace('·', '.') != self.MAP_NAME:
            details = '、'.join(f'{item["name"]}({item["x"]},{item["y"]})' for item in records)
            self.status.setText(
                f'已保存地图 {selected_map["name"]}（ID {selected_map["id"]}）的 '
                f'{len(records)} 个 NPC：{details}。当前地形画布仍为成都·子城，未叠加其他地图坐标。'
            )
            return
        # A freshly captured coordinate replaces the legacy coordinate for the
        # same NPC instead of leaving two markers on the map.
        merged = {
            (str(item.get('map', self.MAP_NAME)).replace('·', '.'), item['name']): item
            for item in self.npc_locations
        }
        for record in records:
            merged[(record['map'].replace('·', '.'), record['name'])] = record
        self.npc_locations = sorted(merged.values(), key=lambda item: (item['y'], item['x'], item['name']))
        self.npc_combo.clear()
        for npc in self.npc_locations:
            self.npc_combo.addItem(f'{npc["name"]}  ({npc["x"]}, {npc["y"]})', npc)
        self.show_npcs.setText(f'显示 NPC（已采集 {len(self.npc_locations)}）')
        self.show_npcs.setChecked(True)
        self.refresh_overlays()
        details = '、'.join(f'{item["name"]}({item["x"]},{item["y"]})' for item in records)
        self.status.setText(f'分页 {page_count} 次，共采集 {len(records)} 个 NPC：{details}。')
