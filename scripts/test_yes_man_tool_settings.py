"""Model/tool separation regressions, suitable for isolated manual validation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yes_man
import yes_man_tool_settings as tools


class ToolSettingsTests(unittest.TestCase):
    def test_profiles_cannot_replace_global_tool_settings(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch('yes_man.config_dir',return_value=Path(folder)), \
             patch('yes_man_tool_settings.config_dir',return_value=Path(folder)):
            shared={'search_enabled':False,'search_url':'https://shared.example/search'}
            tools.save(shared)
            first=dict(yes_man.DEFAULT,model='one',search_enabled=True,search_url='https://ignored.example')
            yes_man.save_profile('One',first)
            yes_man.save_profile('Two',dict(first,model='two',search_url='https://other.example'))
            document=json.loads((Path(folder)/'yes-man.json').read_text())
            self.assertTrue(all('search_url' not in profile and 'search_enabled' not in profile
                                for profile in document['profiles'].values()))
            for name in ('One','Two'):
                config=yes_man.select_profile(name)
                self.assertEqual({key:config[key] for key in tools.DEFAULT},shared)
            self.assertEqual(tools.settings(),shared)

    def test_legacy_active_settings_preserved_without_profile_search_switching(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch('yes_man.config_dir',return_value=Path(folder)), \
             patch('yes_man_tool_settings.config_dir',return_value=Path(folder)):
            path=Path(folder)/'yes-man.json'
            legacy=dict(yes_man.DEFAULT,model='one',search_enabled=False,search_url='https://legacy.example')
            legacy['profiles']={'Other':dict(yes_man.DEFAULT,model='two',search_url='https://profile.example')}
            path.write_text(json.dumps(legacy))
            before=path.read_bytes()
            self.assertEqual(tools.settings()['search_url'],'https://legacy.example')
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse((Path(folder)/'yes-man-tools.json').exists())
            yes_man.select_profile('Other')
            self.assertEqual(tools.settings()['search_url'],'https://legacy.example')
            profiles_before=json.loads(path.read_text())['profiles']
            tools.save({'search_enabled':True,'search_url':'https://global.example'})
            self.assertEqual(json.loads(path.read_text())['profiles'],profiles_before)
            self.assertEqual((Path(folder)/'yes-man-tools.json').stat().st_mode & 0o777,0o600)

if __name__=='__main__': unittest.main()
