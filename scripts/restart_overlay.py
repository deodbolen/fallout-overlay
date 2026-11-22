#!/usr/bin/env python3
"""Restart the desktop host independently of its navigator process."""
import fcntl
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import time


def main():
    directory = Path(os.environ.get('XDG_RUNTIME_DIR', str(Path.home() / '.cache'))) / 'fallout-ui'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / 'restart.lock').open('a') as restart_lock:
        os.fchmod(restart_lock.fileno(), 0o600)
        try:
            fcntl.flock(restart_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        # Identify the actual socket owner instead of matching arbitrary PIDs.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(str(directory / 'embedded.sock'))
            pid, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != os.getuid() or pid <= 1:
                raise RuntimeError('Cannot identify the overlay host.')
            os.kill(pid, signal.SIGTERM)
            with (directory / 'embedded.lock').open('a') as host_lock:
                deadline = time.monotonic() + 3
                forced = False
                while True:
                    try:
                        fcntl.flock(host_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            if forced:
                                raise RuntimeError('Overlay host did not stop.')
                            try:
                                os.kill(pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            forced = True
                            deadline = time.monotonic() + 3
                        time.sleep(.1)
        subprocess.Popen([str(Path(__file__).with_name('terminal.sh')), '--desktop'],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
