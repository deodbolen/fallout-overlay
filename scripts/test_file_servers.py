import curses
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from browser import Navigator
import file_servers


class FileServerTests(unittest.TestCase):
    def test_servers_persist_without_passwords(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'XDG_CONFIG_HOME': folder}):
            smb = file_servers.add_server('NAS', 'smb://nas/shared')
            sftp = file_servers.add_server('SSH files', 'sftp://user@server:2222/home/user')
            self.assertEqual(file_servers.servers(), [smb, sftp])
            with self.assertRaises(ValueError):
                file_servers.add_server('Unsafe', 'sftp://user:secret@server/home')
            self.assertEqual(len(file_servers.servers()), 2)

    def test_invalid_locations(self):
        for uri in ('file:///etc', 'https://example.com', 'smb://nas', 'sftp://', 'sftp://host:bad/path'):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                file_servers.validate_uri(uri)

    def test_data_pages_start_at_home_and_preserve_selection(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'XDG_CONFIG_HOME': folder}):
            nav = Navigator(Mock())
            nav.sound = Mock()
            nav.section = nav.sections.index('DATA')
            self.assertEqual(nav.data_index, 1)
            self.assertEqual(nav.data_pages(), [('root', 'ROOT'), ('home', 'HOME'), ('add', '+ Server')])
            nav.selected['home'] = 3
            nav.switch_data_page(curses.KEY_LEFT)
            self.assertEqual(nav.data_index, 0)
            nav.switch_data_page(curses.KEY_RIGHT)
            self.assertEqual(nav.selected['home'], 3)
            server = file_servers.add_server('NAS', 'smb://nas/share')
            nav.switch_data_page(curses.KEY_RIGHT)
            self.assertEqual(nav.data_pages()[nav.data_index], (server['id'], 'NAS'))
            self.assertEqual(nav.rows()[0], 'server')
            nav.switch_data_page(curses.KEY_RIGHT)
            self.assertEqual(nav.rows()[2], ['+ Server'])


if __name__ == '__main__':
    unittest.main()
