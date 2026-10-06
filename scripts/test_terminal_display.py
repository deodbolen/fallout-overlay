import unittest
from terminal_display import TerminalScreen, render, pyte
class FooterTests(unittest.TestCase):
    def test_clear_and_scrolling_cannot_erase_footer(self):
        screen=TerminalScreen(90,9); stream=pyte.ByteStream(screen)
        stream.feed(b'\x1b[2J'+b'command output\r\n'*30)
        output=render(screen,10,90,full=True).decode()
        self.assertIn('\x1b[10;1H',output)
        self.assertIn('Hold Ctrl and press ]',output)
        self.assertEqual(screen.lines,9)
    def test_alternate_screen_restores_shell(self):
        screen=TerminalScreen(90,9); stream=pyte.ByteStream(screen)
        stream.feed(b'shell prompt\x1b[?1049h\x1b[2Japplication\x1b[?1049l')
        self.assertTrue(screen.display[0].startswith('shell prompt'))
        self.assertIn('Ctrl+]',render(screen,10,90,full=True).decode())
    def test_resize_keeps_footer_below_session(self):
        screen=TerminalScreen(90,9); screen.resize(lines=19,columns=110)
        output=render(screen,20,110,full=True).decode()
        self.assertIn('\x1b[20;1H',output)
        self.assertIn('Session stays running',output)
    def test_cursor_queries_reply_to_pty(self):
        replies=[]; screen=TerminalScreen(90,9,replies.append); stream=pyte.ByteStream(screen)
        stream.feed(b'hello\x1b[6n')
        self.assertEqual(replies,[b'\x1b[1;6R'])
if __name__=='__main__': unittest.main()
