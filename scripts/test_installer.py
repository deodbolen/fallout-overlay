import os
from pathlib import Path
import subprocess
import tempfile
import unittest
SCRIPT=Path(__file__).with_name('install_dependencies.sh').resolve()
class DependencyTests(unittest.TestCase):
    def simulate(self,missing=True,check=False,fail=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);log=root/'calls'
            commands={
                'dpkg-query': '#!/bin/sh\n'+('case "$*" in *nano*) exit 1;; esac\n' if missing else '')+"printf 'install ok installed'\n",
                'id':'#!/bin/sh\necho 1000\n',
                'apt-get':'#!/bin/sh\nexit 0\n',
                'sudo':f'#!/bin/sh\necho "$*" >> "$TEST_LOG"\n'+('exit 1\n' if fail else 'if [ "$2" = install ]; then sed -i "/case /d" "$TEST_BIN/dpkg-query"; fi\nexit 0\n')}
            for name,source in commands.items():
                path=root/name;path.write_text(source);path.chmod(0o755)
            result=subprocess.run(['/bin/sh',str(SCRIPT)]+(['--check'] if check else []),env={**os.environ,'PATH':str(root)+':/usr/bin:/bin','TEST_LOG':str(log),'TEST_BIN':str(root)},capture_output=True,text=True)
            return result,log.read_text() if log.exists() else ''
    def test_complete_install_is_noop(self):
        result,log=self.simulate(missing=False)
        self.assertEqual(result.returncode,0);self.assertEqual(log,'')
    def test_check_does_not_install(self):
        result,log=self.simulate(check=True)
        self.assertEqual(result.returncode,1);self.assertEqual(log,'');self.assertIn('nano',result.stdout)
    def test_install_only_missing_then_recheck(self):
        result,log=self.simulate()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(log,'apt-get update\napt-get install -y nano\n')
    def test_apt_failure_stops(self):
        result,log=self.simulate(fail=True)
        self.assertNotEqual(result.returncode,0);self.assertEqual(log,'apt-get update\n')
if __name__=='__main__':unittest.main()
