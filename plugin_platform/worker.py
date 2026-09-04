import argparse
import importlib.util
import json
import sys
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from plugin_platform.sdk import PluginContext
from plugin_platform.protocol import encode_json_line


class ProtocolWriter:
    """Redirect plugin prints into protocol log events."""

    def __init__(self, emit):
        self.emit = emit
        self.buffer = ''

    def write(self, text: str) -> int:
        self.buffer += text
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if line:
                self.emit('log', {'level': 'info', 'message': line})
        return len(text)

    def flush(self) -> None:
        if self.buffer:
            self.emit('log', {'level': 'info', 'message': self.buffer})
            self.buffer = ''


def send(message: dict) -> None:
    sys.__stdout__.buffer.write(encode_json_line(message))
    sys.__stdout__.buffer.flush()


def emit(event: str, data: dict) -> None:
    send({'type': 'event', 'event': event, 'data': data})


def call(method: str, params: dict):
    request_id = uuid.uuid4().hex
    send({'type': 'rpc', 'id': request_id, 'method': method, 'params': params})
    while True:
        # A frozen GUI process inherits the Windows ANSI code page for the
        # text wrapper even though the host protocol is always UTF-8. Read the
        # pipe as bytes so Chinese RPC results cannot be decoded as GBK.
        line_bytes = sys.stdin.buffer.readline()
        if not line_bytes:
            raise RuntimeError('宿主连接已经关闭')
        line = line_bytes.decode('utf-8')
        response = json.loads(line)
        if response.get('type') != 'rpc_result' or response.get('id') != request_id:
            continue
        if response.get('error'):
            raise RuntimeError(str(response['error']))
        return response.get('result')


def load_plugin(plugin_directory: Path, entry: str):
    entry_path = (plugin_directory / entry).resolve()
    if plugin_directory.resolve() not in entry_path.parents:
        raise ValueError('插件入口不能离开插件目录')
    spec = importlib.util.spec_from_file_location(f'search_cat_plugin_{plugin_directory.name}', entry_path)
    if not spec or not spec.loader:
        raise ImportError(f'无法加载插件入口: {entry}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--plugin-directory', type=Path, required=True)
    parser.add_argument('--entry', required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(arguments)
    config = json.loads(args.config.read_text(encoding='utf-8'))
    context = PluginContext(call, emit, config, args.dry_run)
    writer = ProtocolWriter(emit)
    try:
        with redirect_stdout(writer), redirect_stderr(writer):
            plugin = load_plugin(args.plugin_directory, args.entry)
            if hasattr(plugin, 'on_load'):
                plugin.on_load(context)
            emit('state', {'status': 'running'})
            if not hasattr(plugin, 'on_start'):
                raise AttributeError('插件必须提供 on_start(context)')
            plugin.on_start(context)
            if hasattr(plugin, 'on_stop'):
                plugin.on_stop(context)
            if hasattr(plugin, 'on_unload'):
                plugin.on_unload(context)
        emit('state', {'status': 'completed'})
        return 0
    except Exception as error:
        emit('error', {'message': str(error), 'traceback': traceback.format_exc()})
        emit('state', {'status': 'failed'})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
