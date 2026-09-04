import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plugin_platform.manager import PluginManifest
from plugin_platform.protocol import encode_json_line, sanitize_unicode


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ProtocolEncodingTests(unittest.TestCase):
    def test_lone_surrogate_is_replaced_in_nested_message(self):
        message = {'data': {'title': 'QQ三国\udc80窗口'}, 'items': ['正常', '\ud800']}

        payload = encode_json_line(message)
        decoded = json.loads(payload.decode('utf-8'))

        self.assertEqual(decoded['data']['title'], 'QQ三国?窗口')
        self.assertEqual(decoded['items'][1], '?')
        self.assertEqual(sanitize_unicode('标题\udc80'), '标题?')


class PluginManifestTests(unittest.TestCase):
    def test_example_manifest_is_valid(self):
        directory = PROJECT_ROOT / 'plugins' / 'com.searchcat.example'
        manifest = PluginManifest.load(directory)
        self.assertEqual(manifest.id, 'com.searchcat.example')
        self.assertEqual(manifest.sdk_version, '1')

    def test_qqsg_official_task_manifest_is_valid(self):
        directory = PROJECT_ROOT / 'plugins' / 'com.searchcat.qqsg.official_task'
        manifest = PluginManifest.load(directory)
        self.assertEqual(manifest.id, 'com.searchcat.qqsg.official-task')
        self.assertIn('keyboard.background', manifest.permissions)


class PluginWorkerTests(unittest.TestCase):
    def test_example_plugin_completes_over_rpc(self):
        plugin_directory = PROJECT_ROOT / 'plugins' / 'com.searchcat.example'
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / 'config.json'
            config_path.write_text(json.dumps({
                'capture_mode': 'auto',
                'sample_x': 10,
                'sample_y': 20,
                'perform_click': False,
            }), encoding='utf-8')
            child_environment = os.environ.copy()
            child_environment['PYTHONIOENCODING'] = 'gbk'
            process = subprocess.Popen(
                [
                    sys.executable, '-u', '-m', 'plugin_platform.worker',
                    '--plugin-directory', str(plugin_directory),
                    '--entry', 'main.py',
                    '--config', str(config_path),
                    '--dry-run',
                ],
                cwd=PROJECT_ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                env=child_environment,
            )
            completed = False
            bound_window_log = ''
            try:
                for _ in range(100):
                    line = process.stdout.readline()
                    if not line:
                        break
                    message = json.loads(line)
                    if message.get('type') == 'rpc':
                        method = message['method']
                        responses = {
                            'window.current': {
                                'id': 'test', 'title': 'QQ三国 抚琴退敌 7线', 'pid': 1,
                            },
                            'capture.window': {
                                'id': 'frame', 'width': 100, 'height': 100,
                                'capture_mode': 'background', 'coordinate_space': 'window',
                                'timestamp': 1.0,
                            },
                            'vision.get_color': [10, 20, 30],
                            'storage.read_json': 0,
                            'storage.write_json': {'path': 'run_count.json'},
                        }
                        response = {
                            'type': 'rpc_result',
                            'id': message['id'],
                            'result': responses[method],
                            'error': None,
                        }
                        process.stdin.write(json.dumps(response, ensure_ascii=False) + '\n')
                        process.stdin.flush()
                    elif message.get('event') == 'log':
                        log_message = str(message.get('data', {}).get('message', ''))
                        if log_message.startswith('绑定窗口：'):
                            bound_window_log = log_message
                    elif message.get('event') == 'state' and message.get('data', {}).get('status') == 'completed':
                        completed = True
                exit_code = process.wait(timeout=5)
                stderr = process.stderr.read()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                process.stdin.close()
                process.stdout.close()
                process.stderr.close()
            self.assertEqual(exit_code, 0, stderr)
            self.assertTrue(completed)
            self.assertIn('QQ三国 抚琴退敌 7线', bound_window_log)

    def test_qqsg_official_task_dry_run_completes(self):
        plugin_directory = PROJECT_ROOT / 'plugins' / 'com.searchcat.qqsg.official_task'
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / 'config.json'
            config_path.write_text(json.dumps({
                'calibrated': False,
                'input_mode': 'foreground',
                'capture_mode': 'auto',
                'task_region': [520, 70, 270, 430],
                'task_keyword': '官爵',
                'accept_point': [400, 500],
                'continue_point': [400, 500],
                'complete_point': [400, 500],
                'navigation_wait': 12,
                'completion_confirm_scans': 2,
                'dialog_wait': 1,
                'template_threshold': 0.85,
                'use_templates': False,
                'allow_coordinate_fallback': False,
            }), encoding='utf-8')
            process = subprocess.Popen(
                [
                    sys.executable, '-u', '-m', 'plugin_platform.worker',
                    '--plugin-directory', str(plugin_directory),
                    '--entry', 'main.py', '--config', str(config_path), '--dry-run',
                ],
                cwd=PROJECT_ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
            )
            completed = False
            ocr_calls = 0
            try:
                for _ in range(200):
                    line = process.stdout.readline()
                    if not line:
                        break
                    message = json.loads(line)
                    if message.get('type') == 'rpc':
                        method = message['method']
                        if method == 'window.is_alive':
                            result = True
                        elif method == 'capture.window':
                            result = {
                                'id': 'frame', 'width': 270, 'height': 430,
                                'capture_mode': 'background', 'coordinate_space': 'client',
                                'timestamp': 1.0,
                            }
                        elif method == 'ocr.recognize':
                            ocr_calls += 1
                            result = ([{
                                'text': '官爵任务：寻找张飞',
                                'confidence': 0.99,
                                'box': [[0, 0], [200, 0], [200, 30], [0, 30]],
                                'center': [100, 15],
                            }] if ocr_calls == 1 else [])
                        else:
                            result = {'executed': False, 'dry_run': True}
                        response = {
                            'type': 'rpc_result', 'id': message['id'],
                            'result': result, 'error': None,
                        }
                        process.stdin.write(json.dumps(response) + '\n')
                        process.stdin.flush()
                    elif message.get('event') == 'state' and message.get('data', {}).get('status') == 'completed':
                        completed = True
                exit_code = process.wait(timeout=5)
                stderr = process.stderr.read()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                process.stdin.close()
                process.stdout.close()
                process.stderr.close()
            self.assertEqual(exit_code, 0, stderr)
            self.assertTrue(completed)


if __name__ == '__main__':
    unittest.main()
