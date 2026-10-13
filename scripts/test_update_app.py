import os
from pathlib import Path
import subprocess
import json
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import update_app


class UpdateTests(unittest.TestCase):
    def test_external_updater_hides_running_host_before_check_even_on_failure(self):
        # Exercise the actual socket bridge, without the navigator's environment
        # or a running GTK desktop. The host acknowledges the same command that
        # opening a GUI application sends.
        for failed_check in (False, True):
            with self.subTest(failed_check=failed_check), tempfile.TemporaryDirectory(dir='/tmp') as folder:
                runtime=Path(folder)/'fallout-ui'
                runtime.mkdir()
                commands=[]
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
                    listener.bind(str(runtime/'embedded.sock'))
                    listener.listen(1)
                    listener.settimeout(3)
                    def host():
                        with listener.accept()[0] as connection:
                            commands.append(json.loads(connection.makefile('rb').readline()))
                            connection.sendall(b'{}\n')
                    worker=threading.Thread(target=host,daemon=True)
                    worker.start()
                    def check():
                        self.assertEqual(commands,[{'command':'hide'}])
                        if failed_check:
                            raise ValueError('Network unavailable')
                        return 0
                    env={key:value for key,value in os.environ.items() if key!='FALLOUT_EMBEDDED_SOCKET'}
                    env['XDG_RUNTIME_DIR']=folder
                    try:
                        with patch.dict(os.environ,env,clear=True), patch('update_app.check_updates',side_effect=check):
                            if failed_check:
                                with self.assertRaisesRegex(ValueError,'Network unavailable'):
                                    update_app.main()
                            else:
                                self.assertFalse(update_app.main())
                    finally:
                        worker.join(3)
                    self.assertFalse(worker.is_alive())

    def test_check_fetches_upstream_and_reports_new_commits(self):
        with patch('update_app.git',side_effect=['main','','origin/main','origin','','0\t3']) as git:
            self.assertEqual(update_app.check_updates(),3)
            git.assert_any_call('fetch','origin')

    def test_local_changes_and_commits_are_not_overwritten(self):
        with patch('update_app.git',side_effect=['main',' M scripts/browser.py']) as git:
            with self.assertRaisesRegex(ValueError,'Local changes'):
                update_app.check_updates()
            self.assertEqual(git.call_count,2)
        with patch('update_app.git',side_effect=['main','','origin/main','origin','','1\t2']):
            with self.assertRaisesRegex(ValueError,'local commits'):
                update_app.check_updates()

    def test_up_to_date_never_installs_or_restarts(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'XDG_RUNTIME_DIR':folder}), \
                patch.object(sys,'argv',['update_app.py']), \
                patch('update_app.check_updates',return_value=0), \
                patch('update_app.subprocess.run') as run, patch('update_app.restart_overlay') as restart:
            self.assertFalse(update_app.main())
            run.assert_not_called(); restart.assert_not_called()

    def test_installer_failure_does_not_restart(self):
        failure=subprocess.CalledProcessError(1,['install.sh'])
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'XDG_RUNTIME_DIR':folder}), \
                patch.object(sys,'argv',['update_app.py']), \
                patch('update_app.check_updates',return_value=1), \
                patch('update_app.subprocess.run',side_effect=[Mock(),failure]), \
                patch('update_app.restart_overlay') as restart:
            with self.assertRaises(subprocess.CalledProcessError): update_app.main()
            restart.assert_not_called()

    def test_restart_follows_successful_install(self):
        effects=SimpleNamespace(preferences=lambda:{},SCRIPT=Path('/fake/crt_overlay.py'),running=lambda:False)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'XDG_RUNTIME_DIR':folder}), \
                patch.object(sys,'argv',['update_app.py']), \
                patch.dict(sys.modules,{'crt_settings':effects}), \
                patch('update_app.check_updates',return_value=1), \
                patch('update_app.subprocess.run') as run, patch('update_app.restart_overlay') as restart:
            update_app.main()
            self.assertEqual(run.call_args_list[0].args[0][-2:],['pull','--ff-only'])
            self.assertEqual(run.call_args_list[1].args[0],[str(update_app.ROOT/'install.sh')])
            restart.assert_called_once()


if __name__=='__main__': unittest.main()
