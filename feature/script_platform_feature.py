import json
import shutil
from copy import deepcopy
from pathlib import Path

import cv2
import win32gui
import win32process
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap, QTextCursor, QTextOption
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox, QHBoxLayout,
                             QLabel, QListWidget, QListWidgetItem, QLineEdit, QMessageBox,
                             QPushButton, QSizePolicy, QSplitter, QTextEdit, QVBoxLayout,
                             QWidget)

from core.winhandler import WindowHandler
from core.text import repair_utf8_gbk_mojibake
from core.window_titles import is_qqsg_game_window_title
from plugin_platform.manager import PluginManager, PluginManifest
from plugin_platform.qqsg_data import (QQSGPackage, find_installation, import_routes,
                                       parse_map_catalog)
from plugin_platform.runner import PluginProcess


class ScalablePreviewLabel(QLabel):
    """Preview viewport whose source image never affects layout sizing."""

    def __init__(self, placeholder: str):
        super().__init__(placeholder)
        self._source_pixmap = QPixmap()

    def show_image(self, image: QImage):
        self._source_pixmap = QPixmap.fromImage(image)
        self.setText('')
        self._fit_image()

    def clear_image(self, placeholder: str):
        self._source_pixmap = QPixmap()
        super().setPixmap(QPixmap())
        self.setText(placeholder)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_image()

    def _fit_image(self):
        if self._source_pixmap.isNull():
            return
        target_size = self.contentsRect().size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            return
        super().setPixmap(self._source_pixmap.scaled(
            target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        ))


class ScriptPlatformFeature:
    """Plugin discovery, configuration, window binding, and runtime UI."""

    def __init__(self, parent):
        self.parent = parent
        self.manager = PluginManager()
        self.manifests: list[PluginManifest] = []
        self.window_handler = WindowHandler()
        self.target_window_info = None
        self.target_windows: list[dict] = []
        self.runners: dict[str, PluginProcess] = {}
        self.session_states: dict[str, str] = {}
        self.session_logs: dict[str, list[str]] = {}
        self.session_frames: dict[str, object] = {}
        self.running = False
        self.current_config: dict = {}

    def create_ui(self):
        self.group_box = QGroupBox('自动化脚本平台')
        self.group_box.setObjectName('scriptPlatformCard')
        self.group_box.setStyleSheet("""
            QGroupBox#scriptPlatformCard QPushButton {
                min-height: 28px;
                max-height: 28px;
                padding: 0 9px;
                border-radius: 4px;
                font-size: 12px;
            }
            QGroupBox#scriptPlatformCard QPushButton#scriptPrimaryButton {
                min-height: 30px;
                max-height: 30px;
                background: #356AE6;
                color: white;
                border: 1px solid #356AE6;
                font-weight: 600;
            }
            QGroupBox#scriptPlatformCard QPushButton#scriptPrimaryButton:hover {
                background: #285ACB;
                border-color: #285ACB;
            }
            QGroupBox#scriptPlatformCard QLabel#scriptStatus {
                min-height: 26px;
                max-height: 26px;
                padding: 0 8px;
                background: #F2F6FC;
                color: #53627A;
                border-radius: 4px;
            }
            QGroupBox#scriptPlatformCard QTextEdit {
                border-radius: 4px;
            }
            QGroupBox#scriptPlatformCard QListWidget::item {
                min-height: 40px;
                padding: 0 6px;
                border-radius: 3px;
            }
        """)
        root = QHBoxLayout(self.group_box)
        root.setContentsMargins(12, 16, 12, 10)
        root.setSpacing(12)

        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)
        list_layout.addWidget(QLabel('已安装脚本'))
        self.plugin_list = QListWidget()
        self.plugin_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.plugin_list.currentItemChanged.connect(self._display_selected_plugin)
        list_layout.addWidget(self.plugin_list, 1)
        install_layout = QHBoxLayout()
        install_directory_btn = QPushButton('目录安装')
        install_directory_btn.clicked.connect(self.install_directory)
        install_zip_btn = QPushButton('ZIP 安装')
        install_zip_btn.clicked.connect(self.install_zip)
        refresh_btn = QPushButton('刷新')
        refresh_btn.clicked.connect(self.refresh_plugins)
        install_layout.addWidget(install_directory_btn)
        install_layout.addWidget(install_zip_btn)
        install_layout.addWidget(refresh_btn)
        list_layout.addLayout(install_layout)
        list_panel.setMinimumWidth(200)
        list_panel.setMaximumWidth(235)
        root.addWidget(list_panel, 1)

        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(6)
        self.plugin_title = QLabel('请选择一个脚本')
        self.plugin_title.setObjectName('sectionTitle')
        self.plugin_description = QLabel('插件将在独立 Python 子进程中运行。')
        self.plugin_description.setWordWrap(True)
        self.plugin_description.setObjectName('sectionHint')
        self.plugin_description.setMaximumHeight(44)
        control_layout.addWidget(self.plugin_title)
        control_layout.addWidget(self.plugin_description)

        self.template_panel = QWidget()
        self.template_layout = QHBoxLayout(self.template_panel)
        self.template_layout.setContentsMargins(0, 0, 0, 0)
        self.template_layout.setSpacing(6)
        self.template_status = QLabel('识别模板：无需配置')
        self.template_layout.addWidget(self.template_status)
        self.template_layout.addStretch(1)
        control_layout.addWidget(self.template_panel)

        self.qqsg_data_panel = QWidget()
        qqsg_data_layout = QHBoxLayout(self.qqsg_data_panel)
        qqsg_data_layout.setContentsMargins(0, 0, 0, 0)
        self.qqsg_data_status = QLabel('NPC 路由库：尚未导入')
        import_game_data_btn = QPushButton('导入游戏数据')
        import_game_data_btn.setToolTip('只读解析 QQ 三国 objects.pkg，不修改游戏文件')
        import_game_data_btn.clicked.connect(self.import_qqsg_game_data)
        select_minimap_btn = QPushButton('框选小地图')
        select_minimap_btn.setToolTip('从绑定窗口的后台截图中框选地图名称和坐标')
        select_minimap_btn.clicked.connect(self.select_qqsg_minimap_region)
        select_task_btn = QPushButton('框选任务栏')
        select_task_btn.setToolTip('从绑定窗口的后台截图中框选右侧任务文字区域')
        select_task_btn.clicked.connect(self.select_qqsg_task_region)
        qqsg_data_layout.addWidget(self.qqsg_data_status, 1)
        qqsg_data_layout.addWidget(select_minimap_btn)
        qqsg_data_layout.addWidget(select_task_btn)
        qqsg_data_layout.addWidget(import_game_data_btn)
        map_debug_btn = QPushButton('地图调试')
        map_debug_btn.clicked.connect(self.open_map_debug)
        qqsg_data_layout.addWidget(map_debug_btn)
        map_list_btn = QPushButton('查看地图数据')
        map_list_btn.setToolTip('显示从 QQ 三国 objects.pkg 解析出的全部地图')
        map_list_btn.clicked.connect(self.show_parsed_maps)
        qqsg_data_layout.addWidget(map_list_btn)
        self.qqsg_data_panel.setVisible(False)
        control_layout.addWidget(self.qqsg_data_panel)

        # The daily-task plugin is commonly debugged one activity at a time.
        # Keep this selector next to the QQSG controls so users do not need to
        # edit a long JSON document just to switch between full and single-task
        # runs.
        self.daily_task_panel = QWidget()
        daily_task_layout = QHBoxLayout(self.daily_task_panel)
        daily_task_layout.setContentsMargins(0, 0, 0, 0)
        daily_task_layout.setSpacing(6)
        daily_task_layout.addWidget(QLabel('日常任务调试：'))
        self.daily_task_combo = QComboBox()
        self.daily_task_combo.addItem('完整流程（按任务顺序）', 'sequence')
        self.daily_task_combo.addItem('仅垓下学艺', 'gai_xia_xue_yi')
        self.daily_task_combo.addItem('仅灭鼠靖仓', 'mie_shu_jing_cang')
        self.daily_task_combo.addItem('仅举孝廉答题', 'ju_xiao_lian')
        self.daily_task_combo.addItem('仅运送物资', 'transport')
        self.daily_task_combo.setToolTip(
            '完整流程会按 task_sequence 执行；选择单项后只运行该任务，适合逐项调试。'
        )
        self.daily_task_combo.currentIndexChanged.connect(self._daily_task_selection_changed)
        daily_task_layout.addWidget(self.daily_task_combo, 1)
        self.daily_task_status = QLabel('')
        self.daily_task_status.setObjectName('sectionHint')
        daily_task_layout.addWidget(self.daily_task_status)
        self.daily_task_panel.setVisible(False)
        control_layout.addWidget(self.daily_task_panel)

        self.leveling_panel = QWidget()
        leveling_layout = QHBoxLayout(self.leveling_panel)
        leveling_layout.setContentsMargins(0, 0, 0, 0)
        leveling_layout.setSpacing(6)
        leveling_layout.addWidget(QLabel('小号起号调试：'))
        self.leveling_combo = QComboBox()
        self.leveling_combo.addItem('完整流程（1-50级）', 'full')
        self.leveling_combo.addItem('仅 1-10 级', 'level_1_10')
        self.leveling_combo.addItem('仅 11-20 级', 'level_11_20')
        self.leveling_combo.addItem('仅 21-30 级', 'level_21_30')
        self.leveling_combo.addItem('仅 31-40 级', 'level_31_40')
        self.leveling_combo.addItem('仅 41-50 级', 'level_41_50')
        self.leveling_combo.setToolTip(
            '完整流程从保存的等级继续；单阶段模式只执行选中的等级区间。'
        )
        self.leveling_combo.currentIndexChanged.connect(self._leveling_selection_changed)
        leveling_layout.addWidget(self.leveling_combo, 1)
        self.leveling_status = QLabel('')
        self.leveling_status.setObjectName('sectionHint')
        leveling_layout.addWidget(self.leveling_status)
        self.leveling_panel.setVisible(False)
        control_layout.addWidget(self.leveling_panel)

        self.leveling_region_panel = QWidget()
        leveling_region_layout = QHBoxLayout(self.leveling_region_panel)
        leveling_region_layout.setContentsMargins(0, 0, 0, 0)
        leveling_region_layout.setSpacing(6)
        leveling_region_layout.addWidget(QLabel('起号识别区域：'))
        leveling_task_region_btn = QPushButton('框选任务栏')
        leveling_task_region_btn.clicked.connect(self.select_qqsg_task_region)
        leveling_level_region_btn = QPushButton('框选等级')
        leveling_level_region_btn.clicked.connect(self.select_level_region)
        leveling_region_layout.addWidget(leveling_task_region_btn)
        leveling_region_layout.addWidget(leveling_level_region_btn)
        leveling_region_layout.addStretch(1)
        self.leveling_region_panel.setVisible(False)
        control_layout.addWidget(self.leveling_region_panel)

        window_layout = QHBoxLayout()
        window_layout.setSpacing(6)
        detect_windows_btn = QPushButton('识别全部')
        detect_windows_btn.setFixedWidth(76)
        detect_windows_btn.setToolTip('自动扫描并加入所有 QQ 三国客户端窗口')
        detect_windows_btn.clicked.connect(self.auto_detect_game_windows)
        choose_window_btn = QPushButton('手动添加')
        choose_window_btn.setFixedWidth(76)
        choose_window_btn.clicked.connect(self.choose_window)
        remove_window_btn = QPushButton('移除')
        remove_window_btn.setFixedWidth(54)
        remove_window_btn.clicked.connect(self.remove_current_window)
        self.window_selector = QComboBox()
        self.window_selector.setPlaceholderText('尚未添加游戏窗口')
        self.window_selector.currentIndexChanged.connect(self._active_window_changed)
        window_layout.addWidget(detect_windows_btn)
        window_layout.addWidget(choose_window_btn)
        window_layout.addWidget(self.window_selector, 1)
        window_layout.addWidget(remove_window_btn)
        control_layout.addLayout(window_layout)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(6)
        self.dry_run_checkbox = QCheckBox('模拟运行（不发送真实键鼠输入）')
        self.dry_run_checkbox.setChecked(True)
        action_layout.addWidget(self.dry_run_checkbox)
        action_layout.addStretch(1)
        config_btn = QPushButton('配置')
        config_btn.setFixedWidth(60)
        config_btn.setToolTip('打开 JSON 运行配置')
        config_btn.clicked.connect(self.edit_config)
        action_layout.addWidget(config_btn)
        self.start_btn = QPushButton('启动  Home')
        self.start_btn.setObjectName('scriptPrimaryButton')
        self.start_btn.setFixedWidth(132)
        self.start_btn.clicked.connect(self.toggle)
        self.start_btn.setEnabled(False)
        action_layout.addWidget(self.start_btn)
        control_layout.addLayout(action_layout)

        self.status_label = QLabel('状态：待机')
        self.status_label.setObjectName('scriptStatus')
        control_layout.addWidget(self.status_label)

        bottom_splitter = QSplitter(Qt.Horizontal)
        bottom_splitter.setChildrenCollapsible(False)
        bottom_splitter.setHandleWidth(8)
        bottom_splitter.setOpaqueResize(True)
        bottom_splitter.setMinimumHeight(270)

        log_panel = QWidget()
        log_panel.setMinimumWidth(260)
        log_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(5)
        log_layout.addWidget(QLabel('运行日志'))
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setLineWrapMode(QTextEdit.WidgetWidth)
        self.log_display.setWordWrapMode(QTextOption.WrapAnywhere)
        self.log_display.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log_display.setMinimumSize(240, 240)
        self.log_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.log_display.setStyleSheet('font-family: Consolas, monospace; font-size: 12px;')
        self.log_display.document().setMaximumBlockCount(500)
        log_layout.addWidget(self.log_display, 1)
        bottom_splitter.addWidget(log_panel)

        preview_panel = QWidget()
        preview_panel.setMinimumWidth(260)
        preview_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(5)
        preview_layout.addWidget(QLabel('脚本截图预览'))
        self.preview_label = ScalablePreviewLabel('脚本执行截图将在这里显示')
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(240, 240)
        # A QLabel normally uses its pixmap's native width as its size hint.
        # Ignore that hint so a large captured frame cannot squeeze the log
        # panel; _render_frame() already scales the image to this viewport.
        self.preview_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.preview_label.setStyleSheet(
            'background: #F7F9FC; border: 1px solid #E4E9F0; border-radius: 8px;'
        )
        preview_layout.addWidget(self.preview_label, 1)
        bottom_splitter.addWidget(preview_panel)
        bottom_splitter.setSizes([1, 1])
        bottom_splitter.setStretchFactor(0, 1)
        bottom_splitter.setStretchFactor(1, 1)
        control_layout.addWidget(bottom_splitter, 1)
        root.addWidget(control_panel, 4)

        self.parent.left_layout.addWidget(self.group_box)
        self.refresh_plugins()

    def open_map_debug(self, map_name=None, map_id=None, terrain_entry=None):
        from feature.map_debug_dialog import MapDebugDialog
        config = self.current_config
        saved = config.get('route_data_source', {}).get('game_directory', '')
        installation = Path(saved) if saved else find_installation()
        if not installation or not (installation / 'data/objects.pkg').is_file():
            selected = QFileDialog.getExistingDirectory(self.group_box, '选择 QQ 三国安装目录')
            if not selected:
                return
            installation = Path(selected)
        try:
            manifest = self.current_manifest()
            npc_file = manifest.directory / 'assets/data/npc_locations.json' if manifest else None
            captured_npcs = []
            captured_maps = config.get('captured_npc_maps', {})
            if isinstance(captured_maps, dict) and captured_maps:
                for map_value in captured_maps.values():
                    if not isinstance(map_value, dict):
                        continue
                    for name, value in map_value.get('npcs', {}).items():
                        if isinstance(value, dict):
                            captured_npcs.append({
                                'name': name,
                                'map': map_value.get('map', ''),
                                'map_id': map_value.get('map_id'),
                                **value,
                            })
            captured_config = config.get('captured_npc_routes', {})
            if not captured_npcs and isinstance(captured_config, dict):
                for name, value in captured_config.items():
                    if isinstance(value, dict):
                        captured_npcs.append({'name': name, **value})
            map_package = installation / 'data/update.pkg'
            if not map_package.is_file():
                map_package = installation / 'data/objects.pkg'
            map_catalog = parse_map_catalog(QQSGPackage(map_package).read('res/Txt/MapData.txt'))
            dialog = MapDebugDialog(
                installation / 'data/objects.pkg',
                npc_file=npc_file,
                captured_npcs=captured_npcs,
                map_catalog=map_catalog,
                window_handler=self.window_handler,
                hwnd=int(self.target_window_info['hwnd']) if self.target_window_info else None,
                parent=self.group_box,
                map_name=map_name,
                map_id=map_id,
                terrain_entry=terrain_entry,
            )
            dialog.plan_selected.connect(self.load_terrain_test)
            dialog.npcs_collected.connect(self.save_captured_npcs)
            self.save_terrain_model(dialog.terrain_model())
            dialog.exec_()
        except Exception as error:
            QMessageBox.warning(self.group_box, '地图加载失败', str(error))

    def save_terrain_model(self, model: dict):
        """Persist reusable terrain independently from optional test routes."""
        manifest = self.current_manifest()
        if not manifest or manifest.id != 'com.searchcat.qqsg.official-task':
            return
        config = self._read_config()
        models = dict(config.get('terrain_models', {})) if isinstance(config.get('terrain_models'), dict) else {}
        models[str(model['map'])] = model
        config['terrain_models'] = models
        self.manager.save_config(manifest, config)
        self.current_config = config
        self._log(f'[地形模型] 已保存 {model["map"]}，正式任务可按实时起点规划')

    def save_captured_npcs(self, records: list):
        """Merge NPC coordinates captured from the game's own navigation panel."""
        manifest = self.current_manifest()
        if not manifest or manifest.id != 'com.searchcat.qqsg.official-task' or not records:
            return
        config = self._read_config()
        routes = config.get('npc_routes', {})
        navigation = config.get('navigation_routes', {})
        captured = config.get('captured_npc_routes', {})
        captured_maps = config.get('captured_npc_maps', {})
        routes = dict(routes) if isinstance(routes, dict) else {}
        navigation = dict(navigation) if isinstance(navigation, dict) else {}
        captured = dict(captured) if isinstance(captured, dict) else {}
        captured_maps = dict(captured_maps) if isinstance(captured_maps, dict) else {}
        for record in records:
            name = str(record['name'])
            route = [int(record['map_id']), int(record['x']), int(record['y'])]
            routes[name] = route
            captured[name] = {
                'map': str(record['map']), 'map_id': route[0],
                'x': route[1], 'y': route[2],
                'ocr_confidence': float(record.get('confidence', 0)),
            }
            map_key = str(route[0])
            map_record = dict(captured_maps.get(map_key, {}))
            map_npcs = dict(map_record.get('npcs', {})) if isinstance(map_record.get('npcs', {}), dict) else {}
            map_npcs[name] = {
                'x': route[1], 'y': route[2],
                'ocr_confidence': float(record.get('confidence', 0)),
            }
            captured_maps[map_key] = {
                'map': str(record['map']), 'map_id': route[0], 'npcs': map_npcs,
            }
            existing_path = navigation.get(name)
            existing_waypoints = existing_path.get('waypoints', []) if isinstance(existing_path, dict) else []
            if not isinstance(existing_waypoints, list) or len(existing_waypoints) <= 1:
                # Replace legacy/imported direct endpoints. Multi-point paths
                # were explicitly calibrated by the user and remain intact.
                navigation[name] = {
                    'map': str(record['map']),
                    'waypoints': [[route[1], route[2]]],
                }
        config['npc_routes'] = routes
        config['navigation_routes'] = navigation
        config['captured_npc_routes'] = captured
        config['captured_npc_maps'] = captured_maps
        self.manager.save_config(manifest, config)
        self.current_config = config
        self._update_qqsg_data_controls(manifest, config)
        self._log(f'[NPC 采集] 已保存 {len(records)} 条游戏寻路窗口坐标')

    def load_terrain_test(self, plan):
        manifest = self.current_manifest()
        if not manifest:
            return
        config = dict(self.current_config)
        config['terrain_test_plan'] = plan
        config['terrain_test_enabled'] = True
        config['terrain_test_pending'] = True
        terrain_models = dict(config.get('terrain_models', {})) if isinstance(config.get('terrain_models'), dict) else {}
        terrain_models[str(plan.get('map', '成都.子城'))] = {
            'map': str(plan.get('map', '成都.子城')),
            'scale': float(plan.get('scale', 100)),
            'terrain_records': plan.get('terrain_records', []),
            'planner': plan.get('planner', {}),
        }
        config['terrain_models'] = terrain_models
        self.manager.save_config(manifest, config)
        self.current_config = config
        QMessageBox.information(self.group_box, '已载入寻路测试',
                                '启动脚本将只测试该路线。请先模拟运行核对日志，再取消模拟进行实测。'
                                '\n恢复官爵任务时，在配置中将 terrain_test_enabled 改为 false。')

    def refresh_plugins(self):
        selected_id = self.current_manifest().id if self.current_manifest() else None
        self.manifests, errors = self.manager.discover()
        self.plugin_list.clear()
        selected_row = 0
        for index, manifest in enumerate(self.manifests):
            item = QListWidgetItem(f'{manifest.name}\n{manifest.version}')
            item.setToolTip(f'{manifest.name}\n版本：{manifest.version}\nID：{manifest.id}')
            item.setData(Qt.UserRole, index)
            self.plugin_list.addItem(item)
            if manifest.id == selected_id:
                selected_row = index
        if self.manifests:
            self.plugin_list.setCurrentRow(selected_row)
        else:
            self.plugin_title.setText('尚未安装脚本')
            self.plugin_description.setText('可安装包含 plugin.json 的目录或 ZIP。')
            self.start_btn.setEnabled(False)
        for error in errors:
            self._log(f'[清单错误] {error}')

    def current_manifest(self) -> PluginManifest | None:
        item = self.plugin_list.currentItem() if hasattr(self, 'plugin_list') else None
        if not item:
            return None
        index = item.data(Qt.UserRole)
        return self.manifests[index] if isinstance(index, int) and index < len(self.manifests) else None

    def _display_selected_plugin(self):
        manifest = self.current_manifest()
        if not manifest:
            return
        self.qqsg_data_panel.setVisible(manifest.id in {
            'com.searchcat.qqsg.official-task',
            'com.searchcat.qqsg.daily-tasks',
        })
        self.plugin_title.setText(f'{manifest.name}  {manifest.version}')
        permissions = '、'.join(manifest.permissions) if manifest.permissions else '无额外权限声明'
        description = f'{manifest.description}\n权限：{permissions}'
        self.plugin_description.setText(description)
        self.plugin_description.setToolTip(description)
        try:
            config = self.manager.load_config(manifest)
            if manifest.id == 'com.searchcat.qqsg.official-task' and self._apply_captured_npc_precedence(config):
                self.manager.save_config(manifest, config)
            self.current_config = config
            self._rebuild_template_controls(manifest, config)
            self._update_qqsg_data_controls(manifest, config)
            self._update_daily_task_controls(manifest, config)
            self._update_leveling_controls(manifest, config)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.current_config = {}
            self._rebuild_template_controls(manifest, {})
            self._update_daily_task_controls(manifest, {})
            self._update_leveling_controls(manifest, {})
            self._log(f'[配置错误] {error}')
        self._update_start_enabled()

    def _update_daily_task_controls(self, manifest: PluginManifest, config: dict):
        """Synchronize the daily-task selector from the saved JSON profile."""
        visible = manifest.id == 'com.searchcat.qqsg.daily-tasks'
        self.daily_task_panel.setVisible(visible)
        if not visible:
            return
        mode = str(config.get('task_mode', 'sequence')).strip().lower()
        selected = str(config.get('single_task', 'gai_xia_xue_yi')).strip()
        value = selected if mode in {'single', 'debug', 'one'} else 'sequence'
        index = self.daily_task_combo.findData(value)
        self.daily_task_combo.blockSignals(True)
        self.daily_task_combo.setCurrentIndex(index if index >= 0 else 0)
        self.daily_task_combo.blockSignals(False)
        self.daily_task_status.setText(
            '单任务模式：便于调试' if value != 'sequence' else '完整流程'
        )

    def _daily_task_selection_changed(self, _index: int):
        """Persist the simple UI choice into the plugin's JSON profile."""
        manifest = self.current_manifest()
        if not manifest or manifest.id != 'com.searchcat.qqsg.daily-tasks':
            return
        value = self.daily_task_combo.currentData()
        if not value:
            return
        config = self._read_config()
        if value == 'sequence':
            config['task_mode'] = 'sequence'
            description = '完整流程'
        else:
            config['task_mode'] = 'single'
            config['single_task'] = str(value)
            description = f'单任务：{self.daily_task_combo.currentText()}'
        try:
            path = self.manager.save_config(manifest, config)
        except OSError as error:
            self._log(f'[日常任务模式保存失败] {error}')
            return
        self.current_config = config
        self.daily_task_status.setText('单任务模式：便于调试' if value != 'sequence' else '完整流程')
        self._log(f'[日常任务模式] 已切换为 {description}，配置已保存：{path}')

    def _update_leveling_controls(self, manifest: PluginManifest, config: dict):
        """Synchronize the level-1-to-50 debug selector."""
        visible = manifest.id == 'com.searchcat.qqsg.alt-leveling'
        self.leveling_panel.setVisible(visible)
        self.leveling_region_panel.setVisible(visible)
        if not visible:
            return
        mode = str(config.get('run_mode', 'full')).strip().lower()
        selected = str(config.get('single_stage', 'level_1_10')).strip()
        value = selected if mode == 'single_stage' else 'full'
        index = self.leveling_combo.findData(value)
        self.leveling_combo.blockSignals(True)
        self.leveling_combo.setCurrentIndex(index if index >= 0 else 0)
        self.leveling_combo.blockSignals(False)
        profile = f'{config.get("country", "蜀国")}·{config.get("role_class", "游侠")}'
        self.leveling_status.setText(
            f'{"单阶段调试" if value != "full" else "完整流程"} · {profile}'
        )

    def _leveling_selection_changed(self, _index: int):
        """Persist the level-stage debug choice in the plugin profile."""
        manifest = self.current_manifest()
        if not manifest or manifest.id != 'com.searchcat.qqsg.alt-leveling':
            return
        value = self.leveling_combo.currentData()
        if not value:
            return
        config = self._read_config()
        if value == 'full':
            config['run_mode'] = 'full'
            description = '完整 1-50 级流程'
        else:
            config['run_mode'] = 'single_stage'
            config['single_stage'] = str(value)
            description = f'单阶段：{self.leveling_combo.currentText()}'
        try:
            path = self.manager.save_config(manifest, config)
        except OSError as error:
            self._log(f'[小号起号模式保存失败] {error}')
            return
        self.current_config = config
        profile = f'{config.get("country", "蜀国")}·{config.get("role_class", "游侠")}'
        self.leveling_status.setText(
            f'{"单阶段调试" if value != "full" else "完整流程"} · {profile}'
        )
        self._log(f'[小号起号模式] 已切换为 {description}，配置已保存：{path}')

    def select_level_region(self):
        self._select_qqsg_region(
            'level_region', 'Select character level region', '等级',
        )

    def _update_qqsg_data_controls(self, manifest: PluginManifest, config: dict):
        visible = manifest.id in {
            'com.searchcat.qqsg.official-task',
            'com.searchcat.qqsg.daily-tasks',
        }
        self.qqsg_data_panel.setVisible(visible)
        if visible:
            route_count = len(config.get('npc_routes', {})) if isinstance(config.get('npc_routes'), dict) else 0
            captured_maps = config.get('captured_npc_maps', {})
            map_count = len(captured_maps) if isinstance(captured_maps, dict) else 0
            captured_count = sum(
                len(value.get('npcs', {}))
                for value in captured_maps.values()
                if isinstance(value, dict) and isinstance(value.get('npcs'), dict)
            ) if isinstance(captured_maps, dict) else 0
            region = config.get('minimap_region')
            region_text = f' · 小地图 {region}' if isinstance(region, list) and len(region) == 4 else ''
            task_region = config.get('task_region')
            task_region_text = (
                f' · 任务栏 {task_region}'
                if isinstance(task_region, list) and len(task_region) == 4 else ''
            )
            capture_text = f' · 已采集 {map_count} 图/{captured_count} NPC' if map_count else ''
            self.qqsg_data_status.setText(
                f'NPC 路由库：{route_count} 条{capture_text}{region_text}{task_region_text}'
            )

    @staticmethod
    def _apply_captured_npc_precedence(config: dict) -> bool:
        """Make captures authoritative and migrate them into the per-map catalog."""
        captured = config.get('captured_npc_routes', {})
        if not isinstance(captured, dict):
            return False
        routes = config.get('npc_routes', {})
        navigation = config.get('navigation_routes', {})
        routes = dict(routes) if isinstance(routes, dict) else {}
        navigation = dict(navigation) if isinstance(navigation, dict) else {}
        captured_maps = dict(config.get('captured_npc_maps', {})) \
            if isinstance(config.get('captured_npc_maps'), dict) else {}
        changed = False
        for name, record in captured.items():
            if not isinstance(record, dict):
                continue
            try:
                endpoint = [int(record['map_id']), int(record['x']), int(record['y'])]
            except (KeyError, TypeError, ValueError):
                continue
            if routes.get(name) != endpoint:
                routes[name] = endpoint
                changed = True
            map_key = str(endpoint[0])
            map_value = dict(captured_maps.get(map_key, {}))
            map_npcs = dict(map_value.get('npcs', {})) if isinstance(map_value.get('npcs'), dict) else {}
            captured_value = {
                'x': endpoint[1], 'y': endpoint[2],
                'ocr_confidence': float(record.get('ocr_confidence', 0)),
            }
            if map_npcs.get(name) != captured_value:
                map_npcs[name] = captured_value
                changed = True
            captured_maps[map_key] = {
                'map': str(record.get('map', map_value.get('map', ''))),
                'map_id': endpoint[0], 'npcs': map_npcs,
            }
            existing_path = navigation.get(name)
            waypoints = existing_path.get('waypoints', []) if isinstance(existing_path, dict) else []
            direct_path = {'map': str(record.get('map', '')), 'waypoints': [[endpoint[1], endpoint[2]]]}
            if (not isinstance(waypoints, list) or len(waypoints) <= 1) and existing_path != direct_path:
                navigation[name] = direct_path
                changed = True
        config['npc_routes'] = routes
        config['navigation_routes'] = navigation
        config['captured_npc_maps'] = captured_maps
        return changed

    def select_qqsg_minimap_region(self):
        self._select_qqsg_region(
            'minimap_region', 'Select minimap name and coordinates', '小地图',
        )

    def select_qqsg_task_region(self):
        self._select_qqsg_region(
            'task_region', 'Select task sidebar text region', '任务栏',
        )

    def _select_qqsg_region(self, config_key: str, window_title: str, label: str):
        manifest = self.current_manifest()
        if not manifest or manifest.id not in {
            'com.searchcat.qqsg.official-task',
            'com.searchcat.qqsg.daily-tasks',
            'com.searchcat.qqsg.alt-leveling',
        }:
            return
        if not self.target_window_info:
            QMessageBox.information(self.group_box, '请先绑定窗口', '请先绑定要运行脚本的游戏窗口。')
            return
        hwnd = int(self.target_window_info['hwnd'])
        if not win32gui.IsWindow(hwnd):
            QMessageBox.warning(self.group_box, '窗口失效', '绑定的游戏窗口已经关闭，请重新绑定。')
            return
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            image = self.window_handler.capture_window_image(hwnd, right - left, bottom - top)
            client_left, client_top = win32gui.ClientToScreen(hwnd, (0, 0))
            _, _, client_width, client_height = win32gui.GetClientRect(hwnd)
            offset_x, offset_y = client_left - left, client_top - top
            client_image = image[
                offset_y:offset_y + client_height,
                offset_x:offset_x + client_width,
            ].copy()
            preview = cv2.cvtColor(client_image, cv2.COLOR_RGB2BGR)
            region = cv2.selectROI(
                window_title,
                preview,
                showCrosshair=True,
                fromCenter=False,
            )
            cv2.destroyWindow(window_title)
        except Exception as error:
            QMessageBox.warning(self.group_box, '框选失败', str(error))
            self._log(f'[{label}框选失败] {error}')
            return
        if region == (0, 0, 0, 0):
            return
        config = self._read_config()
        config[config_key] = [int(value) for value in region]
        self.manager.save_config(manifest, config)
        self.current_config = config
        self._update_qqsg_data_controls(manifest, config)
        self._log(f'[{label}区域] 已保存客户区相对区域：{config[config_key]}')

    def import_qqsg_game_data(self):
        manifest = self.current_manifest()
        if not manifest or manifest.id != 'com.searchcat.qqsg.official-task':
            return
        install_dir = find_installation()
        if install_dir is None:
            selected = QFileDialog.getExistingDirectory(
                self.group_box, '选择 QQ 三国安装目录（目录内应包含 data/objects.pkg）'
            )
            if not selected:
                return
            install_dir = Path(selected)
        coordinate_file = manifest.directory / 'assets' / 'data' / 'npc_locations.json'
        try:
            routes, report = import_routes(install_dir, coordinate_file)
            if not routes:
                raise ValueError('地图数据已读取，但没有坐标记录能匹配当前客户端地图')
            config = self._read_config()
            existing = config.get('npc_routes', {})
            if not isinstance(existing, dict):
                existing = {}
            # Existing values include coordinates captured from the in-game
            # navigation panel and therefore outrank legacy imported data.
            config['npc_routes'] = {**routes, **existing}
            existing_navigation = config.get('navigation_routes', {})
            if not isinstance(existing_navigation, dict):
                existing_navigation = {}
            config['navigation_routes'] = {
                **report.get('navigation_routes', {}),
                **existing_navigation,
            }
            config['route_data_source'] = {
                'game_directory': str(install_dir),
                'map_count': report['maps'],
                'coordinate_count': report['locations'],
            }
            self.manager.save_config(manifest, config)
            self.current_config = config
            self._update_qqsg_data_controls(manifest, config)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self.group_box, '游戏数据导入失败', str(error))
            self._log(f'[游戏数据导入失败] {error}')
            return
        conflict_count = len(report['conflicts'])
        unmatched_count = len(report['unmatched'])
        summary = (
            f"已从当前客户端解析 {report['maps']} 张地图，生成 {report['routes']} 条 NPC 路由；"
            f"地图未匹配 {unmatched_count} 条，重名冲突 {conflict_count} 条。"
        )
        self._log(f'[游戏数据] {summary} 来源：{install_dir}')
        QMessageBox.information(self.group_box, '游戏数据导入完成', summary)

    def _rebuild_template_controls(self, manifest: PluginManifest, config: dict | None = None):
        while self.template_layout.count() > 2:
            item = self.template_layout.takeAt(1)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        templates = manifest.templates or []
        if (manifest.id == 'com.searchcat.qqsg.official-task'
                and (config or {}).get('accept_mode', 'enter_spam') != 'guided_click'):
            self.template_panel.setVisible(False)
            return
        self.template_panel.setVisible(bool(templates))
        if not templates:
            self.template_status.setText('识别模板：无需配置')
            return
        available = sum(
            (manifest.directory / 'assets' / definition['path']).is_file()
            for definition in templates
        )
        self.template_status.setText(f'识别模板：已配置 {available}/{len(templates)}')
        for definition in templates:
            path = manifest.directory / 'assets' / definition['path']
            button = QPushButton(('替换' if path.is_file() else '导入') + definition['name'])
            button.setToolTip(str(path))
            button.clicked.connect(
                lambda _checked=False, item=definition: self._import_template(item)
            )
            self.template_layout.insertWidget(self.template_layout.count() - 1, button)

    def _import_template(self, definition: dict[str, str]):
        manifest = self.current_manifest()
        if not manifest:
            return
        source, _ = QFileDialog.getOpenFileName(
            self.group_box,
            f"选择{definition['name']}截图",
            '',
            '图片文件 (*.png *.jpg *.jpeg *.bmp)',
        )
        if not source:
            return
        destination = manifest.directory / 'assets' / definition['path']
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as error:
            QMessageBox.warning(self.group_box, '模板导入失败', str(error))
            return
        self._log(f"已导入{definition['name']}：{destination}")
        self._rebuild_template_controls(manifest, self.current_config)

    @staticmethod
    def _missing_templates(manifest: PluginManifest) -> list[str]:
        return [
            definition['name']
            for definition in (manifest.templates or [])
            if not (manifest.directory / 'assets' / definition['path']).is_file()
        ]

    def _install(self, path: str):
        if not path:
            return
        try:
            manifest = self.manager.install(Path(path))
            self._log(f'已安装插件：{manifest.name} {manifest.version}')
            self.refresh_plugins()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self.group_box, '安装失败', str(error))

    def install_directory(self):
        self._install(QFileDialog.getExistingDirectory(self.group_box, '选择插件目录'))

    def install_zip(self):
        path, _ = QFileDialog.getOpenFileName(self.group_box, '选择插件 ZIP', '', 'ZIP 文件 (*.zip)')
        self._install(path)

    def choose_window(self):
        self.window_handler.choose_window()
        if not self.window_handler.window:
            return
        window = self.window_handler.window
        info = self.window_handler.window_info or {}
        title = repair_utf8_gbk_mojibake(str(info.get('title') or window.title))
        selected = {
            'id': f"hwnd-{int(getattr(window, '_hWnd', 0))}",
            'hwnd': int(getattr(window, '_hWnd', 0)),
            'pid': int(info.get('pid', 0)),
            'title': title,
            'number': int(info.get('number', 1)),
            'left': int(window.left),
            'top': int(window.top),
            'width': int(window.right - window.left),
            'height': int(window.bottom - window.top),
            'source': 'manual',
        }
        existing_index = next(
            (index for index, item in enumerate(self.target_windows)
             if item['id'] == selected['id']),
            None,
        )
        if existing_index is None:
            self.target_windows.append(selected)
            self.session_states[selected['id']] = 'ready'
            self.session_logs.setdefault(selected['id'], [])
            self._refresh_window_selector(selected['id'])
            self._log(
                f"[多窗口] 已添加 {title} #{selected['number']} · PID {selected['pid']}",
                selected['id'],
            )
        else:
            self.target_windows[existing_index] = selected
            self._refresh_window_selector(selected['id'])
        self._update_start_enabled()

    @staticmethod
    def _candidate_window_info(candidate: dict, number: int) -> dict:
        hwnd = int(candidate.get('hwnd', 0))
        return {
            'id': f'hwnd-{hwnd}',
            'hwnd': hwnd,
            'pid': int(candidate.get('pid', 0)),
            'title': repair_utf8_gbk_mojibake(str(candidate.get('title', ''))),
            'number': int(number),
            'left': int(candidate.get('left', 0)),
            'top': int(candidate.get('top', 0)),
            'width': int(candidate.get('width', 0)),
            'height': int(candidate.get('height', 0)),
            'source': 'auto',
        }

    @staticmethod
    def _is_live_window_info(info: dict) -> bool:
        hwnd = int(info.get('hwnd', 0))
        if not hwnd or not win32gui.IsWindow(hwnd):
            return False
        try:
            _, live_pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return False
        expected_pid = int(info.get('pid', 0))
        return not expected_pid or int(live_pid) == expected_pid

    def auto_detect_game_windows(self, _checked=False, silent=False):
        """Replace bindings with every currently visible QQSG client window."""
        if self.running:
            if not silent:
                QMessageBox.information(
                    self.group_box, '脚本正在运行',
                    '请先停止全部窗口，再重新扫描游戏窗口。',
                )
            return 0
        candidates = [
            item for item in self.window_handler.list_window_candidates()
            if is_qqsg_game_window_title(item.get('title', ''))
        ]
        candidates.sort(key=lambda item: (item.get('top', 0), item.get('left', 0), item.get('pid', 0)))
        auto_detected = [
            self._candidate_window_info(candidate, index)
            for index, candidate in enumerate(candidates, 1)
        ]
        detected_ids = {item['id'] for item in auto_detected}
        manual_windows = [
            dict(item)
            for item in self.target_windows
            if item.get('source') == 'manual'
            and item.get('id') not in detected_ids
            and self._is_live_window_info(item)
        ]
        detected = auto_detected + manual_windows
        for index, info in enumerate(detected, 1):
            info['number'] = index
        previous_ids = {item['id'] for item in self.target_windows}
        detected_ids = {item['id'] for item in detected}
        selected_id = (
            self.target_window_info.get('id')
            if self.target_window_info and self.target_window_info.get('id') in detected_ids
            else (detected[0]['id'] if detected else None)
        )
        self.target_windows = detected
        for info in detected:
            self.session_states.setdefault(info['id'], 'ready')
            if self.session_states[info['id']] == 'invalid':
                self.session_states[info['id']] = 'ready'
            self.session_logs.setdefault(info['id'], [])
        for stale_id in previous_ids - detected_ids:
            self.session_states.pop(stale_id, None)
            self.session_logs.pop(stale_id, None)
            self.session_frames.pop(stale_id, None)
        self.target_window_info = None
        self._refresh_window_selector(selected_id)
        self._update_start_enabled()
        if detected:
            manual_note = f'，保留 {len(manual_windows)} 个手动窗口' if manual_windows else ''
            self._log(
                f'[多窗口] 自动识别到 {len(auto_detected)} 个 QQ 三国客户端窗口'
                f'{manual_note}；本次共绑定 {len(detected)} 个窗口'
            )
        elif not silent:
            QMessageBox.information(
                self.group_box, '未找到游戏窗口',
                '没有找到标题以“QQ三国 + 版本数字”开头的可见客户端窗口。\n'
                '如果游戏标题特殊，可使用“手动添加”。',
            )
        return len(detected)

    @staticmethod
    def _window_session_label(info: dict, state: str = '') -> str:
        suffix = f' · {state}' if state else ''
        return (
            f"{info.get('title', '未知窗口')} #{info.get('number', 1)} "
            f"· PID {info.get('pid', 0)}{suffix}"
        )

    def _refresh_window_selector(self, selected_id: str | None = None):
        if not hasattr(self, 'window_selector'):
            return
        selected_id = selected_id or (
            self.target_window_info.get('id') if self.target_window_info else None
        )
        self.window_selector.blockSignals(True)
        self.window_selector.clear()
        selected_index = -1
        for index, info in enumerate(self.target_windows):
            session_id = info['id']
            state = self.session_states.get(session_id, 'ready')
            self.window_selector.addItem(
                self._window_session_label(info, self._state_name(state)),
                session_id,
            )
            if session_id == selected_id:
                selected_index = index
        self.window_selector.blockSignals(False)
        if self.target_windows:
            self.window_selector.setCurrentIndex(
                selected_index if selected_index >= 0 else 0
            )
            self._active_window_changed(self.window_selector.currentIndex())
        else:
            self.target_window_info = None
            self.log_display.clear()
            self.preview_label.clear_image('脚本执行截图将在这里显示')

    def _active_window_changed(self, index: int):
        if index < 0 or index >= len(self.target_windows):
            self.target_window_info = None
            return
        self.target_window_info = self.target_windows[index]
        session_id = self.target_window_info['id']
        self.log_display.setPlainText('\n'.join(self.session_logs.get(session_id, [])))
        self._scroll_log_to_end()
        frame = self.session_frames.get(session_id)
        if frame is not None:
            self._render_frame(frame)
        else:
            self.preview_label.clear_image('该窗口尚无脚本截图')
        self._update_status_label()

    def remove_current_window(self):
        if not self.target_window_info:
            return
        session_id = self.target_window_info['id']
        if session_id in self.runners:
            QMessageBox.information(
                self.group_box, '窗口正在运行',
                '请先停止全部脚本，再移除该窗口。',
            )
            return
        self.target_windows = [
            item for item in self.target_windows if item['id'] != session_id
        ]
        self.session_states.pop(session_id, None)
        self.session_logs.pop(session_id, None)
        self.session_frames.pop(session_id, None)
        self.target_window_info = None
        self._refresh_window_selector()
        self._update_start_enabled()

    def _update_start_enabled(self):
        manifest = self.current_manifest()
        self.start_btn.setEnabled(
            bool(manifest and self.target_windows) or self.running
        )

    def _read_config(self) -> dict:
        if not isinstance(self.current_config, dict):
            raise ValueError('插件配置必须是 JSON 对象')
        return dict(self.current_config)

    def edit_config(self):
        manifest = self.current_manifest()
        if not manifest:
            return
        dialog = QDialog(self.group_box)
        dialog.setWindowTitle(f'{manifest.name} · 运行配置')
        dialog.resize(680, 560)
        layout = QVBoxLayout(dialog)
        hint = QLabel('修改 JSON 配置。保存后将在下次启动脚本时生效。')
        hint.setObjectName('sectionHint')
        layout.addWidget(hint)
        editor = QTextEdit()
        editor.setPlainText(json.dumps(self.current_config, ensure_ascii=False, indent=2))
        editor.setPlaceholderText('{}')
        layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存配置')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        layout.addWidget(buttons)

        def save_and_close():
            try:
                value = json.loads(editor.toPlainText().strip() or '{}')
                if not isinstance(value, dict):
                    raise ValueError('插件配置必须是 JSON 对象')
                path = self.manager.save_config(manifest, value)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                QMessageBox.warning(dialog, '配置错误', str(error))
                return
            self.current_config = value
            self._rebuild_template_controls(manifest, value)
            self._update_qqsg_data_controls(manifest, value)
            self._update_daily_task_controls(manifest, value)
            self._update_leveling_controls(manifest, value)
            self._log(f'配置已保存：{path}')
            dialog.accept()

        buttons.accepted.connect(save_and_close)
        buttons.rejected.connect(dialog.reject)
        dialog.exec_()

    def show_parsed_maps(self):
        """Display every map record parsed from the installed client package."""
        saved = self.current_config.get('route_data_source', {}).get('game_directory', '')
        installation = Path(saved) if saved else find_installation()
        if not installation or not (installation / 'data' / 'objects.pkg').is_file():
            selected = QFileDialog.getExistingDirectory(self.group_box, '选择 QQ 三国安装目录')
            if not selected:
                return
            installation = Path(selected)
        try:
            package = QQSGPackage(installation / 'data' / 'objects.pkg')
            catalog = parse_map_catalog(package.read('res/Txt/MapData.txt'))
            terrain_entries = [name.replace('\\', '/').casefold()
                               for name in package.list_entries('map/')
                               if name.casefold().endswith('.map.srv')]
            connection_candidates = package.connection_candidates()
        except (OSError, ValueError, FileNotFoundError) as error:
            QMessageBox.warning(self.group_box, '地图数据读取失败', str(error))
            return
        from feature.map_debug_dialog import MapDebugDialog

        dialog = QDialog(self.group_box)
        dialog.setWindowTitle(f'已解析地图数据 · {len(catalog)} 张')
        dialog.resize(620, 560)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            f'来源：{installation / "data" / "objects.pkg"}\n'
            f'已从客户端 MapData.txt 解析 {len(catalog)} 张地图；名称和 ID 以当前客户端为准。\n'
            f'连接关系候选资源：{len(connection_candidates)} 个（仅按文件名筛选，需进一步解析内容）。'
        ))
        search = QLineEdit()
        search.setPlaceholderText('筛选地图名称或 ID')
        layout.addWidget(search)
        listing = QListWidget()
        rows = sorted(catalog.values(), key=lambda item: (int(item['id']), str(item['name'])))

        def terrain_candidates(item):
            normalized_name = str(item.get('name', '')).replace('·', '.')
            override = MapDebugDialog.TERRAIN_ENTRY_OVERRIDES.get(normalized_name)
            resource = str(item.get('resource', '')).replace('\\', '/').casefold()
            resource_name = resource.rsplit('/', 1)[-1]
            # MapData normally stores the render resource as ``NN-N.map`` while
            # the walkable geometry is the sibling ``NN-N.map.srv``.  Resolve
            # that exact basename and verify it exists in the package; never
            # infer a terrain file from the numeric catalog ID alone.
            candidates = []
            if override:
                candidates.append(override.casefold())
            if resource_name.endswith('.map'):
                candidates.append(f'{resource_name}.srv')
            elif resource_name.endswith('.map.srv'):
                candidates.append(resource_name)
            if not candidates:
                return []
            return [entry for entry in terrain_entries
                    if entry.rsplit('/', 1)[-1] in set(candidates)]

        for item in rows:
            terrain = terrain_candidates(item)
            state = '可读取地形' if terrain else '仅目录记录'
            row = QListWidgetItem(f"ID {item['id']:>4}  ·  {item['name']}  ·  {state}")
            row.setData(Qt.UserRole, {**item, 'terrain_entries': terrain})
            row.setToolTip('\n'.join(terrain[:8]) if terrain else '未找到对应 .map.srv 文件')
            listing.addItem(row)
        layout.addWidget(listing, 1)

        def filter_rows(value):
            query = str(value or '').strip().casefold()
            for index in range(listing.count()):
                item = listing.item(index)
                data = item.data(Qt.UserRole) or {}
                haystack = f"{data.get('id', '')} {data.get('name', '')}".casefold()
                item.setHidden(bool(query and query not in haystack))

        search.textChanged.connect(filter_rows)
        def open_selected(item):
            data = item.data(Qt.UserRole) or {}
            entries = data.get('terrain_entries', [])
            if not entries:
                QMessageBox.information(dialog, '没有地形文件', '该地图只有目录记录，未找到可打开的 .map.srv 文件。')
                return
            dialog.accept()
            self.open_map_debug(data.get('name'), data.get('id'), entries[0])

        listing.itemDoubleClicked.connect(open_selected)
        export_btn = QPushButton('导出地图清单')

        def export_maps():
            path, _ = QFileDialog.getSaveFileName(
                dialog, '导出地图清单', 'qqsg_maps.json', 'JSON 文件 (*.json)'
            )
            if not path:
                return
            payload = []
            for item in rows:
                terrain = terrain_candidates(item)
                payload.append({
                    'id': item['id'],
                    'name': item['name'],
                    'terrain_available': bool(terrain),
                    'terrain_entries': terrain,
                })
            payload = {
                'maps': payload,
                'connection_candidate_entries': connection_candidates,
            }
            try:
                Path(path).write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8'
                )
                QMessageBox.information(dialog, '导出完成', f'已导出 {len(payload["maps"])} 张地图。')
            except OSError as error:
                QMessageBox.warning(dialog, '导出失败', str(error))

        export_btn.clicked.connect(export_maps)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(export_btn)
        layout.addWidget(buttons)
        dialog.exec_()

    def toggle(self):
        self.stop() if self.running else self.start()

    def start(self):
        manifest = self.current_manifest()
        if not manifest:
            return
        if not self.target_windows:
            QMessageBox.information(
                self.group_box, '未找到游戏窗口',
                '请先启动 QQ 三国客户端，或使用“手动添加”。',
            )
            return
        try:
            config = self._read_config()
            if (manifest.id == 'com.searchcat.qqsg.official-task'
                    and config.get('terrain_test_enabled', False)
                    and not config.get('terrain_test_pending', False)):
                config['terrain_test_enabled'] = False
                self.current_config = config
                self._log('[地图测试] 已清除旧测试标志，本次启动进入官爵任务流程')
            self.manager.save_config(manifest, config)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self.group_box, '配置错误', str(error))
            return
        if config.get('use_templates', False):
            missing = self._missing_templates(manifest)
            if missing:
                QMessageBox.warning(
                    self.group_box,
                    '识别模板未配置',
                    '请先导入以下模板：' + '、'.join(missing),
                )
                return
        valid_windows = []
        for info in self.target_windows:
            hwnd = int(info['hwnd'])
            if not win32gui.IsWindow(hwnd):
                self.session_states[info['id']] = 'invalid'
                self._log('[多窗口] 目标窗口已关闭，本次跳过', info['id'])
                continue
            _, live_pid = win32process.GetWindowThreadProcessId(hwnd)
            if info.get('pid') and int(live_pid) != int(info['pid']):
                self.session_states[info['id']] = 'invalid'
                self._log('[多窗口] HWND 已被其他进程复用，本次跳过', info['id'])
                continue
            valid_windows.append(info)
        if not valid_windows:
            QMessageBox.warning(self.group_box, '无可用窗口', '所有绑定窗口均已失效，请重新添加。')
            self._refresh_window_selector()
            return

        for info in valid_windows:
            session_id = info['id']
            if session_id in self.runners:
                continue
            self.session_logs[session_id] = []
            if self.target_window_info and self.target_window_info['id'] == session_id:
                self.log_display.clear()
            runner = PluginProcess(
                self.manager,
                manifest,
                deepcopy(config),
                info,
                dry_run=self.dry_run_checkbox.isChecked(),
                session_key=session_id,
                parent=self.group_box,
            )
            runner.log_received.connect(
                lambda message, sid=session_id: self._log(message, sid)
            )
            runner.event_received.connect(
                lambda event, data, sid=session_id: self._on_event(sid, event, data)
            )
            runner.frame_captured.connect(
                lambda image, sid=session_id: self._show_frame(sid, image)
            )
            runner.state_changed.connect(
                lambda state, sid=session_id: self._set_state(sid, state)
            )
            runner.finished.connect(
                lambda code, sid=session_id, instance=runner:
                self._on_finished(sid, instance, code)
            )
            self.runners[session_id] = runner
            self.session_states[session_id] = 'starting'
            runner.start()
        self._sync_running_ui()

    def stop(self):
        for session_id, runner in list(self.runners.items()):
            self.session_states[session_id] = 'stopping'
            runner.stop()
        self._sync_running_ui()

    @staticmethod
    def _state_name(state: str) -> str:
        names = {
            'starting': '正在启动', 'running': '运行中', 'completed': '已完成',
            'failed': '失败', 'stopping': '正在停止', 'stopped': '已停止',
            'ready': '待机', 'invalid': '窗口失效',
        }
        return names.get(state, state)

    def _set_state(self, session_id: str, state: str):
        self.session_states[session_id] = state
        self._refresh_window_selector(session_id if self.target_window_info and
                                      self.target_window_info['id'] == session_id else None)
        self._sync_running_ui()

    def _on_finished(self, session_id: str, runner: PluginProcess, exit_code: int):
        if self.runners.get(session_id) is not runner:
            return
        completed_test = bool(
            exit_code == 0
            and runner.manifest.id == 'com.searchcat.qqsg.official-task'
            and runner.config.get('terrain_test_pending', False)
        )
        if completed_test:
            manifest = runner.manifest
            config = self.manager.load_config(manifest)
            config['terrain_test_enabled'] = False
            config['terrain_test_pending'] = False
            self.manager.save_config(manifest, config)
            self.current_config = config
        self.runners.pop(session_id, None)
        self.session_states[session_id] = 'completed' if exit_code == 0 else 'failed'
        self._log(f'插件进程已结束，退出码 {exit_code}', session_id)
        if completed_test:
            self._log('[地图测试] 本次测试已完成并自动退出测试模式；下次启动将执行官爵任务', session_id)
        active_id = self.target_window_info.get('id') if self.target_window_info else None
        self._refresh_window_selector(active_id)
        self._sync_running_ui()

    def _log(self, message: str, session_id: str | None = None):
        if session_id:
            logs = self.session_logs.setdefault(session_id, [])
            logs.append(str(message))
            if len(logs) > 500:
                del logs[:-500]
            active_id = self.target_window_info.get('id') if self.target_window_info else None
            if active_id != session_id:
                return
        self.log_display.append(str(message))
        # QTextEdit.append() updates the document but does not reliably keep
        # the viewport at the latest block, especially while many SDK events
        # arrive in quick succession. Move both the cursor and scrollbar now,
        # then repeat after Qt has recalculated the document layout.
        self.log_display.moveCursor(QTextCursor.End)
        self.log_display.ensureCursorVisible()
        self._scroll_log_to_end()
        QTimer.singleShot(0, self._scroll_log_to_end)

    def _scroll_log_to_end(self):
        if not hasattr(self, 'log_display'):
            return
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.log_display.viewport().update()

    def _on_event(self, session_id: str, event: str, data: dict):
        if event == 'watch':
            self._log(f"[变量] {data.get('name')} = {data.get('value')}", session_id)
        elif event == 'rpc_completed':
            error = f"，错误：{data['error']}" if data.get('error') else ''
            self._log(
                f"[SDK] {data.get('method')} · {data.get('duration_ms')} ms{error}",
                session_id,
            )

    def _show_frame(self, session_id: str, image):
        height, width, channels = image.shape
        qt_image = QImage(
            image.data, width, height, channels * width, QImage.Format_RGB888,
        ).copy()
        self.session_frames[session_id] = qt_image
        active_id = self.target_window_info.get('id') if self.target_window_info else None
        if active_id != session_id:
            return
        self._render_frame(qt_image)

    def _render_frame(self, qt_image: QImage):
        self.preview_label.show_image(qt_image)

    def _update_status_label(self):
        active_id = self.target_window_info.get('id') if self.target_window_info else None
        active_state = self._state_name(self.session_states.get(active_id, 'ready')) if active_id else '未绑定'
        running_count = len(self.runners)
        self.status_label.setText(
            f'状态：{active_state} · 运行 {running_count}/{len(self.target_windows)} 窗口'
        )

    def _sync_running_ui(self):
        self.running = bool(self.runners)
        self.start_btn.setText('停止全部  Home' if self.running else '启动全部  Home')
        self.plugin_list.setEnabled(not self.running)
        self.dry_run_checkbox.setEnabled(not self.running)
        self._update_status_label()
        self._update_start_enabled()
