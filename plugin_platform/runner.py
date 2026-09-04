import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

from automation.services import AutomationHost
from core.text import repair_utf8_gbk_mojibake
from plugin_platform.manager import PluginManifest, PluginManager
from plugin_platform.protocol import encode_json_line, sanitize_unicode


class PluginProcess(QObject):
    """Manage one isolated plugin worker process and its host RPC calls."""

    event_received = pyqtSignal(str, object)
    log_received = pyqtSignal(str)
    state_changed = pyqtSignal(str)
    finished = pyqtSignal(int)
    frame_captured = pyqtSignal(object)

    def __init__(
        self,
        manager: PluginManager,
        manifest: PluginManifest,
        config: dict[str, Any],
        window_info: dict[str, Any],
        dry_run: bool = True,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.manager = manager
        self.manifest = manifest
        self.config = config
        self.window_info = dict(window_info)
        self.window_info['title'] = repair_utf8_gbk_mojibake(
            str(self.window_info.get('title', ''))
        )
        self.dry_run = dry_run
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(lambda error: self.log_received.emit(f'运行器错误: {error}'))
        self.stdout_buffer = ''
        self.run_directory = self._create_run_directory()
        self.event_path = self.run_directory / 'events.jsonl'
        self.log_path = self.run_directory / 'run.log'
        self.config_path = self.run_directory / 'config.json'
        self.config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        self.host = AutomationHost(
            manifest.directory,
            manager.plugin_data_directory(manifest.id),
            manifest.permissions,
            dry_run=dry_run,
        )
        self.host.register_window(self.window_info)

    def _create_run_directory(self) -> Path:
        stamp = time.strftime('%Y%m%d_%H%M%S')
        directory = self.manager.plugin_data_directory(self.manifest.id) / 'runs' / f'{stamp}_{uuid.uuid4().hex[:6]}'
        directory.mkdir(parents=True)
        return directory

    def start(self) -> None:
        if self.process.state() != QProcess.NotRunning:
            return
        environment = QProcessEnvironment.systemEnvironment()
        project_root = str(Path(__file__).resolve().parent.parent)
        current_python_path = environment.value('PYTHONPATH')
        environment.insert('PYTHONPATH', project_root + (f';{current_python_path}' if current_python_path else ''))
        self.process.setProcessEnvironment(environment)
        arguments = [
            '--plugin-directory', str(self.manifest.directory),
            '--entry', self.manifest.entry,
            '--config', str(self.config_path),
        ]
        if getattr(sys, 'frozen', False):
            arguments.insert(0, '--plugin-worker')
        else:
            arguments[0:0] = ['-u', '-m', 'plugin_platform.worker']
        if self.dry_run:
            arguments.append('--dry-run')
        self.state_changed.emit('starting')
        self.process.start(sys.executable, arguments)

    def stop(self) -> None:
        if self.process.state() == QProcess.NotRunning:
            return
        self.state_changed.emit('stopping')
        self.process.terminate()
        QTimer.singleShot(2000, self._kill_if_running)

    def _kill_if_running(self) -> None:
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()

    def _read_stdout(self) -> None:
        self.stdout_buffer += bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        while '\n' in self.stdout_buffer:
            line, self.stdout_buffer = self.stdout_buffer.split('\n', 1)
            if line.strip():
                self._handle_message(line)

    def _read_stderr(self) -> None:
        text = bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace').strip()
        if text:
            self._append_log(text)

    def _handle_message(self, line: str) -> None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            self._append_log(f'无法解析运行器输出: {line}')
            return
        self._write_event(message)
        if message.get('type') == 'rpc':
            started = time.monotonic()
            try:
                result = self.host.dispatch(message['method'], message.get('params') or {})
                error = None
            except Exception as exception:
                result = None
                error = str(exception)
            response = {'type': 'rpc_result', 'id': message['id'], 'result': result, 'error': error}
            self.process.write(encode_json_line(response))
            self.process.waitForBytesWritten(1000)
            completed = {
                'type': 'rpc_completed',
                'method': message['method'],
                'duration_ms': round((time.monotonic() - started) * 1000, 2),
                'params': message.get('params') or {},
                'result': result,
                'error': error,
            }
            self._write_event(completed)
            self.event_received.emit('rpc_completed', completed)
            if message['method'] == 'capture.window' and result and not error:
                self.frame_captured.emit(self.host.frames[result['id']].copy())
            return
        if message.get('type') != 'event':
            return
        event = str(message.get('event', 'event'))
        data = message.get('data') or {}
        self.event_received.emit(event, data)
        if event == 'log':
            self._append_log(f"[{data.get('level', 'info')}] {data.get('message', '')}")
        elif event == 'state':
            self.state_changed.emit(str(data.get('status', 'unknown')))
        elif event == 'error':
            self._append_log(f"[error] {data.get('message', '')}\n{data.get('traceback', '')}")
        elif event.startswith('step_'):
            self._append_log(f'[{event}] {data}')

    def _write_event(self, message: dict[str, Any]) -> None:
        record = sanitize_unicode({'time': time.time(), **message})
        with self.event_path.open('a', encoding='utf-8') as file:
            file.write(json.dumps(record, ensure_ascii=False) + '\n')

    def _append_log(self, text: str) -> None:
        text = sanitize_unicode(str(text))
        with self.log_path.open('a', encoding='utf-8') as file:
            file.write(text + '\n')
        self.log_received.emit(text)

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        self.state_changed.emit('stopped' if exit_code != 0 else 'completed')
        self.finished.emit(exit_code)
