"""Verify system deployment and restoration without touching local LightDM."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import greeter_background as greeter


class LoginSoundInstallTests(unittest.TestCase):
    def test_install_repeat_and_restore_preserve_previous_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root / name for name in (
                'BACKUP', 'SOUND_DIR', 'SOUND_LIBRARY', 'SOUND_LAUNCHER',
                'SOUND_DESKTOP', 'SOUND_CONFIG')}
            paths['BACKUP'].mkdir()
            paths['SOUND_CONFIG'].write_text('[Seat:*]\ngreeter-session=original\n')

            def compile_library(args, **kwargs):
                Path(args[args.index('-o') + 1]).write_bytes(b'compiled')

            with patch.multiple(greeter, **paths), \
                 patch.object(greeter.subprocess, 'check_output', return_value=''), \
                 patch.object(greeter.subprocess, 'run', side_effect=compile_library), \
                 patch.object(greeter.shutil, 'which', return_value='/usr/sbin/lightdm-gtk-greeter'):
                greeter.install_login_sounds()
                greeter.install_login_sounds()
                for event in ('good', 'bad'):
                    original = greeter.ROOT / f'fallout-sounds/password/ui_hacking_pass{event}.wav'
                    self.assertEqual((paths['SOUND_DIR'] / f'{event}.wav').read_bytes(),
                                     original.read_bytes())
                self.assertIn('greeter-session=fallout-gtk-greeter', paths['SOUND_CONFIG'].read_text())
                self.assertIn('LD_PRELOAD=', paths['SOUND_LAUNCHER'].read_text())
                greeter.restore_login_sounds()
                self.assertEqual(paths['SOUND_CONFIG'].read_text(),
                                 '[Seat:*]\ngreeter-session=original\n')
                self.assertFalse(paths['SOUND_DESKTOP'].exists())

    def test_compile_failure_does_not_select_unbuilt_greeter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(greeter, 'SOUND_LIBRARY', root / 'module.so'), \
                 patch.object(greeter, 'SOUND_CONFIG', root / 'config'), \
                 patch.object(greeter.subprocess, 'check_output', return_value=''), \
                 patch.object(greeter.subprocess, 'run', side_effect=RuntimeError('compile failed')):
                with self.assertRaises(RuntimeError):
                    greeter.install_login_sounds()
                self.assertFalse((root / 'config').exists())


if __name__ == '__main__':
    unittest.main()
