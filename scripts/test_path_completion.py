from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from path_completion import directory_matches, complete_directory
from browser import Navigator

class CompletionTests(unittest.TestCase):
    def test_only_directories_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ('Documents','Downloads','dir with spaces','.hidden'): (root/name).mkdir()
            (root/'data.txt').write_text('file')
            self.assertEqual(directory_matches('Do',root),['Documents/','Downloads/'])
            self.assertEqual(directory_matches('.',root),['.hidden/'])
            self.assertIn('dir with spaces/',directory_matches('',root))
            self.assertEqual(directory_matches('missing/',root),[])
            self.assertEqual(complete_directory('D',directory_matches('D',root)),'Do')
            self.assertEqual(complete_directory('Do',directory_matches('Do',root),1,True),'Downloads/')
    def test_absolute_and_tilde(self):
        with tempfile.TemporaryDirectory() as d, patch.dict('os.environ',{'HOME':d}):
            root=Path(d); (root/'Documents').mkdir()
            self.assertEqual(directory_matches('~/Doc',root),['~/Documents/'])
            self.assertEqual(directory_matches(str(root)+'/Doc',root),[str(root)+'/Documents/'])
            self.assertEqual(directory_matches('~',root),['~/'])
    def test_tab_in_destination_field(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'Documents').mkdir()
            screen=Mock(); screen.getmaxyx.return_value=(30,120)
            screen.get_wch.side_effect=['\t','\n']
            navigator=Navigator(screen); navigator.draw=Mock()
            with patch('browser.curses.curs_set'):
                self.assertEqual(navigator.text('DESTINATION','Doc',directory_base=root),'Documents/')
            self.assertTrue(any('Available directories:' in call.args[1] for call in navigator.draw.call_args_list))

if __name__=='__main__': unittest.main()
