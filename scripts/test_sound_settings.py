import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
import sound_settings
from sounds import Sounds
class VolumeTests(unittest.TestCase):
    def test_save_preserves_crt_and_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'XDG_CONFIG_HOME':folder}):
            path=Path(folder)/'fallout-ui/settings.json';path.parent.mkdir();path.write_text('{"crt_overlay":true}')
            sound_settings.save('fan_volume',0)
            sound_settings.save('effects_volume',100)
            self.assertEqual(sound_settings.levels(),{'fan_volume':0,'effects_volume':100})
            self.assertTrue(json.loads(path.read_text())['crt_overlay'])
            with self.assertRaises(ValueError): sound_settings.save('fan_volume',101)
    def test_refresh_updates_playing_sounds(self):
        with patch('sound_settings.levels',return_value={'fan_volume':0,'effects_volume':65}):
            sounds=Sounds(); fan=Mock(); effect=Mock()
            sounds.players={'fan':(fan,None,None),'ok':(effect,None,None)}
            sounds.refresh()
            fan.set_property.assert_called_with('volume',0)
            effect.set_property.assert_called_with('volume',.65)
if __name__=='__main__': unittest.main()
