import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import update_app


class UpdateTests(unittest.TestCase):
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

    def test_check_only_never_installs_or_restarts(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'XDG_RUNTIME_DIR':folder}), \
                patch.object(sys,'argv',['update_app.py','--check']), \
                patch('update_app.check_updates',return_value=2), \
                patch('update_app.subprocess.run') as run, patch('update_app.restart_overlay') as restart:
            update_app.main()
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
