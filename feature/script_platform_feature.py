import json
import shutil
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox, QHBoxLayout,
                             QLabel, QListWidget, QListWidgetItem, QMessageBox,
                             QPushButton, QSplitter, QTextEdit, QVBoxLayout,
                             QWidget)

from core.winhandler import WindowHandler
from core.text import repair_utf8_gbk_mojibake
from plugin_platform.manager import PluginManager, PluginManifest
from plugin_platform.qqsg_data import find_installation, import_routes
from plugin_platform.runner import PluginProcess


class ScriptPlatformFeature:
    """Plugin discovery, configuration, window binding, and runtime UI."""

    def __init__(self, parent):
        self.parent = parent
        self.manager = PluginManager()
        self.manifests: list[PluginManifest] = []
        self.window_handler = WindowHandler()
        self.target_window_info = None
        self.runner: PluginProcess | None = None
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
        qqsg_data_layout.addWidget(self.qqsg_data_status, 1)
        qqsg_data_layout.addWidget(import_game_data_btn)
        self.qqsg_data_panel.setVisible(False)
        control_layout.addWidget(self.qqsg_data_panel)

        window_layout = QHBoxLayout()
        window_layout.setSpacing(6)
        choose_window_btn = QPushButton('绑定窗口')
        choose_window_btn.setFixedWidth(76)
        choose_window_btn.clicked.connect(self.choose_window)
        self.window_label = QLabel('未绑定窗口')
        self.window_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        window_layout.addWidget(choose_window_btn)
        window_layout.addWidget(self.window_label, 1)
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
        self.start_btn.setFixedWidth(116)
        self.start_btn.clicked.connect(self.toggle)
        self.start_btn.setEnabled(False)
        action_layout.addWidget(self.start_btn)
        control_layout.addLayout(action_layout)

        self.status_label = QLabel('状态：待机')
        self.status_label.setObjectName('scriptStatus')
        control_layout.addWidget(self.status_label)

        bottom_splitter = QSplitter(Qt.Horizontal)
        bottom_splitter.setChildrenCollapsible(False)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(5)
        log_layout.addWidget(QLabel('运行日志'))
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMinimumHeight(240)
        self.log_display.setStyleSheet('font-family: Consolas, monospace; font-size: 12px;')
        self.log_display.document().setMaximumBlockCount(500)
        log_layout.addWidget(self.log_display, 1)
        bottom_splitter.addWidget(log_panel)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(5)
        preview_layout.addWidget(QLabel('脚本截图预览'))
        self.preview_label = QLabel('脚本执行截图将在这里显示')
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(240)
        self.preview_label.setStyleSheet(
            'background: #F7F9FC; border: 1px solid #E4E9F0; border-radius: 8px;'
        )
        preview_layout.addWidget(self.preview_label, 1)
        bottom_splitter.addWidget(preview_panel)
        bottom_splitter.setSizes([420, 420])
        bottom_splitter.setStretchFactor(0, 1)
        bottom_splitter.setStretchFactor(1, 1)
        control_layout.addWidget(bottom_splitter, 1)
        root.addWidget(control_panel, 4)

        self.parent.left_layout.addWidget(self.group_box)
        self.refresh_plugins()

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
        self.qqsg_data_panel.setVisible(manifest.id == 'com.searchcat.qqsg.official-task')
        self.plugin_title.setText(f'{manifest.name}  {manifest.version}')
        permissions = '、'.join(manifest.permissions) if manifest.permissions else '无额外权限声明'
        description = f'{manifest.description}\n权限：{permissions}'
        self.plugin_description.setText(description)
        self.plugin_description.setToolTip(description)
        self._rebuild_template_controls(manifest)
        try:
            config = self.manager.load_config(manifest)
            self.current_config = config
            self._update_qqsg_data_controls(manifest, config)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.current_config = {}
            self._log(f'[配置错误] {error}')
        self._update_start_enabled()

    def _update_qqsg_data_controls(self, manifest: PluginManifest, config: dict):
        visible = manifest.id == 'com.searchcat.qqsg.official-task'
        self.qqsg_data_panel.setVisible(visible)
        if visible:
            route_count = len(config.get('npc_routes', {})) if isinstance(config.get('npc_routes'), dict) else 0
            self.qqsg_data_status.setText(f'NPC 路由库：{route_count} 条')

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
            config['npc_routes'] = {**existing, **routes}
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

    def _rebuild_template_controls(self, manifest: PluginManifest):
        while self.template_layout.count() > 2:
            item = self.template_layout.takeAt(1)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        templates = manifest.templates or []
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
        self._rebuild_template_controls(manifest)

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
        self.target_window_info = {
            'id': f"hwnd-{int(getattr(window, '_hWnd', 0))}",
            'hwnd': int(getattr(window, '_hWnd', 0)),
            'pid': int(info.get('pid', 0)),
            'title': title,
            'number': int(info.get('number', 1)),
            'left': int(window.left),
            'top': int(window.top),
            'width': int(window.right - window.left),
            'height': int(window.bottom - window.top),
        }
        self.window_label.setText(
            f"{title} #{self.target_window_info['number']} · PID {self.target_window_info['pid']}"
        )
        self._update_start_enabled()

    def _update_start_enabled(self):
        self.start_btn.setEnabled(bool(self.current_manifest() and self.target_window_info) or self.running)

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
            self._update_qqsg_data_controls(manifest, value)
            self._log(f'配置已保存：{path}')
            dialog.accept()

        buttons.accepted.connect(save_and_close)
        buttons.rejected.connect(dialog.reject)
        dialog.exec_()

    def toggle(self):
        self.stop() if self.running else self.start()

    def start(self):
        manifest = self.current_manifest()
        if not manifest or not self.target_window_info:
            return
        try:
            config = self._read_config()
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
        self.log_display.clear()
        self.runner = PluginProcess(
            self.manager,
            manifest,
            config,
            self.target_window_info,
            dry_run=self.dry_run_checkbox.isChecked(),
            parent=self.group_box,
        )
        self.runner.log_received.connect(self._log)
        self.runner.event_received.connect(self._on_event)
        self.runner.frame_captured.connect(self._show_frame)
        self.runner.state_changed.connect(self._set_state)
        self.runner.finished.connect(self._on_finished)
        self.runner.start()
        self.running = True
        self.start_btn.setText('停止  Home')
        self.plugin_list.setEnabled(False)

    def stop(self):
        if self.runner:
            self.runner.stop()
        self.status_label.setText('状态：正在停止')

    def _set_state(self, state: str):
        names = {
            'starting': '正在启动', 'running': '运行中', 'completed': '已完成',
            'failed': '失败', 'stopping': '正在停止', 'stopped': '已停止',
        }
        self.status_label.setText(f'状态：{names.get(state, state)}')

    def _on_finished(self, exit_code: int):
        self.running = False
        self.start_btn.setText('启动  Home')
        self.plugin_list.setEnabled(True)
        self._update_start_enabled()
        self._log(f'插件进程已结束，退出码 {exit_code}')
        self.runner = None

    def _log(self, message: str):
        self.log_display.append(str(message))

    def _on_event(self, event: str, data: dict):
        if event == 'watch':
            self._log(f"[变量] {data.get('name')} = {data.get('value')}")
        elif event == 'rpc_completed':
            error = f"，错误：{data['error']}" if data.get('error') else ''
            self._log(
                f"[SDK] {data.get('method')} · {data.get('duration_ms')} ms{error}"
            )

    def _show_frame(self, image):
        height, width, channels = image.shape
        qt_image = QImage(
            image.data, width, height, channels * width, QImage.Format_RGB888,
        ).copy()
        self.preview_label.setPixmap(QPixmap.fromImage(qt_image).scaled(
            self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation,
        ))
