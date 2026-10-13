#!/usr/bin/env python3
"""Check/update the installed checkout and restart its overlay after success."""
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent


def hide_overlay(runtime):
    # The external terminal deliberately has no FALLOUT_EMBEDDED_SOCKET env.
    # Locate the same host as F12 and send the GUI launcher's idempotent hide
    # command. This also works when the navigator still has older code loaded.
    from embedded_client import request
    path = runtime / 'embedded.sock'
    try:
        request('hide', socket_path=str(path), timeout=5)
    except (FileNotFoundError, ConnectionRefusedError):
        # Updating from a regular desktop terminal with no overlay is valid.
        pass


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True,
                          text=True, capture_output=True).stdout.strip()


def check_updates():
    branch = git('branch', '--show-current')
    if not branch:
        raise ValueError('Switch to a Git branch before updating.')
    if git('status', '--porcelain'):
        raise ValueError('Local changes found. Commit or stash them before updating.')
    upstream = git('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}')
    remote = git('config', 'branch.' + branch + '.remote')
    if not remote or remote == '.':
        raise ValueError('This branch needs a remote upstream before updating.')
    print('Checking ' + remote + ' / ' + upstream + '…', flush=True)
    git('fetch', remote)
    ahead, behind = map(int, git('rev-list', '--left-right', '--count', 'HEAD...' + upstream).split())
    if ahead:
        raise ValueError('This checkout has local commits. Resolve them before using Update.')
    return behind


def restart_overlay():
    path = Path(os.environ.get('XDG_RUNTIME_DIR', str(Path.home() / '.cache'))) / 'fallout-ui/embedded.sock'
    if path.exists():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5)
            client.connect(str(path))
            client.sendall(b'{"command":"shutdown_for_update"}\n')
            response = json.loads(client.makefile('rb').readline())
            if 'error' in response:
                raise ValueError(response['error'])
        deadline = time.monotonic() + 10
        while path.exists() and time.monotonic() < deadline:
            time.sleep(.1)
        if path.exists():
            raise ValueError('The overlay did not stop; restart it with F12.')
        # Shutdown releases the host lock shortly after removing its socket.
        with path.with_name('embedded.lock').open('a') as host_lock:
            while True:
                try:
                    fcntl.flock(host_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ValueError('The overlay is still stopping; restart it with F12.')
                    time.sleep(.1)
    subprocess.Popen([str(ROOT / 'scripts/terminal.sh')], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', str(Path.home() / '.cache'))) / 'fallout-ui'
    runtime.mkdir(parents=True, exist_ok=True)
    hide_overlay(runtime)
    with (runtime / 'update.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('An update is already running.')
        behind = check_updates()
        if not behind:
            print('System up to date.', flush=True)
            return False
        print(f'{behind} new commit(s) available.', flush=True)
        print('Pulling latest version…', flush=True)
        subprocess.run(['git', '-C', str(ROOT), 'pull', '--ff-only'], check=True)
        print('Running installer. Enter your sudo password if prompted.', flush=True)
        subprocess.run([str(ROOT / 'install.sh')], cwd=ROOT, check=True)
        # Refresh desktop effects using the updated code and saved preferences.
        from crt_settings import preferences, SCRIPT, running
        settings = preferences()
        subprocess.run([sys.executable, str(SCRIPT), '--stop'], check=True)
        if settings.get('crt_overlay') or settings.get('crt_animation'):
            deadline = time.monotonic() + 5
            while running() and time.monotonic() < deadline:
                time.sleep(.1)
            if running():
                raise ValueError('CRT overlay did not stop; restart it from Settings.')
            subprocess.Popen([sys.executable, str(SCRIPT)], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print('Installation succeeded. Closing sessions and restarting the overlay…', flush=True)
        restart_overlay()
        print('Update complete.', flush=True)
        return True


if __name__ == '__main__':
    try:
        updated = main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('\nUpdate stopped: ' + str(error), file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        try: input('\nPress Enter to close this update window. ')
        except (EOFError, KeyboardInterrupt): pass
        sys.exit(1)
    if not updated:
        try: input('\nPress Enter to close this window. ')
        except (EOFError, KeyboardInterrupt): pass
