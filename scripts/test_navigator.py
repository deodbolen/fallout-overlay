import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from ssh_manager import Catalog, remote_command, ssh_args, public_key, username
from browser import Tree
from terminal_sessions import Session

class NavigatorTests(unittest.TestCase):
    def test_catalog_save_edit_and_blank_user(self):
        with tempfile.TemporaryDirectory() as d:
            catalog=Catalog(d)
            host=catalog.save_host('lab','lab.example','','')
            self.assertTrue(username(host))
            catalog.save_host('renamed','192.0.2.10','','',host['id'])
            self.assertEqual(len(catalog.read()['hosts']),1)
            self.assertEqual(catalog.path.stat().st_mode & 0o777,0o600)
            with self.assertRaises(ValueError): catalog.save_host('bad','-oProxyCommand=bad')
            with self.assertRaises(ValueError): catalog.save_host('bad','host','$(bad)')

    def test_password_and_key_auth_options(self):
        host={'address':'example.org','user':''}
        args=ssh_args(host,password_only=True)
        self.assertIn('PubkeyAuthentication=no',args)
        self.assertNotIn('StrictHostKeyChecking=no',args)
        with tempfile.NamedTemporaryFile() as key:
            args=ssh_args(host,{'path':key.name},key_only=True)
            self.assertIn('IdentitiesOnly=yes',args)
            self.assertIn('PasswordAuthentication=no',args)

    def test_remote_push_revoke_preserve_other_keys(self):
        with tempfile.TemporaryDirectory() as d:
            env=dict(os.environ,HOME=d)
            folder=Path(d)/'.ssh'; folder.mkdir()
            auth=folder/'authorized_keys'
            other='ssh-ed25519 BBBB other'
            auth.write_text(other) # no trailing newline
            line='ssh-ed25519 AAAA selected'
            for _ in range(2): subprocess.run(['sh','-c',remote_command('~/.ssh','AAAA','push',line)],env=env,check=True)
            self.assertEqual(auth.read_text().count(line),1)
            self.assertIn(other,auth.read_text())
            self.assertEqual(auth.stat().st_mode & 0o777,0o600)
            subprocess.run(['sh','-c',remote_command('~/.ssh','AAAA','revoke')],env=env,check=True)
            self.assertNotIn('AAAA',auth.read_text()); self.assertIn(other,auth.read_text())

    def test_remote_directory_is_quoted(self):
        with tempfile.TemporaryDirectory() as d:
            folder=str(Path(d)/'keys; touch INJECTED')
            subprocess.run(['sh','-c',remote_command(folder,'AAAA','push','ssh-ed25519 AAAA key')],check=True,cwd=d)
            self.assertTrue((Path(folder)/'authorized_keys').exists())
            self.assertFalse((Path(d)/'INJECTED').exists())

    def test_tree_loop_and_hidden(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'dir').mkdir(); (root/'.hidden').mkdir()
            (root/'dir'/'cycle').symlink_to(root)
            tree=Tree(root); tree.expanded={root,root/'dir',root/'dir'/'cycle'}
            self.assertEqual(len(tree.rows()),3)
            tree.hidden=True; self.assertEqual(len(tree.rows()),4)

    def test_auth_failure_offers_push_but_network_failure_does_not(self):
        from session import connect
        host={'name':'lab','address':'example.org','user':''}
        key={'path':'unused'}
        with patch('session.ssh_args',return_value=['ssh']), patch('session.interactive_ssh',return_value=(255,'Permission denied (publickey).')), patch('builtins.input',return_value='n') as prompt:
            self.assertEqual(connect(host,key),255)
            self.assertIn('Push',prompt.call_args.args[0])
        with patch('session.ssh_args',return_value=['ssh']), patch('session.interactive_ssh',return_value=(255,'Connection refused')), patch('builtins.input') as prompt:
            self.assertEqual(connect(host,key),255)
            prompt.assert_not_called()

    def test_failed_revoke_stays_tracked(self):
        from session import revoke
        record={'id':'install','host':{'name':'lab','address':'example.org','user':'test'},'directory':'~/.ssh','blob':'AAAA'}
        with patch('session.ssh_args',return_value=['ssh']), patch('session.subprocess.call',return_value=255), patch('session.Catalog') as catalog:
            self.assertEqual(revoke([record],{'path':'unused'}),255)
            catalog.assert_not_called()

    def test_key_generation_in_embedded_session(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'HOME':d,'XDG_CONFIG_HOME':str(Path(d)/'config'),'XDG_STATE_HOME':str(Path(d)/'state')}):
            session=Session('generate','generate test',name='test')
            try:
                deadline=time.monotonic()+5
                answers=0
                while time.monotonic()<deadline:
                    output=bytes(session.buffer)
                    if answers==0 and b'Enter passphrase' in output:
                        os.write(session.master,b'\n'); answers=1
                    elif answers==1 and b'Enter same passphrase' in output:
                        os.write(session.master,b'\n'); answers=2
                    if b'Key saved.' in output: break
                    time.sleep(.02)
                self.assertIn(b'Key saved.',session.buffer)
                catalog=Catalog().read()
                self.assertEqual(catalog['keys'][0]['name'],'test')
                path=Path(catalog['keys'][0]['path'])
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
                self.assertEqual(public_key(catalog['keys'][0])[0],'ssh-ed25519')
                os.write(session.master,b'\n'); session.process.wait(timeout=5)
            finally: session.close()

    def test_embedded_session_exec_and_cleanup(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'XDG_STATE_HOME':d}):
            session=Session('command','test',argv=['/bin/sh','-c','printf SESSION_OK'])
            try:
                deadline=time.monotonic()+5
                while b'SESSION_OK' not in session.buffer and time.monotonic()<deadline: time.sleep(.02)
                self.assertIn(b'SESSION_OK',session.buffer)
                os.write(session.master,b'\n')
                session.process.wait(timeout=5)
            finally: session.close()
            self.assertEqual(session.status,'closed')

if __name__=='__main__': unittest.main()
