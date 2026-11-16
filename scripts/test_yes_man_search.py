import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit, parse_qs
import yes_man
import yes_man_search as search


class SearchTests(unittest.TestCase):
    def config(self,protocol='OpenAI compatible'):
        return dict(yes_man.DEFAULT,model='FortiLab',protocol=protocol,
                    search_enabled=True,search_url='http://search.local:8080')

    def test_searxng_query_bounded_results_and_no_llm_key(self):
        opener=MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value=json.dumps({'results':[
            {'title':'<b>A</b> &amp; B','url':'https://example.org/'+str(i),'content':'snippet'} for i in range(10)
        ]}).encode()
        with patch('yes_man_search.build_opener',return_value=opener):
            result=search.search('http://search.local:8080','hello & 日本語')
        request=opener.open.call_args.args[0]
        self.assertEqual(parse_qs(urlsplit(request.full_url).query),{'q':['hello & 日本語'],'format':['json']})
        self.assertEqual(urlsplit(request.full_url).path,'/search')
        self.assertEqual(len(result['results']),5)
        self.assertEqual(result['results'][0]['title'],'A & B')
        self.assertIsNone(request.get_header('Authorization'))

    def test_tool_round_trip_for_both_protocols(self):
        for protocol in ('OpenAI compatible','Ollama'):
            arguments={'query':'Linux release'}
            call={'id':'call-1','type':'function','function':{'name':'web_search',
                  'arguments':arguments if protocol=='Ollama' else json.dumps(arguments)}}
            results={'results':[{'url':'https://kernel.org','title':'Linux','snippet':'release'}]}
            history=[{'role':'user','content':'Latest Linux?'}]
            with patch('yes_man._completion',side_effect=[{'tool_calls':[call]},{'content':'Found Linux.'}]) as complete, \
                 patch('yes_man_search.search',return_value=results) as searching:
                answer=yes_man.reply(self.config(protocol),history)
                searching.assert_called_once_with('http://search.local:8080','Linux release')
                tool=complete.call_args.args[1][-1]
                self.assertEqual(tool['role'],'tool')
                self.assertEqual(tool['tool_name'] if protocol=='Ollama' else tool['tool_call_id'],
                                 'web_search' if protocol=='Ollama' else 'call-1')
                self.assertIn('https://kernel.org',answer)
            self.assertEqual(len(history),1)

    def test_disabled_search_and_unknown_tools_do_not_execute(self):
        call={'id':'x','function':{'name':'run_shell','arguments':'{}'}}
        with patch('yes_man._completion',return_value={'tool_calls':[call]}), \
             patch('yes_man_search.search') as searching:
            with self.assertRaises(ValueError): yes_man.reply(dict(self.config(),search_enabled=False),[])
            searching.assert_not_called()
        with patch('yes_man._completion',side_effect=[{'tool_calls':[call]},{'content':'Unavailable'}]) as complete, \
             patch('yes_man_search.search') as searching:
            yes_man.reply(self.config(),[])
            searching.assert_not_called()
            self.assertIn('Unsupported tool',complete.call_args.args[1][-1]['content'])

    def test_failures_and_repeated_calls_are_bounded(self):
        call={'id':'x','function':{'name':'web_search','arguments':'{"query":"test"}'}}
        with patch('yes_man._completion',return_value={'tool_calls':[call]}) as complete, \
             patch('yes_man_search.search',side_effect=ValueError('Search offline')) as searching:
            with self.assertRaisesRegex(ValueError,'limit'): yes_man.reply(self.config(),[])
            self.assertEqual(searching.call_count,3)
            self.assertEqual(complete.call_count,4)
        for query in ('','x'*513):
            with self.assertRaises(ValueError): search.search('http://search.local',query)
        for url in ('file:///etc/passwd','https://user:secret@host'):
            with self.assertRaises(ValueError): search.validate_url(url)

if __name__=='__main__': unittest.main()
