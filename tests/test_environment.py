import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_environment as env


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='env-test-', dir=Path(__file__).resolve().parents[1].parent)
        self.state = Path(self.temp.name) / 'state'

    def tearDown(self):
        self.temp.cleanup()

    def health_response(self, **changes):
        value = {'identity': env.IDENTITY, 'state_dir': str(self.state), 'pid': 123}
        value.update(changes)
        stream = io.BytesIO(json.dumps(value).encode())
        return stream

    def test_real_runtime_has_functioning_sqlite_and_hash(self):
        report = env.runtime_check()
        self.assertTrue(report['ok'], report)
        self.assertEqual(report['third_party_packages'], [])
        self.assertIn('sqlite_version', report)

    def test_missing_standard_library_is_reported_not_pip_installed(self):
        original = env.importlib.import_module
        def import_module(name):
            if name == 'sqlite3':
                raise ImportError('missing _sqlite3')
            return original(name)
        with patch.object(env.importlib, 'import_module', side_effect=import_module):
            result = env.runtime_check()
        self.assertFalse(result['ok'])
        self.assertEqual(result['missing_modules'][0]['module'], 'sqlite3')

    def test_old_python_is_rejected(self):
        with patch.object(env.sys, 'version_info', (3, 9, 0)):
            self.assertFalse(env.runtime_check()['ok'])

    def test_storage_write_check_cleans_only_its_own_files(self):
        marker = Path(self.temp.name) / 'keep.txt'
        marker.write_text('existing data')
        result = env.storage_check(self.state)
        self.assertTrue(result['ok'], result)
        self.assertEqual(marker.read_text(), 'existing data')
        self.assertFalse(self.state.exists())
        self.assertEqual(list(Path(self.temp.name).iterdir()), [marker])

    def test_invalid_or_unwritable_directory_is_rejected(self):
        self.assertFalse(env.storage_check(Path('relative'))['ok'])
        self.state.write_text('not a directory')
        self.assertFalse(env.storage_check(self.state)['ok'])
        self.state.unlink()
        with patch.object(tempfile, 'TemporaryDirectory', side_effect=PermissionError('denied')):
            self.assertFalse(env.storage_check(self.state)['ok'])

    def test_existing_matching_service_is_reused_without_bind(self):
        opener = Mock()
        opener.open.return_value = self.health_response()
        with patch('urllib.request.build_opener', return_value=opener), patch('socket.socket') as socket:
            report = env.service_check(self.state)
        self.assertEqual(report['status'], 'reuse')
        socket.assert_not_called()

    def test_foreign_or_different_state_service_is_rejected(self):
        for changes in ({'identity': 'other'}, {'state_dir': str(self.state.parent)}, {'state_dir': 'relative'}):
            with self.subTest(changes=changes):
                opener = Mock()
                opener.open.return_value = self.health_response(**changes)
                with patch('urllib.request.build_opener', return_value=opener):
                    self.assertFalse(env.service_check(self.state)['ok'])

    def test_free_and_occupied_non_http_ports_are_distinguished(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError('refused')
        with patch('urllib.request.build_opener', return_value=opener), patch('socket.socket') as factory:
            self.assertEqual(env.service_check(self.state)['status'], 'available')
            factory.return_value.__enter__.return_value.bind.side_effect = OSError('occupied')
            self.assertFalse(env.service_check(self.state)['ok'])

    def test_incomplete_skill_package_is_rejected(self):
        actual = Path.is_file
        def is_file(path):
            return False if path.name == 'progress_page.html' else actual(path)
        with patch.object(Path, 'is_file', is_file), patch.object(env, 'service_check', return_value={'ok': True}):
            report = env.check_environment(self.state)
        self.assertFalse(report['ready'])
        self.assertIn('progress_page.html', report['checks']['skill_files']['missing'])


if __name__ == '__main__':
    unittest.main()
