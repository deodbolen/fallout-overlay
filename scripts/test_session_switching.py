import unittest
from unittest.mock import Mock, patch
from session_input import InputRouter
from terminal_sessions import Sessions

class SessionSwitchingTests(unittest.TestCase):
    def test_f1_f2_encodings_and_split_packets(self):
        for sequence,action in ((b'\x1bOP','previous'),(b'\x1bOQ','next'),
                                (b'\x1b[11~','previous'),(b'\x1b[12~','next'),
                                (b'\x1b[[A','previous'),(b'\x1b[[B','next')):
            for split in range(1,len(sequence)):
                router=InputRouter()
                self.assertEqual(router.feed(sequence[:split]),(b'',None,b''))
                self.assertEqual(router.feed(sequence[split:]),(b'',action,b''))
    def test_portable_session_shortcuts_need_no_escape_sequence(self):
        router=InputRouter()
        self.assertEqual(router.feed(b'\x0f'),(b'','previous',b''))
        self.assertEqual(router.feed(b'\x10'),(b'','next',b''))
        self.assertEqual(router.feed(b'pwd\r\x10next'),(b'pwd\r','next',b'next'))
        self.assertEqual(router.feed(b'\x0e'),(b'\x0e',None,b''))
        self.assertEqual(router.feed(b'\x1b[A'),(b'\x1b[A',None,b''))
    def test_terminal_shift_arrows_and_passthrough(self):
        for ending,action in ((b'A','previous'),(b'B','next'),(b'D','section_previous'),(b'C','section_next')):
            router=InputRouter()
            self.assertEqual(router.feed(b'\x1b[1;6'),(b'',None,b''))
            self.assertEqual(router.feed(ending+b'pwd'),(b'',action,b'pwd'))
        router=InputRouter()
        self.assertEqual(router.feed(b'\x18e'),(b'\x18e',None,b''))
        self.assertEqual(router.feed(b'\x18n'),(b'\x18n',None,b''))
        self.assertEqual(router.feed(b'\x1b[17~'),(b'\x1b[17~',None,b''))

    def test_section_shortcut_returns_to_navigator_without_closing_session(self):
        session=Mock(); session.process.poll.return_value=None
        session.attach.return_value=('section_next',b'')
        sessions=Sessions(); sessions.items=[session]
        self.assertEqual(sessions.attach(Mock(),session),'section_next')
        session.close.assert_not_called()
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

    def test_prune_removes_only_exited_sessions(self):
        alive,closed=Mock(),Mock()
        alive.process.poll.return_value=None
        closed.process.poll.return_value=0
        sessions=Sessions(); sessions.items=[alive,closed]
        sessions.prune()
        self.assertEqual(sessions.items,[alive])
        alive.close.assert_not_called()
        closed.close.assert_called_once()
        closed.path.unlink.assert_called_once_with(missing_ok=True)

    def test_embedded_prune_keeps_finished_output_until_dismissed(self):
        from embedded_client import Sessions as EmbeddedSessions
        alive,finished,closed=Mock(),Mock(),Mock()
        alive.status='running'; finished.status='finished'; closed.status='closed'
        sessions=EmbeddedSessions(); sessions.items=[alive,finished,closed]
        sessions.prune()
        self.assertEqual(sessions.items,[alive,finished])
        closed.close.assert_called_once()
        finished.close.assert_not_called()

    def test_host_close_shortcut_and_cleanup(self):
        import ast
        from pathlib import Path
        from types import SimpleNamespace
        source=ast.parse(Path(__file__).with_name('embedded_app.py').read_text())
        host=next(node for node in source.body if isinstance(node,ast.ClassDef) and node.name=='Host')
        methods=[node for node in host.body if isinstance(node,ast.FunctionDef) and node.name in ('session_keys','remove_session','child_exited')]
        gdk=SimpleNamespace(ModifierType=SimpleNamespace(CONTROL_MASK=1,SHIFT_MASK=2),
                            KEY_Return=10,KEY_KP_Enter=11,KEY_Up=12,KEY_Down=13,KEY_w=119,
                            keyval_to_lower=lambda key:key)
        scope={'Gdk':gdk,'GLib':SimpleNamespace(idle_add=lambda callback:callback())}
        exec(compile(ast.Module(body=methods,type_ignores=[]),'<session-methods>','exec'),scope)
        instance=Mock(); instance.current='active'
        instance.modifier_shortcut.return_value=False
        self.assertTrue(scope['session_keys'](instance,Mock(),SimpleNamespace(state=3,keyval=119)))
        instance.close_session.assert_called_once_with('active')
        record={'path':Mock(),'terminal':Mock(),'closed':False}
        instance.records={'active':record}
        scope['remove_session'](instance,'active')
        self.assertEqual(instance.records,{})
        instance.detach.assert_called_once()
        record['terminal'].destroy.assert_called_once()
        scope['remove_session'](instance,'active')  # Late child-exit notification is harmless.

if __name__=='__main__': unittest.main()
