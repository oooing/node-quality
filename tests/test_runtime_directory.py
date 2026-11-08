"""Temporary checks accept an OS alias for the same directory, not other parents."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from detector import Detector


class RuntimeDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.runtime = self.root / 'runtime'
        self.detector = Detector(sys.executable, self.runtime)
        self.node = {'id': 'fixture', 'name': 'fixture', 'unsupported': '',
                     'config': {'name': 'fixture', 'type': 'direct'}}

    def tearDown(self):
        self.temp.cleanup()

    def assert_reaches_network_setup(self):
        # No interface is supplied: stop after directory validation, before any core/network use.
        with patch('detector.subprocess.Popen') as spawn:
            result = self.detector.check(self.node)
        self.assertEqual(result['diagnosis']['code'], 'no_interface')
        spawn.assert_not_called()
        self.assertEqual(list(self.runtime.iterdir()), [])

    def test_regular_directory(self):
        self.assert_reaches_network_setup()

    def test_same_directory_under_an_os_alias(self):
        alias = self.root / 'runtime-alias'
        if os.name == 'nt':
            subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(alias), str(self.runtime)],
                           check=True, capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            alias.symlink_to(self.runtime, target_is_directory=True)
        try:
            # Model an OS redirect that retains the parent's alias but resolves its child.
            self.assertNotEqual(alias, self.runtime)
            self.assertTrue(alias.samefile(self.runtime))
            self.detector.runtime = alias
            self.assert_reaches_network_setup()
        finally:
            if os.name == 'nt':
                os.rmdir(alias)  # Remove only the junction itself, never its target.
            else:
                alias.unlink()

    def test_different_parent_still_rejected(self):
        other = self.root / 'other'
        other.mkdir()
        temporary_factory = tempfile.TemporaryDirectory
        with patch('detector.tempfile.TemporaryDirectory',
                   side_effect=lambda **_: temporary_factory(prefix='check-', dir=other)), \
             patch('detector.subprocess.Popen') as spawn:
            result = self.detector.check(self.node)
        self.assertEqual(result['diagnosis']['code'], 'runtime_directory')
        spawn.assert_not_called()
        self.assertEqual(list(other.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
