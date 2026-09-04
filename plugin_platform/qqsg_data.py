"""Read-only QQSG package helpers used by the official-task plugin."""

import json
import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path


MAP_DATA_PATH = 'res\\Txt\\MapData.txt'
PACKAGE_MAGIC = 100


@dataclass(frozen=True)
class PackageEntry:
    name: str
    offset: int
    size: int
    compressed_size: int


class QQSGPackage:
    """Read individual files from a QQSG ``objects.pkg`` without extracting it."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _find_entry(self, wanted_name: str) -> PackageEntry:
        file_size = self.path.stat().st_size
        wanted = wanted_name.replace('/', '\\').casefold()
        with self.path.open('rb') as stream:
            header = stream.read(16)
            if len(header) != 16:
                raise ValueError('objects.pkg 文件头不完整')
            magic, count, table_offset, table_size = struct.unpack('<4I', header)
            if magic != PACKAGE_MAGIC:
                raise ValueError(f'不支持的 objects.pkg 格式（标记 {magic}）')
            if count > 2_000_000 or table_offset + table_size > file_size:
                raise ValueError('objects.pkg 索引越界或已经损坏')
            stream.seek(table_offset)
            table = stream.read(table_size)
        cursor = 0
        for _ in range(count):
            if cursor + 2 > len(table):
                break
            name_length = struct.unpack_from('<H', table, cursor)[0]
            cursor += 2
            entry_end = cursor + name_length + 16
            if entry_end > len(table):
                raise ValueError('objects.pkg 文件索引不完整')
            raw_name = table[cursor:cursor + name_length]
            cursor += name_length
            _flag, offset, size, compressed_size = struct.unpack_from('<4I', table, cursor)
            cursor += 16
            name = raw_name.decode('gb18030', errors='replace')
            if name.replace('/', '\\').casefold() == wanted:
                if offset + compressed_size > file_size:
                    raise ValueError(f'{name} 的数据范围越界')
                return PackageEntry(name, offset, size, compressed_size)
        raise FileNotFoundError(f'游戏包中没有找到 {wanted_name}')

    def read(self, name: str) -> bytes:
        entry = self._find_entry(name)
        with self.path.open('rb') as stream:
            stream.seek(entry.offset)
            payload = stream.read(entry.compressed_size)
        if entry.compressed_size != entry.size:
            try:
                payload = zlib.decompress(payload)
            except zlib.error as error:
                raise ValueError(f'{entry.name} 解压失败：{error}') from error
        if len(payload) != entry.size:
            raise ValueError(f'{entry.name} 解压尺寸不正确')
        return payload


def normalize_map_name(value: str) -> str:
    """Normalize punctuation used differently by the client and old coordinate lists."""
    return ''.join(value.strip().replace('．', '.').replace('·', '.').split()).casefold()


def parse_map_data(payload: bytes) -> dict[str, int]:
    """Return normalized map-name to current client map-ID mappings."""
    text = payload.decode('gb18030', errors='strict').lstrip('\ufeff')
    result: dict[str, int] = {}
    for line in text.splitlines():
        columns = line.strip().split()
        if len(columns) < 3:
            continue
        try:
            map_id = int(columns[0])
        except ValueError:
            continue
        map_name = normalize_map_name(columns[2])
        if map_name:
            result.setdefault(map_name, map_id)
    if not result:
        raise ValueError('MapData.txt 中没有解析到地图记录')
    return result


def find_installation() -> Path | None:
    """Locate QQSG from uninstall registry entries and common WeGame folders."""
    candidates: list[Path] = []
    if os.name == 'nt':
        try:
            import winreg

            roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
            views = (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY)
            key_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
            for root in roots:
                for view in views:
                    try:
                        key = winreg.OpenKey(root, key_path, 0, winreg.KEY_READ | view)
                    except OSError:
                        continue
                    with key:
                        for index in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                subkey = winreg.OpenKey(key, winreg.EnumKey(key, index))
                                name = str(winreg.QueryValueEx(subkey, 'DisplayName')[0])
                                location = str(winreg.QueryValueEx(subkey, 'InstallLocation')[0])
                            except OSError:
                                continue
                            if 'QQ三国' in name and location:
                                candidates.append(Path(location.strip('" ')))
        except (ImportError, OSError):
            pass
    for drive in 'CDEFG':
        candidates.append(Path(f'{drive}:\\WeGameApps\\QQ三国'))
    return next((path for path in candidates if (path / 'data' / 'objects.pkg').is_file()), None)


def load_npc_locations(path: Path) -> list[dict]:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, list):
        raise ValueError('NPC 坐标文件必须是 JSON 数组')
    return value


def build_routes(map_ids: dict[str, int], locations: list[dict]) -> tuple[dict, dict]:
    """Join public NPC coordinates to IDs parsed from the installed game client."""
    candidates: dict[str, list[list[int]]] = {}
    unmatched: list[str] = []
    invalid = 0
    for item in locations:
        try:
            name = str(item['name']).strip()
            map_name = str(item['map']).strip()
            x, y = int(item['x']), int(item['y'])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        map_id = map_ids.get(normalize_map_name(map_name))
        if map_id is None:
            unmatched.append(f'{name}@{map_name}')
            continue
        candidates.setdefault(name, []).append([map_id, x, y])
    routes = {name: values[0] for name, values in candidates.items() if len(set(map(tuple, values))) == 1}
    conflicts = {name: values for name, values in candidates.items() if len(set(map(tuple, values))) > 1}
    return routes, {
        'maps': len(map_ids), 'locations': len(locations), 'routes': len(routes),
        'unmatched': unmatched, 'conflicts': conflicts, 'invalid': invalid,
    }


def import_routes(install_dir: Path, location_file: Path) -> tuple[dict, dict]:
    package_path = Path(install_dir) / 'data' / 'objects.pkg'
    if not package_path.is_file():
        raise FileNotFoundError(f'没有找到 {package_path}')
    map_ids = parse_map_data(QQSGPackage(package_path).read(MAP_DATA_PATH))
    return build_routes(map_ids, load_npc_locations(location_file))
