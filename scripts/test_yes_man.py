import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from urllib.error import HTTPError
import yes_man
import tool_belt


class YesManTests(unittest.TestCase):
    def config(self,**values): return dict(yes_man.DEFAULT,model='test-model',**values)

    def test_chat_word_wrapping(self):
        from yes_man_ui import wrap_chat_line
        self.assertEqual(wrap_chat_line('hello world',8),['hello','world'])
        self.assertEqual(wrap_chat_line('hi abcdefghij end',6),['hi','abcdef','ghij','end'])
        self.assertEqual(wrap_chat_line('hello world',11),['hello world'])
        self.assertEqual(wrap_chat_line('日本語 test',6),['日本語','test'])
        self.assertEqual(wrap_chat_line('',10),[''])

    def test_builtin_always_available(self):
        with patch('tool_belt.favorites',return_value=[]):
            self.assertEqual(tool_belt.applications([])[0]['builtin'],'yes-man')

    def test_private_persistence(self):
        with tempfile.TemporaryDirectory() as folder, patch('yes_man.config_dir',return_value=Path(folder)):
            yes_man.save(self.config(api_key='secret'))
            self.assertEqual(yes_man.settings()['api_key'],'secret')
            self.assertEqual((Path(folder)/'yes-man.json').stat().st_mode & 0o777,0o600)

    def test_request_protocols_preserve_text_and_history(self):
        messages=[{'role':'user','content':'Hello 日本語 & **literal**'}]
        for protocol,url,endpoint,response in [
            ('OpenAI compatible','http://localhost:1234/v1','http://localhost:1234/v1/chat/completions',{'choices':[{'message':{'content':'Hi!'}}]}),
            ('Ollama','http://localhost:11434','http://localhost:11434/api/chat',{'message':{'content':'Hi!'}})]:
            opener=MagicMock(); stream=opener.open.return_value.__enter__.return_value
            stream.read.return_value=json.dumps(response).encode()
            with patch('yes_man.build_opener',return_value=opener):
                self.assertEqual(yes_man.reply(self.config(protocol=protocol,url=url,api_key='key'),messages),'Hi!')
            request=opener.open.call_args.args[0]
            self.assertEqual(request.full_url,endpoint)
            body=json.loads(request.data)
            self.assertEqual(body['messages'][1:],messages)
            self.assertFalse(body['stream'])
            self.assertEqual(request.get_header('Authorization'),'Bearer key')
            self.assertEqual(len(messages),1)

    def test_connectivity_result_and_timeout_restored(self):
        import yes_man_ui
        nav=Mock(); nav.screen=Mock(spec=['timeout','get_wch'])
        with patch('yes_man.reply',return_value='OK') as reply, patch('yes_man_ui.read_key',side_effect=__import__('curses').error):
            yes_man_ui.test_connection(nav,self.config())
            self.assertIn('successful',nav.message)
            self.assertEqual(reply.call_args.args[1][0]['role'],'user')
        nav.screen.timeout.assert_called_with(-1)
        with patch('yes_man.reply',side_effect=ValueError('HTTP 401')), patch('yes_man_ui.read_key',side_effect=__import__('curses').error):
            yes_man_ui.test_connection(nav,self.config())
            self.assertIn('HTTP 401',nav.message)

    def test_escape_during_connection_check_restores_input(self):
        import threading
        import yes_man_ui
        gate=threading.Event()
        nav=Mock(); nav.screen=Mock(spec=['timeout','get_wch'])
        def slow_reply(*args):
            gate.wait(2)
            return 'OK'
        try:
            with patch('yes_man.reply',side_effect=slow_reply), patch('yes_man_ui.read_key',return_value='\x1b'):
                yes_man_ui.test_connection(nav,self.config())
                self.assertIn('dismissed',nav.message)
                nav.screen.timeout.assert_called_with(-1)
        finally: gate.set()

    def test_escape_parser_without_nonexistent_getdelay(self):
        from navigator_input import read_key
        import curses
        screen=Mock(spec=['get_wch','timeout'])
        screen.get_wch.side_effect=['\x1b',curses.error()]
        self.assertEqual(read_key(screen,100),'\x1b')
        screen.timeout.assert_called_with(100)

    def test_exact_fortilab_endpoint_and_tls_option(self):
        for url in ('https://10.0.1.215/v1','https://10.0.1.215/v1/',
                    'https://10.0.1.215/v1/chat/completions'):
            config=self.config(url=url)
            self.assertEqual(yes_man.endpoint(config),'https://10.0.1.215/v1/chat/completions')
        self.assertTrue(yes_man.validate(self.config())['verify_tls'])
        self.assertFalse(yes_man.validate(self.config(verify_tls=False))['verify_tls'])

    def test_server_error_includes_endpoint_and_redacts_key(self):
        import io
        opener=MagicMock()
        opener.open.side_effect=HTTPError('https://server',404,'Not Found',{},
            io.BytesIO(b'{"error":{"message":"Model unknown; key secret"}}'))
        with patch('yes_man.build_opener',return_value=opener):
            with self.assertRaises(ValueError) as caught:
                yes_man.reply(self.config(api_key='secret'),[])
        self.assertIn('/v1/chat/completions',str(caught.exception))
        self.assertIn('Model unknown',str(caught.exception))
        self.assertNotIn('secret',str(caught.exception))

    def test_chat_types_directly_and_enter_sends(self):
        import yes_man_ui
        nav=Mock(); nav.yes_man_messages=[]
        class ImmediateThread:
            def __init__(self,target,**kwargs): self.target=target
            def start(self): self.target()
        with patch('yes_man.settings',return_value=self.config()), \
             patch('yes_man.reply',return_value='Hello!') as reply, \
             patch('yes_man_ui.portrait',return_value=True), \
             patch('yes_man_ui.cursor'), \
             patch('yes_man_ui.chat_panel',return_value=(0,10)), \
             patch('yes_man_ui.threading.Thread',ImmediateThread), \
             patch('yes_man_ui.read_key',side_effect=['h','i','\n','\x1b']):
            yes_man_ui.chat(nav)
        self.assertEqual(reply.call_args.args[1],[{'role':'user','content':'hi'}])
        self.assertEqual(nav.yes_man_messages,[{'role':'user','content':'hi'},
                                               {'role':'assistant','content':'Hello!'}])
        nav.screen.timeout.assert_called_with(-1)

    def test_invalid_config_and_unexpected_reply(self):
        for url in ('file:///tmp/test','http://user:password@server','https://server?key=secret'):
            with self.assertRaises(ValueError): yes_man.validate(self.config(url=url))
        opener=MagicMock(); opener.open.return_value.__enter__.return_value.read.return_value=b'{}'
        with patch('yes_man.build_opener',return_value=opener), self.assertRaisesRegex(ValueError,'Unexpected'):
            yes_man.reply(self.config(),[])
        opener.open.side_effect=HTTPError('http://server',401,'secret must not leak',{},None)
        with patch('yes_man.build_opener',return_value=opener), self.assertRaisesRegex(ValueError,'HTTP 401'):
            yes_man.reply(self.config(),[])

if __name__=='__main__': unittest.main()
