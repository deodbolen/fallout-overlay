import sys
import subprocess
import unittest
from unittest.mock import patch
from session import interactive_ssh
class FeedbackTests(unittest.TestCase):
    def run_ssh(self,output,code):
        # Substitute a local process for SSH; no network or credentials involved.
        original=subprocess.Popen
        def fake_spawn(args,**kwargs):
            self.assertEqual(args[1],'-v')
            return original([args[0],*args[2:]],**kwargs)
        with patch('session.sound') as sound, patch('session.os.write'), patch('session.subprocess.Popen',side_effect=fake_spawn):
            result=interactive_ssh([sys.executable,'-c',f'import sys;sys.stderr.write({output!r});sys.exit({code})'])
        return result,[c.args[0] for c in sound.call_args_list]
    def test_establishment_and_normal_logout(self):
        result,sounds=self.run_ssh('debug1: Entering interactive session.\n',0)
        self.assertEqual(sounds,['good']);self.assertEqual(result,(0,''))
    def test_authentication_failure(self):
        result,sounds=self.run_ssh('Permission denied (publickey).\n',255)
        self.assertEqual(sounds,['bad']);self.assertIn('Permission denied',result[1])
    def test_network_failure(self):
        result,sounds=self.run_ssh('Connection refused\n',255)
        self.assertEqual(sounds,['bad'])
if __name__=='__main__':unittest.main()
