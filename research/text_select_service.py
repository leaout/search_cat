"""Loopback-only service for authorized offline image experiments."""

import argparse
import importlib
import io
import json
import logging
import math
import secrets
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_UPLOAD = 4 * 1024 * 1024
MAX_PIXELS = 4_000_000


class ResearchRecognizer:
    """Lazy adapter to an explicitly trusted local upstream checkout."""

    def __init__(self, upstream: Path):
        self.upstream = upstream.resolve()
        self.engine = None

    def _load(self) -> None:
        if self.engine is not None:
            return
        if not (self.upstream / 'src' / 'captcha.py').is_file():
            raise RuntimeError('上游目录缺少 src/captcha.py')
        for name in ('pre_model_v7.onnx', 'best_v3.onnx'):
            if not (self.upstream / 'model' / name).is_file():
                raise RuntimeError(f'缺少上游模型：{name}')
        if 'src' in sys.modules:
            raise RuntimeError('src模块已被其他程序加载，请使用独立进程启动服务')
        sys.path.insert(0, str(self.upstream))
        try:
            module = importlib.import_module('src.captcha')
            if not Path(module.__file__).resolve().is_relative_to(self.upstream):
                raise RuntimeError('上游模块路径冲突')
            self.engine = module.TextSelectCaptcha()
        finally:
            sys.path.remove(str(self.upstream))

    def recognize(self, data: bytes) -> dict:
        if not data or len(data) > MAX_UPLOAD:
            raise ValueError('图片必须为1字节至4MiB')
        try:
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in ('PNG', 'JPEG') or source.width * source.height > MAX_PIXELS:
                    raise ValueError('仅支持PNG/JPEG，最多400万像素')
                source.load()
                image = source.convert('RGB')
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ValueError('无效图片') from error
        started = time.perf_counter()
        try:
            self._load()
            with tempfile.TemporaryDirectory(prefix='searchcat-research-') as directory:
                path = Path(directory) / 'input.png'
                image.save(path)
                result = self.engine.run_dict(str(path))
            # Convert NumPy scalar values and reject non-finite or out-of-image output.
            points = []
            for point in result['point']:
                x, y = float(point['x_rel']), float(point['y_rel'])
                if not math.isfinite(x) or not math.isfinite(y) or not 0 <= x < image.width \
                        or not 0 <= y < image.height:
                    raise RuntimeError('模型返回越界坐标')
                points.append({'x': x, 'y': y})
            return {'width': image.width, 'height': image.height, 'points': points,
                    'elapsed_ms': round((time.perf_counter() - started) * 1000, 2),
                    'purpose': 'offline_research'}
        finally:
            image.close()


def make_handler(recognizer: ResearchRecognizer, token: str):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def respond(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def authorized(self) -> bool:
            return secrets.compare_digest(self.headers.get('Authorization', ''), f'Bearer {token}')

        def do_GET(self) -> None:
            if not self.authorized():
                self.respond(401, {'error': 'Unauthorized'})
            elif self.path == '/health':
                self.respond(200, {'status': 'ok', 'model_loaded': recognizer.engine is not None})
            else:
                self.respond(404, {'error': 'Not found'})

        def do_POST(self) -> None:
            if not self.authorized():
                self.respond(401, {'error': 'Unauthorized'})
                return
            if self.path != '/recognize':
                self.respond(404, {'error': 'Not found'})
                return
            if self.headers.get('Content-Type', '').split(';')[0] not in ('image/png', 'image/jpeg'):
                self.respond(415, {'error': 'Upload raw PNG/JPEG bytes; no URLs or file paths'})
                return
            try:
                lengths = self.headers.get_all('Content-Length', [])
                if len(lengths) != 1 or self.headers.get('Transfer-Encoding'):
                    raise ValueError('需要唯一Content-Length，不支持分块传输')
                length = int(lengths[0])
                if not 0 < length <= MAX_UPLOAD:
                    self.respond(413, {'error': 'Upload limit: 4MiB'})
                    return
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('上传不完整')
                self.respond(200, recognizer.recognize(data))
            except (ValueError, TimeoutError) as error:
                self.respond(400, {'error': str(error)})
            except Exception:
                logging.exception('Offline research inference failed')
                self.respond(503, {'error': '模型不可用或推理失败，请查看服务端日志'})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', required=True, type=Path, help='Trusted upstream source directory')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    token = secrets.token_urlsafe(32)
    server = HTTPServer(('127.0.0.1', args.port), make_handler(ResearchRecognizer(args.upstream), token))
    print(f'Offline research service: http://127.0.0.1:{args.port}', flush=True)
    print(f'Bearer token: {token}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
