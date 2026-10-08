"""Single-line RPC checks without Windows input, model loading, or screenshots."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from plugin_platform.sdk import Frame, OCRAPI


class FakeImage:
    """Supply just the array shape needed by coordinate conversion."""

    def __init__(self, height: int, width: int):
        self.shape = (height, width, 3)


def fake_cv2():
    def resize(image, destination, fx, fy, interpolation):
        return FakeImage(round(image.shape[0] * fy), round(image.shape[1] * fx))

    def border(image, top, bottom, left, right, border_type, value):
        return FakeImage(image.shape[0] + top + bottom, image.shape[1] + left + right)

    return SimpleNamespace(
        COLOR_RGB2BGR=1,
        COLOR_RGB2HSV=2,
        COLOR_GRAY2BGR=3,
        INTER_CUBIC=4,
        BORDER_CONSTANT=5,
        cvtColor=Mock(side_effect=lambda image, conversion: image),
        resize=Mock(side_effect=resize),
        copyMakeBorder=Mock(side_effect=border),
    )


def host_method(cv2):
    source = Path(__file__).resolve().parents[1] / 'automation' / 'services.py'
    module = ast.parse(source.read_text(encoding='utf-8'))
    host = next(node for node in module.body
                if isinstance(node, ast.ClassDef) and node.name == 'AutomationHost')
    method = next(node for node in host.body
                  if isinstance(node, ast.FunctionDef) and node.name == '_ocr_recognize')
    namespace = {'Any': Any, 'cv2': cv2}
    extracted = ast.Module(body=[method], type_ignores=[])
    exec(compile(ast.fix_missing_locations(extracted), str(source), 'exec'), namespace)
    return namespace['_ocr_recognize']


def whole_image_result(image, text='1', confidence=0.95):
    height, width = image.shape[:2]
    return [[[[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
             (text, confidence)]]


class OCRSingleLineTests(unittest.TestCase):
    def setUp(self):
        self.image = FakeImage(20, 70)
        self.cv2 = fake_cv2()
        self.engine = Mock()
        self.engine.do_ocr_line.side_effect = whole_image_result
        method = host_method(self.cv2)
        self.host = SimpleNamespace(_frame=Mock(return_value=self.image), _ocr_engine=self.engine)
        self.recognize = lambda params: method(self.host, params)
        self.frame = Frame('crop-1', 70, 20, 'foreground', 'client', 0)

    def test_sdk_default_payload_is_backward_compatible(self):
        call = Mock(return_value=[])
        OCRAPI(call).recognize(self.frame)
        call.assert_called_once_with('ocr.recognize', {
            'frame_id': 'crop-1', 'min_confidence': 0.5, 'preprocess': 'none'})

    def test_sdk_explicit_false_does_not_add_optional_payload_key(self):
        call = Mock(return_value=[])
        OCRAPI(call).recognize(self.frame, min_confidence=0.7,
                               preprocess='task_scale', single_line=False)
        call.assert_called_once_with('ocr.recognize', {
            'frame_id': 'crop-1', 'min_confidence': 0.7, 'preprocess': 'task_scale'})

    def test_sdk_true_adds_single_line_flag(self):
        call = Mock(return_value=[])
        OCRAPI(call).recognize(self.frame, min_confidence=0.8, single_line=True)
        call.assert_called_once_with('ocr.recognize', {
            'frame_id': 'crop-1', 'min_confidence': 0.8,
            'preprocess': 'none', 'single_line': True})

    def test_single_line_bypasses_full_text_detection(self):
        result = self.recognize({'frame_id': 'crop-1', 'single_line': True})
        self.engine.do_ocr_line.assert_called_once_with(self.image)
        self.engine.do_ocr_ext.assert_not_called()
        self.host._frame.assert_called_once_with('crop-1')
        self.assertEqual(result[0]['text'], '1')
        self.assertEqual(result[0]['confidence'], 0.95)

    def test_single_line_returns_crop_local_full_image_box_and_center(self):
        result = self.recognize({'frame_id': 'crop-1', 'single_line': True})
        self.assertEqual(result[0]['box'], [[0, 0], [69, 0], [69, 19], [0, 19]])
        self.assertEqual(result[0]['center'], [34, 9])
        # The crop's desktop/client origin is deliberately not added here.
        self.assertLess(result[0]['center'][0], self.frame.width)
        self.assertLess(result[0]['center'][1], self.frame.height)

    def test_single_line_confidence_is_filtered(self):
        self.engine.do_ocr_line.side_effect = lambda image: whole_image_result(image, '1', 0.49)
        self.assertEqual(self.recognize({'frame_id': 'crop-1', 'single_line': True,
                                        'min_confidence': 0.5}), [])
        self.engine.do_ocr_ext.assert_not_called()

    def test_single_line_confidence_boundary_is_accepted(self):
        self.engine.do_ocr_line.side_effect = lambda image: whole_image_result(image, '1', 0.8)
        result = self.recognize({'frame_id': 'crop-1', 'single_line': True, 'min_confidence': 0.8})
        self.assertEqual(result[0]['text'], '1')

    def test_single_line_empty_result_is_safe(self):
        self.engine.do_ocr_line.side_effect = None
        for response in (None, []):
            with self.subTest(response=response):
                self.engine.do_ocr_line.return_value = response
                self.assertEqual(self.recognize({'frame_id': 'crop-1', 'single_line': True}), [])

    def test_scaled_single_line_removes_padding_and_clips_to_original_crop(self):
        result = self.recognize({'frame_id': 'crop-1', 'single_line': True,
                                 'preprocess': 'task_scale'})
        prepared = self.engine.do_ocr_line.call_args.args[0]
        self.assertEqual(prepared.shape, (108, 258, 3))
        self.assertEqual(result[0]['box'], [[0, 0], [69, 0], [69, 19], [0, 19]])
        self.assertEqual(result[0]['center'], [34, 9])
        self.engine.do_ocr_ext.assert_not_called()

    def test_legacy_host_path_keeps_detection_and_original_geometry(self):
        self.engine.do_ocr_ext.return_value = [
            [[[10, 2], [29, 2], [29, 11], [10, 11]], ('普通OCR', 0.9)]]
        result = self.recognize({'frame_id': 'crop-1'})
        self.engine.do_ocr_ext.assert_called_once_with(self.image)
        self.engine.do_ocr_line.assert_not_called()
        self.assertEqual(result[0]['box'], [[10, 2], [29, 2], [29, 11], [10, 11]])
        self.assertEqual(result[0]['center'], [19, 6])

    def test_invalid_preprocessing_does_not_invoke_either_engine_path(self):
        with self.assertRaises(ValueError):
            self.recognize({'frame_id': 'crop-1', 'single_line': True, 'preprocess': 'unknown'})
        self.engine.do_ocr_line.assert_not_called()
        self.engine.do_ocr_ext.assert_not_called()


if __name__ == '__main__':
    unittest.main()
