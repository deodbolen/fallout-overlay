import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import searxng_service as service


class SearxngServiceTests(unittest.TestCase):
    def test_unit_is_local_only_and_digest_pinned(self):
        text=service.service_text('docker.io/searxng/searxng@sha256:abc',Path('/a path/config'),Path('/cache'))
        self.assertIn('127.0.0.1:8888:8080',text)
        self.assertIn('--pull=never',text)
        self.assertIn('@sha256:abc',text)
        self.assertIn('"/a path/config:/etc/searxng"',text)
        self.assertNotIn('sudo',text)
        self.assertNotIn('--privileged',text)

    def test_migration_preserves_existing_choices_and_profiles(self):
        with tempfile.TemporaryDirectory() as folder, patch('searxng_service.config_dir',return_value=Path(folder)):
            path=Path(folder)/'yes-man.json'
            path.write_text(json.dumps({'model':'FortiLab','api_key':'secret','search_url':'https://custom',
                'search_enabled':False,'profiles':{'old':{'model':'a'},
                'custom':{'search_url':'https://custom','search_enabled':False}}}))
            service.migrate_settings()
            result=json.loads(path.read_text())
            self.assertEqual(result['search_url'],'https://custom')
            self.assertFalse(result['search_enabled'])
            self.assertEqual(result['api_key'],'secret')
            self.assertEqual(result['profiles']['old']['search_url'],service.URL)
            self.assertTrue(result['profiles']['old']['search_enabled'])
            self.assertFalse(result['profiles']['custom']['search_enabled'])

    def test_install_is_repeatable_and_restore_stops_only_owned_service(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); config=base/'config'; state=base/'state'; unit=base/'systemd'/service.UNIT
            def command(args,**kwargs):
                return Mock(stdout='docker.io/searxng/searxng@sha256:abc\n')
            response=MagicMock(); response.__enter__.return_value.read.return_value=b'OK'
            with patch('searxng_service.config_dir',return_value=config), \
                 patch('searxng_service.state_dir',return_value=state), \
                 patch('searxng_service.unit_path',return_value=unit), \
                 patch('searxng_service.os.geteuid',return_value=1000), \
                 patch('searxng_service.run',side_effect=command) as run, \
                 patch('searxng_service.subprocess.run',return_value=Mock(returncode=0)), \
                 patch('searxng_service.urlopen',return_value=response):
                service.install()
                settings=config/'searxng/settings.yml'; before=settings.read_bytes()
                self.assertIn(b'- json',before)
                service.install()
                self.assertEqual(settings.read_bytes(),before)
                service.restore()
                self.assertFalse(unit.exists())
                self.assertTrue(settings.exists())
                run.assert_any_call(['systemctl','--user','disable','--now',service.UNIT])
                unit.write_text('not managed')
                run.reset_mock(); service.restore(); run.assert_not_called()
                self.assertTrue(unit.exists())

if __name__=='__main__': unittest.main()
