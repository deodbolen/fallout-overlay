import curses
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from browser import Navigator
import crt_settings

class SettingsTests(unittest.TestCase):
    def test_right_navigation_reaches_settings(self):
        navigator=Navigator(Mock())
        for expected in (1,2,3,4,0):
            navigator.switch_section(curses.KEY_RIGHT)
            self.assertEqual(navigator.section,expected)
        navigator.section=4
        with patch('crt_settings.running',return_value=False):
            self.assertEqual(navigator.rows()[0],'settings')
            self.assertIn('Disabled',navigator.rows()[2][0])
    def test_toggle_saved_and_autostart_disabled(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'XDG_CONFIG_HOME':d}):
            self.assertFalse(crt_settings.enabled())
            crt_settings.save(True)
            self.assertTrue(crt_settings.enabled())
            crt_settings.save(False)
            self.assertFalse(crt_settings.enabled())
            self.assertIn('Hidden=true',(Path(d)/'autostart/fallout-crt.desktop').read_text())
    def test_animation_has_separate_toggle(self):
        navigator=Navigator(Mock()); navigator.section=4
        with patch('crt_settings.running',return_value=True), patch('crt_settings.enabled',return_value=False), patch('crt_settings.animation_enabled',return_value=True):
            self.assertEqual(navigator.rows()[2],['CRT overlay: Disabled','CRT scan animation: Enabled'])
        navigator.menu=Mock(return_value=0)
        with patch('crt_settings.set_animation') as toggle:
            navigator.activate('settings',1,[])
            toggle.assert_called_once_with(True)

    def test_static_disable_preserves_animation_startup(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'XDG_CONFIG_HOME':d}):
            from ssh_manager import atomic_json
            atomic_json(Path(d)/'fallout-ui/settings.json',{'crt_animation':True})
            crt_settings.save(False)
            self.assertTrue(crt_settings.animation_enabled())
            self.assertIn('Hidden=false',(Path(d)/'autostart/fallout-crt.desktop').read_text())

    def test_settings_menu_actions_and_cancel(self):
        navigator=Navigator(Mock())
        for choice,expected in ((0,True),(1,False),(2,None)):
            navigator.menu=Mock(return_value=choice)
            with patch('crt_settings.set_enabled') as toggle:
                navigator.activate('settings',0,[])
                if expected is None: toggle.assert_not_called()
                else: toggle.assert_called_once_with(expected)

if __name__=='__main__': unittest.main()
