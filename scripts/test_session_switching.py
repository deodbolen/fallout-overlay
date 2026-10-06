import unittest
from unittest.mock import Mock
from session_input import InputRouter
from terminal_sessions import Sessions

class SessionSwitchingTests(unittest.TestCase):
    def test_shortcuts_and_ordinary_arrows(self):
        router=InputRouter()
        self.assertEqual(router.feed(b'pwd\r\x1b[1;5Bnext'),(b'pwd\r','next',b'next'))
        self.assertEqual(router.feed(b'\x1b[A'),(b'\x1b[A',None,b''))
        self.assertEqual(router.feed(b'\x1d'),(b'','detach',b''))
    def test_split_shortcut(self):
        router=InputRouter()
        self.assertEqual(router.feed(b'\x1b[1;'),(b'',None,b''))
        self.assertEqual(router.feed(b'5A'),(b'','previous',b''))
    def test_escape_timeout_flush(self):
        router=InputRouter(); router.feed(b'\x1b')
        self.assertEqual(router.flush(),b'\x1b')
    def test_cycle_skips_finished_and_keeps_sessions_alive(self):
        first,finished,last=Mock(),Mock(),Mock()
        for session in (first,finished,last): session.process.poll.return_value=None
        first.status=last.status='running'; finished.status='finished'
        last.attach.return_value=('next',b'')
        first.attach.return_value=('detach',b'')
        sessions=Sessions(); sessions.items=[first,finished,last]
        selected=Mock(); sessions.attach(Mock(),last,selected)
        self.assertEqual([call.args[0] for call in selected.call_args_list],[last,first])
        finished.attach.assert_not_called()
        first.close.assert_not_called(); last.close.assert_not_called()

if __name__=='__main__': unittest.main()
