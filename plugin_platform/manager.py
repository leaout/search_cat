import json
import os
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    sdk_version: str
    entry: str
    description: str
    permissions: list[str]
    directory: Path
    config_schema: str | None = None
    templates: list[dict[str, str]] | None = None

    @classmethod
    def load(cls, directory: Path) -> 'PluginManifest':
        manifest_path = directory / 'plugin.json'
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
        required = ('id', 'name', 'version', 'sdk_version', 'entry')
        missing = [field for field in required if not data.get(field)]
        if missing:
            raise ValueError(f'{manifest_path} 缺少字段: {", ".join(missing)}')
        plugin_id = str(data['id'])
        if not all(character.isalnum() or character in '._-' for character in plugin_id):
            raise ValueError(f'插件 ID 包含非法字符: {plugin_id}')
        entry = (directory / str(data['entry'])).resolve()
        if directory.resolve() not in entry.parents or not entry.is_file():
            raise ValueError(f'插件入口无效: {data["entry"]}')
        templates = []
        for definition in data.get('templates', []):
            if not isinstance(definition, dict):
                raise ValueError('templates 中的项目必须是对象')
            template_id = str(definition.get('id', '')).strip()
            template_name = str(definition.get('name', '')).strip()
            template_path = Path(str(definition.get('path', '')))
            if not template_id or not template_name or not str(template_path):
                raise ValueError('模板必须包含 id、name 和 path')
            if template_path.is_absolute() or '..' in template_path.parts:
                raise ValueError(f'模板路径无效: {template_path}')
            templates.append({
                'id': template_id,
                'name': template_name,
                'path': template_path.as_posix(),
            })
        return cls(
            id=plugin_id,
            name=str(data['name']),
            version=str(data['version']),
            sdk_version=str(data['sdk_version']),
            entry=str(data['entry']),
            description=str(data.get('description', '')),
            permissions=[str(value) for value in data.get('permissions', [])],
            directory=directory.resolve(),
            config_schema=data.get('config_schema'),
            templates=templates,
        )


class PluginManager:
    """Discover plugins and allocate isolated writable data directories."""

    def __init__(self, portable: bool | None = None):
        application_root = Path(sys.argv[0]).resolve().parent
        if portable is None:
            portable = (application_root / 'portable.flag').exists() or not getattr(sys, 'frozen', False)
        if portable:
            self.root = Path.cwd()
        else:
            local_app_data = Path(os.environ.get('LOCALAPPDATA', application_root))
            self.root = local_app_data / 'SearchCat'
        self.plugins_directory = self.root / 'plugins'
        self.data_directory = self.root / 'plugin_data'
        self.plugins_directory.mkdir(parents=True, exist_ok=True)
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self._install_bundled_plugins(application_root)

    def _install_bundled_plugins(self, application_root: Path) -> None:
        if self.plugins_directory.resolve() == (application_root / 'plugins').resolve():
            return
        bundled_directory = application_root / 'plugins'
        if not bundled_directory.is_dir():
            return
        for source in bundled_directory.iterdir():
            destination = self.plugins_directory / source.name
            if source.is_dir() and (source / 'plugin.json').is_file() and not destination.exists():
                shutil.copytree(source, destination)

    def discover(self) -> tuple[list[PluginManifest], list[str]]:
        manifests = []
        errors = []
        for directory in sorted(self.plugins_directory.iterdir()):
            if not directory.is_dir() or not (directory / 'plugin.json').is_file():
                continue
            try:
                manifests.append(PluginManifest.load(directory))
            except (OSError, ValueError, json.JSONDecodeError) as error:
                errors.append(f'{directory.name}: {error}')
        return manifests, errors

    def plugin_data_directory(self, plugin_id: str) -> Path:
        directory = (self.data_directory / plugin_id).resolve()
        if self.data_directory.resolve() not in directory.parents:
            raise ValueError('插件数据目录无效')
        for child in ('config', 'profiles', 'data', 'cache', 'logs', 'screenshots', 'runs', 'temp'):
            (directory / child).mkdir(parents=True, exist_ok=True)
        return directory

    def load_config(self, manifest: PluginManifest, profile: str = 'default') -> dict[str, Any]:
        config_path = self.plugin_data_directory(manifest.id) / 'profiles' / f'{profile}.json'
        if not config_path.exists():
            return self._default_config(manifest)
        saved = json.loads(config_path.read_text(encoding='utf-8'))
        if not isinstance(saved, dict):
            raise ValueError(f'插件配置必须是 JSON 对象: {config_path}')
        config = self._default_config(manifest)
        config.update(saved)
        return config

    def save_config(self, manifest: PluginManifest, config: dict[str, Any], profile: str = 'default') -> Path:
        config_path = self.plugin_data_directory(manifest.id) / 'profiles' / f'{profile}.json'
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        return config_path

    @staticmethod
    def _default_config(manifest: PluginManifest) -> dict[str, Any]:
        if not manifest.config_schema:
            return {}
        schema_path = manifest.directory / manifest.config_schema
        if not schema_path.is_file():
            return {}
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
        return {
            name: definition['default']
            for name, definition in schema.get('properties', {}).items()
            if 'default' in definition
        }

    def install(self, source: Path) -> PluginManifest:
        source = source.resolve()
        staging = self.root / 'temp_plugin_install'
        if staging.exists():
            shutil.rmtree(staging)
        try:
            if source.is_dir():
                shutil.copytree(source, staging)
            elif source.suffix.lower() == '.zip':
                staging.mkdir(parents=True)
                with zipfile.ZipFile(source) as archive:
                    for member in archive.infolist():
                        target = (staging / member.filename).resolve()
                        if staging.resolve() not in target.parents and target != staging.resolve():
                            raise ValueError('插件压缩包包含越界路径')
                    archive.extractall(staging)
            else:
                raise ValueError('请选择插件目录或 ZIP 文件')
            candidates = [staging] + [path for path in staging.iterdir() if path.is_dir()]
            plugin_root = next((path for path in candidates if (path / 'plugin.json').is_file()), None)
            if plugin_root is None:
                raise ValueError('没有找到 plugin.json')
            manifest = PluginManifest.load(plugin_root)
            destination = self.plugins_directory / manifest.id
            if destination.exists():
                raise FileExistsError(f'插件已存在: {manifest.id}')
            shutil.move(str(plugin_root), destination)
            return PluginManifest.load(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
