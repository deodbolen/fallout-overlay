"""In-process PTY sessions: attach directly, detach with Ctrl+], keep running."""
import curses
import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import tty
import uuid
from pathlib import Path
from ssh_manager import state_dir, atomic_json
from terminal_display import TerminalScreen, render, pyte
from session_input import InputRouter

class Session:
    def __init__(self,action,label,**details):
        self.id=uuid.uuid4().hex
        self.label=label
        self.path=state_dir()/'sessions'/(self.id+'.json')
        atomic_json(self.path,{'id':self.id,'action':action,'label':label,'created':time.time(),'status':'starting',**details})
        self.master,slave=pty.openpty()
        try: size=os.get_terminal_size(sys.stdin.fileno())
        except OSError: size=os.terminal_size((100,30))
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',max(1,size.lines-1),size.columns,0,0))
        env=dict(os.environ,TERM=os.environ.get('TERM','xterm-256color'))
        def child_setup():
            os.setsid(); fcntl.ioctl(0,termios.TIOCSCTTY,0)
        self.process=subprocess.Popen(['/usr/bin/python3',str(Path(__file__).with_name('session.py')),str(self.path)],stdin=slave,stdout=slave,stderr=slave,env=env,preexec_fn=child_setup)
        os.close(slave)
        self.buffer=bytearray(); self.lock=threading.Lock(); self.attached=False; self.truncated=False
        self.display=TerminalScreen(size.columns,max(1,size.lines-1),self._reply)
        self.stream=pyte.ByteStream(self.display)
        self.revision=0
        self.reader=threading.Thread(target=self._read,daemon=True); self.reader.start()

    def _reply(self,data):
        try: os.write(self.master,data)
        except OSError: pass

    def _read(self):
        while True:
            try: output=os.read(self.master,65536)
            except OSError: break
            if not output: break
            with self.lock:
                self.stream.feed(output)
                self.revision+=1
                self.buffer.extend(output)
                if len(self.buffer)>4*1024*1024:
                    del self.buffer[:len(self.buffer)-4*1024*1024]; self.truncated=True


    @property
    def status(self):
        if self.process.poll() is not None: return 'closed'
        try: return json.loads(self.path.read_text())['status']
        except (OSError,ValueError): return 'running'

    def attach(self,screen,router=None,pending=b''):
        if self.process.poll() is not None: return None,b''
        router=router or InputRouter()
        pending_since=None
        fd=sys.stdin.fileno(); original=termios.tcgetattr(fd)
        curses.def_prog_mode(); curses.endwin()
        try:
            tty.setraw(fd)
            size=os.get_terminal_size(fd)
            fcntl.ioctl(self.master,termios.TIOCSWINSZ,struct.pack('HHHH',max(1,size.lines-1),size.columns,0,0))
            with self.lock:
                self.display.resize(lines=max(1,size.lines-1),columns=size.columns)
                os.write(sys.stdout.fileno(),b'\x1b[0m\x1b[2J\x1b[H')
                os.write(sys.stdout.fileno(),render(self.display,size.lines,size.columns,full=True))
                self.attached=True
                painted=self.revision
            while self.process.poll() is None:
                if pending or select.select([fd],[],[],.03)[0]:
                    data=pending or os.read(fd,4096)
                    pending=b''
                    if not data: break
                    forward,action,remainder=router.feed(data)
                    if forward: os.write(self.master,forward)
                    if action: return action,remainder
                    pending_since=time.monotonic() if router.pending else None
                elif router.pending and pending_since is not None and time.monotonic()-pending_since>.1:
                    os.write(self.master,router.flush()); pending_since=None
                newsize=os.get_terminal_size(fd)
                if newsize!=size:
                    size=newsize
                    fcntl.ioctl(self.master,termios.TIOCSWINSZ,struct.pack('HHHH',max(1,size.lines-1),size.columns,0,0))
                    with self.lock: self.display.resize(lines=max(1,size.lines-1),columns=size.columns)
                with self.lock:
                    if self.display.dirty or self.revision!=painted:
                        os.write(sys.stdout.fileno(),render(self.display,size.lines,size.columns))
                        painted=self.revision
        finally:
            with self.lock: self.attached=False
            termios.tcsetattr(fd,termios.TCSADRAIN,original)
            # Restore ordinary terminal modes after SSH/full-screen programs.
            os.write(sys.stdout.fileno(),b'\x1b[?1049l\x1b[?1l\x1b[?2004l\x1b[0m\x1b[?25h')
            curses.reset_prog_mode(); screen.clear(); screen.refresh()
        return None,b''

    def close(self):
        if self.process.poll() is None:
            # The remote shell is a foreground process group inside this PTY.
            try:
                foreground=os.tcgetpgrp(self.master)
                if foreground!=os.getpgrp(): os.killpg(foreground,signal.SIGHUP)
            except (OSError,ProcessLookupError): pass
            try: os.killpg(self.process.pid,signal.SIGHUP)
            except ProcessLookupError: pass
        try: os.close(self.master)
        except OSError: pass
        try:
            data=json.loads(self.path.read_text()); data['status']='closed'; atomic_json(self.path,data)
        except (OSError,ValueError): pass

class Sessions:
    def __init__(self): self.items=[]
    def launch(self,action,label,**details):
        session=Session(action,label,**details); self.items.append(session); return session
    def attach(self,screen,session,on_switch=lambda session: None):
        router=InputRouter(); pending=b''
        while session.process.poll() is None:
            on_switch(session)
            action,pending=session.attach(screen,router,pending)
            if action not in ('next','previous'): return
            active=[s for s in self.items if s.process.poll() is None and s.status in ('running','starting')]
            if not active: continue
            step=1 if action=='next' else -1
            if session in active:
                session=active[(active.index(session)+step)%len(active)]
            else: session=active[0 if step==1 else -1]

    def close(self):
        for session in self.items: session.close()
