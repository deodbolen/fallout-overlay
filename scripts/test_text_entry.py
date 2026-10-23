import curses
import unittest
from unittest.mock import Mock
from text_entry import TextField,draw_box


class TextEntryTests(unittest.TestCase):
    def test_edit_middle_of_address(self):
        field=TextField('192.0.2.1')
        field.edit(curses.KEY_LEFT)
        field.edit(curses.KEY_DC)
        field.edit('5')
        self.assertEqual(field.value,'192.0.2.5')
        field.edit(curses.KEY_HOME)
        field.edit('a')
        field.edit(curses.KEY_BACKSPACE)
        self.assertEqual(field.value,'192.0.2.5')
        field.edit('\x15')
        self.assertEqual((field.value,field.position),('',0))

    def test_empty_field_has_border_and_cursor_inside(self):
        screen=Mock(); screen.getmaxyx.return_value=(24,80)
        draw_box(screen,TextField())
        self.assertEqual(len(screen.addnstr.call_args_list),3)
        self.assertTrue(screen.addnstr.call_args_list[0].args[2].startswith('+---'))
        screen.move.assert_called_once_with(4,3)

    def test_long_unicode_path_keeps_cursor_inside_narrow_box(self):
        screen=Mock(); screen.getmaxyx.return_value=(24,25)
        field=TextField('/a/very/long/path/文書')
        draw_box(screen,field)
        row,column=screen.move.call_args.args
        self.assertEqual(row,4)
        self.assertLess(column,24)
        self.assertGreaterEqual(column,3)
        field.edit(curses.KEY_HOME)
        draw_box(screen,field)
        screen.move.assert_called_with(4,3)


if __name__=='__main__': unittest.main()
