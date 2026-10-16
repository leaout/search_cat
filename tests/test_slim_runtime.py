"""Guard against eagerly importing optional AI runtimes in the desktop entry."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SlimRuntimeTests(unittest.TestCase):
    def test_entry_has_no_optional_ai_import(self):
        tree = ast.parse((ROOT / 'gui.py').read_text(encoding='utf-8'))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append((node.module or '').split('.')[0])
        self.assertFalse({'torch', 'ultralytics', 'langchain'} & set(modules))

    def test_paddle_import_is_deferred_until_engine_creation(self):
        tree = ast.parse((ROOT / 'core/ocr.py').read_text(encoding='utf-8'))
        self.assertFalse(any(isinstance(node, ast.ImportFrom) and node.module == 'paddleocr'
                             for node in tree.body))
        self.assertTrue(any(isinstance(node, ast.ImportFrom) and node.module == 'paddleocr'
                            for node in ast.walk(tree)))

    def test_default_requirements_do_not_install_legacy_features(self):
        desktop = (ROOT / 'requirements-desktop.txt').read_text(encoding='utf-8')
        for package in ('ultralytics', 'langchain', 'pyaudio', 'SpeechRecognition'):
            self.assertNotIn(package, desktop)
