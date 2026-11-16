"""Focused evidence integration regressions. No live requests required."""
import unittest
from unittest.mock import patch
from yes_man_sources import retrieve_search_results, source_footer, MAX_EXCERPT


class PageEvidenceTests(unittest.TestCase):
    def test_reads_pages_caps_excerpts_and_preserves_search_result(self):
        original={'results':[{'url':'https://example.org/article','snippet':'search snippet'}]}
        cache={}
        with patch('yes_man_sources.retrieve_page',return_value={
                'ok':True,'text':'a'*(MAX_EXCERPT+1),'final_url':'https://example.org/final',
                'truncated':False,'error':None}) as fetch:
            result=retrieve_search_results(original,cache)
            retrieve_search_results(original,cache)
        fetch.assert_called_once_with('https://example.org/article')
        self.assertNotIn('page',original['results'][0])
        page=result['results'][0]['page']
        self.assertTrue(page['ok'])
        self.assertTrue(page['truncated'])
        self.assertEqual(len(page['text']),MAX_EXCERPT)
        footer=source_footer(cache,['https://example.org/article'])
        self.assertIn('Retrieved pages',footer)
        self.assertIn('https://example.org/final',footer)
        self.assertNotIn('Search-only',footer)

    def test_reply_budget_spans_multiple_searches(self):
        cache={}
        with patch('yes_man_sources.retrieve_page',return_value={
                'ok':False,'text':'','error':'blocked_destination'}) as fetch:
            first=retrieve_search_results({'results':[{'url':'https://example.org/'+str(i)} for i in range(5)]},cache)
            retrieve_search_results({'results':[{'url':'https://other.org/page'}]},cache)
        self.assertEqual(fetch.call_count,3)
        self.assertEqual(first['results'][3]['page']['error'],'reply_retrieval_limit')
        self.assertTrue(all(not row['page']['ok'] for row in first['results']))
        footer=source_footer(cache,[row['url'] for row in first['results']])
        self.assertIn('No article content could be retrieved',footer)
        self.assertIn('blocked_destination',footer)
        self.assertIn('Search-only',footer)

    def test_failed_retrieval_never_uses_snippet_as_page_text(self):
        with patch('yes_man_sources.retrieve_page',return_value={
                'ok':False,'text':'','error':'timeout'}):
            result=retrieve_search_results({'results':[{'url':'https://example.org',
                                                       'snippet':'Unverified claim'}]}, {})
        page=result['results'][0]['page']
        self.assertEqual(page['text'],'')
        self.assertFalse(page['ok'])
        self.assertEqual(page['error'],'timeout')

if __name__=='__main__': unittest.main()
