import curses
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from browser import Navigator
from navigator_input import read_key


class FileSelectionTests(unittest.TestCase):
    def test_range_extends_and_shrinks_skipping_directories(self):
        nav=Navigator.__new__(Navigator)
        nav.file_anchor=None; nav.file_selection=set(); nav.selected={}
        rows=[(Path('/a'),0,False),(Path('/folder'),0,True),(Path('/b'),0,False),(Path('/c'),0,False)]
        nav.select_file_range(rows,0,1)
        nav.select_file_range(rows,1,1)
        self.assertEqual(nav.file_selection,{Path('/a'),Path('/b')})
        nav.select_file_range(rows,2,-1)
        self.assertEqual(nav.file_selection,{Path('/a')})
        self.assertEqual(nav.selected['home'],1)

    def test_shift_sequences(self):
        for suffix,expected in [('A','select_up'),('B','select_down')]:
            screen=Mock()
            screen.get_wch.side_effect=list('\x1b[1;2'+suffix)
            self.assertEqual(read_key(screen),expected)

    def test_copy_group_and_conflict_preflight(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); dest=root/'dest'; dest.mkdir()
            paths=[root/'a',root/'b']
            for path in paths: path.write_text(path.name)
            nav=Navigator.__new__(Navigator)
            nav.tree=object(); nav.data_trees={'home':nav.tree}
            nav.file_selection=set(paths); nav.file_anchor=0
            nav.menu=Mock(return_value=0); nav.text=Mock(return_value=str(dest))
            nav.batch_file_actions(paths)
            self.assertEqual([(dest/p.name).read_text() for p in paths],['a','b'])
            self.assertFalse(nav.file_selection)
            with patch('browser.copy_file') as copy:
                with self.assertRaises(ValueError): nav.batch_file_actions(paths)
                copy.assert_not_called()

if __name__=='__main__': unittest.main()
