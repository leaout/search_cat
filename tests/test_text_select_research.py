"""Offline research adapter tests; no third-party models or desktop APIs."""
import io
import http.client
import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import Mock

from PIL import Image
from research.text_select_service import MAX_UPLOAD, ResearchRecognizer, make_handler


class ResearchTests(unittest.TestCase):
    def test_http_authorization_health_and_upload(self):
        adapter = Mock()
        adapter.engine = None
        adapter.recognize.return_value = {'points': [], 'purpose': 'offline_research'}
        server = HTTPServer(('127.0.0.1', 0), make_handler(adapter, 'test-token'))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        try:
            connection.request('GET', '/health')
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            headers = {'Authorization': 'Bearer test-token', 'Content-Type': 'image/png'}
            connection.request('POST', '/recognize', self.image(), headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())['purpose'], 'offline_research')
            adapter.recognize.assert_called_once_with(self.image())
            connection.request('POST', '/recognize', b'http://example.com',
                               {**headers, 'Content-Type': 'application/json'})
            response = connection.getresponse()
            self.assertEqual(response.status, 415)
            response.read()
            self.assertEqual(adapter.recognize.call_count, 1)
        finally:
            connection.close()
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

    def image(self):
        stream = io.BytesIO()
        with Image.new('RGB', (30, 20)) as image:
            image.save(stream, format='PNG')
        return stream.getvalue()

    def test_result_and_temporary_image_cleanup(self):
        adapter = ResearchRecognizer(Path('.'))
        adapter.engine = Mock()
        paths = []
        def run(path):
            self.assertTrue(Path(path).is_file())
            paths.append(path)
            return {'point': [{'x_rel': 4, 'y_rel': 8}]}
        adapter.engine.run_dict.side_effect = run
        result = adapter.recognize(self.image())
        self.assertEqual(result['points'], [{'x': 4.0, 'y': 8.0}])
        self.assertEqual((result['width'], result['height']), (30, 20))
        self.assertFalse(Path(paths[0]).exists())

    def test_invalid_upload_never_loads_model(self):
        adapter = ResearchRecognizer(Path('.'))
        adapter._load = Mock()
        for data in (b'', b'invalid', b'x' * (MAX_UPLOAD + 1)):
            with self.assertRaises(ValueError):
                adapter.recognize(data)
        adapter._load.assert_not_called()

    def test_missing_checkout_fails_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = ResearchRecognizer(Path(directory))
            with self.assertRaisesRegex(RuntimeError, 'captcha.py'):
                adapter.recognize(self.image())

    def test_output_bounds_validated(self):
        adapter = ResearchRecognizer(Path('.'))
        adapter.engine = Mock()
        for x in (-1, 30, float('nan')):
            adapter.engine.run_dict.return_value = {'point': [{'x_rel': x, 'y_rel': 5}]}
            with self.assertRaises(RuntimeError):
                adapter.recognize(self.image())
