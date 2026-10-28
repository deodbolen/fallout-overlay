"""Exercise real PTY transport, TUI scrolling and export without a desktop."""
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import shlex
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from terminal_display import TerminalScreen,pyte

ROOT=Path(__file__).resolve().parent.parent


class TerminalHistoryIntegrationTests(unittest.TestCase):
    def test_numbered_output_can_be_scrolled_and_exported_from_real_tui(self):
        with tempfile.TemporaryDirectory() as directory:
            try:master,slave=pty.openpty()
            except OSError as error:self.skipTest('PTY unavailable: '+str(error))
            fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',28,100,0,0))
            env=dict(os.environ,HOME=directory,TERM='xterm-256color',SSH_CONNECTION='test',
                     XDG_CONFIG_HOME=directory,XDG_CACHE_HOME=directory,XDG_STATE_HOME=directory,HISTFILE='/dev/null')
            env.pop('FALLOUT_EMBEDDED_SOCKET',None);env.pop('FALLOUT_SOUND_SOCKET',None)
            # Use this test's Python so the regression works on macOS and Linux.
            process=subprocess.Popen([sys.executable,str(ROOT/'scripts/browser.py')],
                                     stdin=slave,stdout=slave,stderr=slave,env=env)
            os.close(slave)
            screen=TerminalScreen(100,28);stream=pyte.ByteStream(screen)

            def pump(seconds=.1):
                deadline=time.monotonic()+seconds
                while time.monotonic()<deadline:
                    if select.select([master],[],[],.02)[0]:
                        try:stream.feed(os.read(master,65536))
                        except OSError:return

            def expect(text):
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    pump(.05)
                    if text in '\n'.join(screen.display):return
                    if process.poll() is not None:break
                self.fail('Missing '+repr(text)+'\n'+'\n'.join(screen.display))

            def send(data):os.write(master,data)

            def export_to(path):
                send(b'\x1d');expect('+ Local terminal')
                send(b'm');expect('Export plain text')
                send(b'\x1bOB'*3+b'\r');expect('EXPORT PLAIN TEXT')
                send(b'\x15'+str(path).encode()+b'\r')
                expect('Exported plain UTF-8 text')
                return path.read_text()

            try:
                expect('[SYSTEM]')
                for heading in ('[DATA]','[SSH]','[TERMINAL]'):
                    send(b'\x1bOQ');expect(heading)
                send(b'\r');expect('Session 1/1')
                code='for i in range(1,201): print(f"LINE-{i:03d} **bold** http://example.org/?a=1&b=2 漢字 😀 👩‍💻 "+"x"*180)'
                send(('python3 -c '+shlex.quote(code)+'\r').encode())
                expect('LINE-200')
                send(b'\x1bOR'*40)
                expect('LINE-001')
                send(b'\x1bOS'*40)
                expect('LINE-200')
                text=export_to(Path(directory)/'first.txt')
                numbered=re.findall(r'^LINE-(\d{3}) ',text,re.M)
                self.assertEqual(numbered,[f'{i:03d}' for i in range(1,201)])
                self.assertIn('**bold** http://example.org/?a=1&b=2 漢字 😀 👩‍💻',text)
                self.assertNotIn('http\\://',text)
                self.assertNotIn('\\*\\*bold',text)
                self.assertNotIn('\x1b',text)
                self.assertNotIn(' '*100,text)

                # A second session must neither inherit nor export the first.
                send(b'\x1bOA\r');expect('Session 2/2')
                send(b'printf SECOND_SESSION_ONLY\\n\r');expect('SECOND_SESSION_ONLY')
                other=export_to(Path(directory)/'second.txt')
                self.assertIn('SECOND_SESSION_ONLY',other)
                self.assertNotIn('LINE-001',other)
                send(b'q');expect('ACTIVE TERMINALS');send(b'\r')
                deadline=time.monotonic()+4
                while process.poll() is None and time.monotonic()<deadline:pump()
                self.assertEqual(process.wait(timeout=1),0)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                os.close(master)


if __name__=='__main__':unittest.main()
