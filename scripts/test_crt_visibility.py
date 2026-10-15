import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import crt_settings


class VisibilityTests(unittest.TestCase):
    def test_effects_follow_host_visibility_and_return_without_changing_preferences(self):
        with tempfile.TemporaryDirectory() as folder, patch('crt_settings.runtime_dir',return_value=Path(folder)):
            command=str(Path(crt_settings.__file__).with_name('embedded_app.py').resolve()).encode()
            with patch.object(Path,'read_bytes',return_value=b'python3\0'+command+b'\0'):
                self.assertFalse(crt_settings.host_visible())
                crt_settings.set_host_visible(True)
                self.assertTrue(crt_settings.host_visible())
                crt_settings.set_host_visible(False)
                self.assertFalse(crt_settings.host_visible())
                crt_settings.set_host_visible(True)
                self.assertTrue(crt_settings.host_visible())

    def test_crashed_host_or_reused_pid_does_not_leave_effects_visible(self):
        with tempfile.TemporaryDirectory() as folder, patch('crt_settings.runtime_dir',return_value=Path(folder)):
            crt_settings.set_host_visible(True)
            with patch.object(Path,'read_bytes',side_effect=FileNotFoundError):
                self.assertFalse(crt_settings.host_visible())
            with patch.object(Path,'read_bytes',return_value=b'/usr/bin/browser\0'):
                self.assertFalse(crt_settings.host_visible())

    def test_invalid_visibility_state_hides_effects(self):
        with tempfile.TemporaryDirectory() as folder, patch('crt_settings.runtime_dir',return_value=Path(folder)):
            for value in ('[]','null','bad json','{"visible":true,"pid":-1}'):
                (Path(folder)/'overlay-visibility.json').write_text(value)
                self.assertFalse(crt_settings.host_visible())


if __name__=='__main__': unittest.main()
