import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
from metrics import rates, human, sample, previous_sample, display_width
class MetricsTests(unittest.TestCase):
    def test_rates(self):
        self.assertEqual(rates({'sda':[4096,8192]}, {'sda':[2048,4096]},2),[1024,2048])
    def test_reset_and_new_devices(self):
        self.assertEqual(rates({'sda':[1,2],'sdb':[200,400]}, {'sda':[100,200]},2),[0,0])
    def test_units(self):
        self.assertEqual(human(1024**3),'1G')
    def test_live_sample(self):
        value=sample(); self.assertGreater(sum(value['cpu']),0)
        self.assertNotIn('lo',value['net'])

    def test_invalid_or_rebooted_cache_starts_with_zero_rates(self):
        now={'time': 10, 'cpu': [100]*8, 'disk': {}, 'net': {}}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'metrics.json'
            self.assertEqual(previous_sample(path,now),now)
            for old in (None, {}, {'time': 20},
                        {**now, 'time': 5, 'cpu': [200]*8},
                        {**now, 'time': 5, 'net': {'eth0': [1]}},
                        {**now, 'time': 5, 'disk': {'sda': ['bad', 2]}}):
                path.write_text(json.dumps(old))
                self.assertEqual(previous_sample(path,now),now)
            old={**now, 'time': 5, 'cpu': [50]*8}
            path.write_text(json.dumps(old))
            self.assertEqual(previous_sample(path,now),old)

    def test_display_probe_cached_and_refreshed(self):
        with tempfile.TemporaryDirectory() as folder, patch('metrics.subprocess.run') as probe:
            probe.return_value=Mock(returncode=0,stdout='Screen 0: current 1280 x 720')
            cache=Path(folder)
            self.assertEqual(display_width(cache,10),1280)
            self.assertEqual(display_width(cache,12),1280)
            probe.assert_called_once()
            probe.return_value=Mock(returncode=0,stdout='Screen 0: current 1920 x 1080')
            self.assertEqual(display_width(cache,70),1920)
            self.assertEqual(probe.call_count,2)
            # A reboot resets monotonic time and invalidates the previous cache.
            self.assertEqual(display_width(cache,1),1920)
            self.assertEqual(probe.call_count,3)

    def test_failed_display_probe_is_also_cached(self):
        with tempfile.TemporaryDirectory() as folder, patch('metrics.subprocess.run',side_effect=OSError) as probe:
            self.assertEqual(display_width(Path(folder),10),1920)
            self.assertEqual(display_width(Path(folder),12),1920)
            probe.assert_called_once()
if __name__=='__main__': unittest.main()
