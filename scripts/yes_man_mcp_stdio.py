"""Explicitly owned MCP stdio subprocess lifecycle; no protocol handling."""
import json
import os
import subprocess
import threading


class StdioTransport:
    """Own one process launched from trusted, validated local configuration.

    Constructing the transport never starts a process. Only trusted application
    code may provide configuration and call start(); model-generated commands
    must never be passed here. The owner must call close() when finished.
    process exposes the three separate binary pipes for later protocol support.
    No background readers or automatic protocol messages are introduced here.
    """

    def __init__(self, server):
        if not isinstance(server, dict) or server.get('transport') != 'stdio':
            raise ValueError('StdioTransport requires a validated stdio server configuration.')
        self._argv = [server['command']] + list(server.get('args', []))
        self._cwd = server.get('cwd')
        if 'cwd' in server and (not isinstance(self._cwd, str) or not self._cwd.strip()):
            raise ValueError('Configured working directory must be a nonempty string.')
        # Do not inherit arbitrary credentials, shell hooks, Python injection
        # variables, or the LLM's bearer token from the parent environment.
        self._env = {'PATH': os.defpath}
        for name in ('HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR'):
            if name in os.environ:
                self._env[name] = os.environ[name]
        self._env.update(dict(server.get('env', {})))
        self.process = None
        self._lock = threading.RLock()

    def start(self):
        """Launch explicitly, or return the already running owned process.

        Startup errors propagate. Popen cleans its newly allocated resources if
        creation/exec fails; the transport acquires ownership only on success.
        stderr is never merged into stdout and no shell evaluates arguments.
        """
        with self._lock:
            if self.process is not None:
                if self.process.poll() is None:
                    return self.process
                self.close()
            options = {}
            if self._cwd is not None:
                options['cwd'] = self._cwd
            self.process = subprocess.Popen(
                self._argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=dict(self._env), shell=False,
                close_fds=True, start_new_session=True, **options)
            return self.process

    def send(self, message):
        """Write one compact UTF-8 JSON line without logging its contents."""
        if not isinstance(message, dict):
            raise ValueError('MCP message must be a dictionary.')
        try:
            data = (json.dumps(message, ensure_ascii=False, separators=(',', ':'),
                               allow_nan=False) + '\n').encode('utf-8')
        except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
            raise ValueError('MCP message could not be serialized as UTF-8 JSON.') from None
        with self._lock:
            process = self.process
            if process is None:
                raise RuntimeError('MCP stdio transport is not started or has closed.')
            if process.poll() is not None:
                raise RuntimeError('MCP server process has exited.')
            pipe = process.stdin
            if pipe is None or pipe.closed:
                raise RuntimeError('MCP server stdin is unavailable.')
            try:
                remaining = memoryview(data)
                while remaining:
                    written = pipe.write(remaining)
                    if written is None or written <= 0 or written > len(remaining):
                        raise RuntimeError('MCP server stdin could not accept the complete message.')
                    remaining = remaining[written:]
                pipe.flush()
            except (OSError, ValueError):
                raise RuntimeError('Could not write to MCP server stdin; the pipe may be closed.') from None

    def close(self):
        """Terminate and reap the child, escalating after three seconds.

        Repeated calls are safe. A forced kill also has a bounded three-second
        wait; if the OS cannot reap the child, TimeoutExpired propagates and its
        handle is retained so the owner can retry cleanup. Pipes still close.
        This owns the direct child, not independently detached descendants.
        """
        with self._lock:
            process = self.process
            if process is None:
                return
            try:
                if process.poll() is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=3)
            finally:
                for pipe in (process.stdin, process.stdout, process.stderr):
                    if pipe is not None:
                        pipe.close()
            self.process = None
