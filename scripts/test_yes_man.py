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
        nav=Mock(); nav.screen.getdelay.return_value=-1
        with patch('yes_man.reply',return_value='OK') as reply:
            yes_man_ui.test_connection(nav,self.config())
            self.assertIn('successful',nav.message)
            self.assertEqual(reply.call_args.args[1][0]['role'],'user')
        nav.screen.timeout.assert_called_with(-1)
        with patch('yes_man.reply',side_effect=ValueError('HTTP 401')):
            yes_man_ui.test_connection(nav,self.config())
            self.assertIn('HTTP 401',nav.message)

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
