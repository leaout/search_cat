"""Exercise atomic storage code without GUI/Windows dependencies."""
import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'automation/services.py'
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))
CLASS = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'AutomationHost')
METHOD = next(node for node in CLASS.body if isinstance(node, ast.FunctionDef) and node.name == '_storage_write_json')
NAMESPACE = {'Any': object}
exec(compile(ast.Module(body=[METHOD], type_ignores=[]), str(SOURCE), 'exec'), NAMESPACE)
WRITE = NAMESPACE['_storage_write_json']


class AtomicStorageTests(unittest.TestCase):
    def test_write_preserves_unicode_and_no_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            host = Mock()
            host._data_path.return_value = path
            WRITE(host, {'path': 'ledger.json', 'value': {'pending': '矿锄'}})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'pending': '矿锄'})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_replace_failure_preserves_old_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            host = Mock()
            host._data_path.return_value = path
            WRITE(host, {'path': 'ledger.json', 'value': {'pending': True}})
            with patch('os.replace', side_effect=OSError('blocked')):
                with self.assertRaises(OSError):
                    WRITE(host, {'path': 'ledger.json', 'value': {'pending': False}})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'pending': True})
            self.assertEqual(list(Path(directory).iterdir()), [path])
