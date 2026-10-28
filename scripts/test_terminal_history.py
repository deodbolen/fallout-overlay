import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from terminal_display import TerminalScreen,pyte,render,text_slice
from terminal_text import export_text,plain_text,copy_terminal_text,vte_text
import navigator_settings


def terminal(text,columns=80,lines=25,chunk=None):
    screen=TerminalScreen(columns,lines)
    stream=pyte.ByteStream(screen)
    data=text.encode('utf-8')
    if chunk:
        for start in range(0,len(data),chunk):stream.feed(data[start:start+chunk])
    else:stream.feed(data)
    return screen,stream


class HistoryTests(unittest.TestCase):
    def test_numbered_100_and_200_lines_survive_and_can_be_scrolled(self):
        for count in (100,200):
            expected=''.join(f'{number:04d}\n' for number in range(1,count+1))
            screen,_=terminal(expected.replace('\n','\r\n'))
            self.assertEqual(screen.export_text(),expected)
            screen.scroll(10000)
            self.assertIn('0001',''.join(screen.row_text(row) for row in screen.view_rows()))
            self.assertEqual(screen.export_text(),expected)

    def test_at_least_10000_rows_retained(self):
        expected=''.join(f'{number:05d}\r\n' for number in range(10050))
        screen,_=terminal(expected)
        self.assertGreaterEqual(len(screen.history),10000)
        self.assertIn('00026\n',screen.export_text())
        self.assertIn('10049\n',screen.export_text())
        self.assertNotIn('00000\n',screen.export_text())

    def test_wrapped_lines_do_not_use_one_history_slot_per_visual_fragment(self):
        line='a'*500
        expected=''.join(f'{n:03d} '+line+'\n' for n in range(200))
        screen,_=terminal(expected.replace('\n','\r\n'),columns=8,lines=4)
        self.assertGreater(len(screen.history),10000)
        self.assertEqual(screen.export_text(),expected)
        self.assertEqual(screen.history_lines,199)

    def test_scroll_position_stays_anchored_during_new_output(self):
        screen,stream=terminal(''.join(f'{n}\r\n' for n in range(200)))
        screen.scroll(70)
        before=[screen.row_text(row) for row in screen.view_rows()]
        stream.feed(b'new output\r\n')
        self.assertEqual(before,[screen.row_text(row) for row in screen.view_rows()])

    def test_alt_screen_and_resize_preserve_normal_history_and_state(self):
        source=''.join(f'{n} 漢字 👩\u200d💻\r\n' for n in range(200))+'shell> '
        screen,stream=terminal(source,columns=20,lines=8)
        expected=screen.export_text()
        stream.feed(b'\x1b[?1049h\x1b[2Jalternate application\r\n')
        self.assertEqual(screen.export_text(),expected)
        screen.resize(5,12)
        stream.feed(b'\x1b[?1049l')
        self.assertEqual(screen.export_text(),expected)
        for columns in (80,8,32):
            screen.resize(10,columns)
            self.assertEqual(screen.export_text(),expected)
        stream.feed(b'echo done')
        self.assertTrue(screen.export_text().endswith('shell> echo done'))

    def test_split_utf8_clusters_and_wide_character_at_right_margin(self):
        source='abc漢字 😀 👩\u200d💻 👍🏽 🇺🇸 ♥️ e\u0301'
        screen,_=terminal(source+'\r\n',columns=4,lines=3,chunk=1)
        self.assertEqual(screen.export_text(),source+'\n')
        for columns in (10,6,20):
            screen.resize(4,columns)
            self.assertEqual(screen.export_text(),source+'\n')
        self.assertEqual(text_slice('a👩\u200d💻漢b',1,4),'👩\u200d💻漢')

    def test_ansi_removed_and_all_literal_markup_is_preserved(self):
        source='user@host:~$ **bold** http://example.org/?a=1&b=2 <tag> &amp; \\path'
        screen,_=terminal('\x1b[1;32m'+source+'\x1b[0m\r\n',columns=12,lines=5)
        self.assertEqual(screen.export_text(),source+'\n')
        self.assertEqual(plain_text('\x1b]8;;http://x\x07link\x1b]8;;\x07'),'link')
        self.assertEqual(plain_text('\x1b[31m'+source+'\x1b[0m'),source)

    def test_no_visual_padding_is_rendered_or_exported(self):
        screen,_=terminal('hi',columns=200,lines=4)
        self.assertEqual(screen.export_text(),'hi')
        output=render(screen,5,200,full=True)
        self.assertNotIn(b' '*50,output)

    def test_sessions_never_share_history(self):
        first,one=terminal('FIRST\r\n')
        second,two=terminal('SECOND\r\n')
        one.feed(b'ONE\r\n');two.feed(b'TWO\r\n')
        self.assertEqual(first.export_text(),'FIRST\nONE\n')
        self.assertEqual(second.export_text(),'SECOND\nTWO\n')

    def test_render_after_shrinking_normal_and_alternate_viewports(self):
        screen,stream=terminal(''.join(f'{i}\r\n' for i in range(100)))
        expected=screen.export_text()
        screen.resize(5,20)
        self.assertIn(b'\x1b[6;1H',render(screen,6,20))
        stream.feed(b'\x1b[?1049hfull-screen application')
        screen.resize(3,10)
        render(screen,4,10)
        stream.feed(b'\x1b[?1049l')
        render(screen,4,10)
        self.assertEqual(screen.export_text(),expected)


class PlainExportTests(unittest.TestCase):
    def test_file_is_literal_utf8_private_and_never_overwrites(self):
        source='**bold** http://x <a> &amp; 漢字 👩\u200d💻 e\u0301\n'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'session.txt'
            export_text(path,source)
            self.assertEqual(path.read_bytes(),source.encode('utf-8'))
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):export_text(path,'different session')
            self.assertEqual(path.read_text(),source)

    def test_remote_clipboard_contains_literal_text_only(self):
        source='**bold** http://x &amp; 漢字\n'
        with patch('terminal_text.os.write',side_effect=lambda fd,data:len(data)) as write:
            copy_terminal_text(source)
            data=bytes(write.call_args.args[1])
            self.assertEqual(base64.b64decode(data[len(b'\x1b]52;c;'):-1]),source.encode())

    def test_partial_clipboard_writes_are_completed(self):
        packets=[]
        def partial(fd,data):
            count=min(3,len(data));packets.append(bytes(data[:count]));return count
        with patch('terminal_text.os.write',side_effect=partial):copy_terminal_text('漢字 **bold**')
        packet=b''.join(packets)
        self.assertEqual(base64.b64decode(packet[len(b'\x1b]52;c;'):-1]).decode(),'漢字 **bold**')

    def test_vte_export_uses_full_contents_not_visible_text(self):
        widget=Mock();gio=Mock();vte=Mock()
        output=gio.MemoryOutputStream.new_resizable.return_value
        output.steal_as_bytes.return_value.get_data.return_value=b'oldest\nlatest\n'
        self.assertEqual(vte_text(widget,gio,vte),'oldest\nlatest\n')
        widget.write_contents_sync.assert_called_once_with(output,vte.WriteFlags.DEFAULT,None)
        widget.get_text.assert_not_called()

    def test_config_minimum_capacity_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'XDG_CONFIG_HOME':folder}):
            self.assertEqual(navigator_settings.scrollback_lines(),10000)
            navigator_settings.save_scrollback_lines(20000)
            self.assertEqual(navigator_settings.scrollback_lines(),20000)
            with self.assertRaises(ValueError):navigator_settings.save_scrollback_lines(9999)


if __name__=='__main__':unittest.main()
