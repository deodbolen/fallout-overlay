"""Explicitly owned MCP stdio subprocess lifecycle; no protocol handling."""
from contextlib import contextmanager
import json
import math
import os
import select
import subprocess
import threading
import time


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
        self._receive_lock = threading.Lock()
        self._receive_process = None
        self._receive_buffer = bytearray()
        self._receive_failed = False
        self._request_lock = threading.Lock()
        self._next_request_id = 1
        self._request_process = None
        self._pending_responses = []

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

    def receive(self, timeout=10):
        """Return one UTF-8 JSON dictionary with a whole-message deadline.

        JSON payloads may contain at most 1 MiB, excluding the newline. Partial
        lines survive timeouts; bytes after a newline remain for the next call.
        Oversize input requires a process restart because framing is no longer
        trusted. No stderr input, background readers, or message logging is used.
        """
        try:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise ValueError
            timeout = float(timeout)
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError
        except (ValueError, OverflowError):
            raise ValueError('MCP receive timeout must be a positive finite number.') from None
        deadline = time.monotonic() + timeout

        @contextmanager
        def state_lock():
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._lock.acquire(timeout=min(remaining, threading.TIMEOUT_MAX)):
                raise TimeoutError('Timed out waiting for the MCP transport.')
            try:
                yield
            finally:
                self._lock.release()

        while not self._receive_lock.acquire(timeout=min(timeout, 0.1)):
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise TimeoutError('Timed out waiting for an MCP message.')
        try:
            with state_lock():
                process = self.process
                if process is None:
                    raise RuntimeError('MCP stdio transport is not started or has closed.')
                if self._receive_process is not process:
                    self._receive_process = process
                    self._receive_buffer.clear()
                    self._receive_failed = False
            limit = 1024 * 1024
            while True:
                with state_lock():
                    if self.process is not process:
                        raise RuntimeError('MCP stdio transport closed or restarted during receive.')
                    pipe = process.stdout
                    if pipe is None or pipe.closed:
                        raise RuntimeError('MCP server stdout is unavailable.')
                    if self._receive_failed:
                        raise ValueError('MCP message exceeded 1 MiB; restart the transport before receiving again.')
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Timed out waiting for a complete MCP message.')
                    newline = self._receive_buffer.find(b'\n')
                    if newline >= 0:
                        raw = bytes(self._receive_buffer[:newline])
                        del self._receive_buffer[:newline + 1]
                        break
                    if len(self._receive_buffer) > limit:
                        self._receive_buffer.clear()
                        self._receive_failed = True
                        raise ValueError('MCP message exceeds the 1 MiB limit.')
                    descriptor = pipe.fileno()
                try:
                    readable, _, _ = select.select([descriptor], [], [], min(remaining, 0.1))
                    with state_lock():
                        if self.process is not process or pipe.closed:
                            raise RuntimeError('MCP stdio transport closed or restarted during receive.')
                        if not readable:
                            if process.poll() is not None:
                                raise RuntimeError('MCP server exited before completing a message.')
                            continue
                        blocking = os.get_blocking(descriptor)
                        try:
                            os.set_blocking(descriptor, False)
                            chunk = os.read(descriptor, min(65536, limit + 1 - len(self._receive_buffer)))
                        except BlockingIOError:
                            continue
                        finally:
                            os.set_blocking(descriptor, blocking)
                        if not chunk:
                            raise RuntimeError('MCP server exited or closed stdout before completing a message.')
                        self._receive_buffer.extend(chunk)
                except TimeoutError:
                    raise
                except (OSError, ValueError):
                    raise RuntimeError('Could not read MCP server stdout; the pipe may be closed.') from None
            try:
                text = raw.decode('utf-8')
            except UnicodeError:
                raise ValueError('MCP message contains invalid UTF-8.') from None
            def reject_constant(value):
                raise ValueError('Non-JSON numeric constant.')
            try:
                message = json.loads(text, parse_constant=reject_constant)
            except (ValueError, RecursionError):
                raise ValueError('MCP message contains invalid JSON.') from None
            if not isinstance(message, dict):
                raise ValueError('MCP message must be a JSON dictionary.')
            return message
        finally:
            self._receive_lock.release()

    def request(self, method, params=None, timeout=10):
        """Send one JSON-RPC request and return its ID-matched result.

        Only one request may be outstanding. Notifications are consumed without
        execution; server requests are explicitly rejected. Unmatched responses
        are retained for this process (up to 64); reaching that bound raises an
        error before consuming more input. No background reader is introduced.
        """
        if not isinstance(method, str) or not method.strip():
            raise ValueError('JSON-RPC method must be a nonempty string.')
        if params is not None and not isinstance(params, (dict, list)):
            raise ValueError('JSON-RPC params must be a dictionary or list.')
        try:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise ValueError
            timeout = float(timeout)
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError
        except (ValueError, OverflowError):
            raise ValueError('MCP request timeout must be a positive finite number.') from None
        deadline = time.monotonic() + timeout
        if not self._request_lock.acquire(blocking=False):
            raise RuntimeError('An MCP stdio request is already outstanding.')

        def remaining():
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError('MCP request timed out.')
            return left

        class DeadlineInput:
            # send() still owns framing and full-write handling. This temporary
            # unbuffered adapter makes its pipe writes obey the same deadline.
            def __init__(self, pipe):
                self.pipe = pipe
                self.descriptor = pipe.fileno()

            @property
            def closed(self):
                return self.pipe.closed

            def write(self, data):
                while True:
                    _, writable, _ = select.select([], [self.descriptor], [], remaining())
                    if not writable:
                        raise TimeoutError('MCP request timed out sending.')
                    remaining()
                    try:
                        return os.write(self.descriptor, data)
                    except BlockingIOError:
                        continue

            def flush(self):
                remaining()  # Writes above go directly to the pipe.

        try:
            if not self._lock.acquire(timeout=min(remaining(), threading.TIMEOUT_MAX)):
                raise TimeoutError('MCP request timed out waiting for transport.')
            try:
                process = self.process
                if process is None or process.poll() is not None:
                    raise RuntimeError('MCP server process is not running.')
                if self._request_process is not process:
                    self._request_process = process
                    self._pending_responses = []
                identifier = self._next_request_id
                self._next_request_id += 1
                message = {'jsonrpc': '2.0', 'id': identifier, 'method': method}
                if params is not None:
                    message['params'] = params
                pipe = process.stdin
                if pipe is None or pipe.closed:
                    raise RuntimeError('MCP server stdin is unavailable.')
                blocking = os.get_blocking(pipe.fileno())
                try:
                    os.set_blocking(pipe.fileno(), False)
                    process.stdin = DeadlineInput(pipe)
                    try:
                        self.send(message)
                    except RuntimeError:
                        remaining()  # Preserve TimeoutError despite send's I/O wrapper.
                        raise
                finally:
                    process.stdin = pipe
                    os.set_blocking(pipe.fileno(), blocking)
            finally:
                self._lock.release()

            while True:
                remaining()
                if self.process is not process:
                    raise RuntimeError('MCP transport closed or restarted during request.')
                matched = next((index for index, response in enumerate(self._pending_responses)
                                if type(response['id']) is int and response['id'] == identifier), None)
                if matched is not None:
                    response = self._pending_responses.pop(matched)
                else:
                    if len(self._pending_responses) >= 64:
                        raise RuntimeError('MCP unmatched-response buffer is full; restart the transport.')
                    response = self.receive(timeout=remaining())
                    if self.process is not process:
                        raise RuntimeError('MCP transport closed or restarted during request.')
                    if response.get('jsonrpc') != '2.0':
                        raise ValueError('Invalid JSON-RPC response version.')
                    if 'method' in response:
                        if 'id' in response:
                            raise ValueError('Server-initiated JSON-RPC requests are not supported.')
                        if (not isinstance(response['method'], str) or not response['method'].strip() or
                                'result' in response or 'error' in response or
                                ('params' in response and not isinstance(response['params'], (dict, list)))):
                            raise ValueError('Malformed JSON-RPC notification.')
                        continue
                    if ('id' not in response or
                            (response['id'] is not None and type(response['id']) not in (int, str)) or
                            ('result' in response) == ('error' in response)):
                        raise ValueError('Malformed JSON-RPC response.')
                    if 'error' in response:
                        error = response['error']
                        if (not isinstance(error, dict) or type(error.get('code')) is not int or
                                not isinstance(error.get('message'), str)):
                            raise ValueError('Malformed JSON-RPC error response.')
                    if type(response['id']) is not int or response['id'] != identifier:
                        self._pending_responses.append(response)
                        continue
                if time.monotonic() >= deadline:
                    self._pending_responses.append(response)
                    raise TimeoutError('MCP request timed out.')
                if 'error' in response:
                    # Do not expose server error text/data, which may contain secrets.
                    raise RuntimeError('MCP JSON-RPC request failed with error code ' + str(response['error']['code']) + '.')
                return response['result']
        finally:
            self._request_lock.release()

    def initialize(self, timeout=10):
        """Negotiate MCP 2024-11-05 on an explicitly started transport."""
        with self._lock:
            process = self.process
            if process is None or process.poll() is not None:
                raise RuntimeError('MCP initialization requires a running transport.')
        protocol_version = '2024-11-05'
        result = self.request('initialize', {
            'protocolVersion': protocol_version,
            'capabilities': {},
            'clientInfo': {'name': 'yes-man-mcp', 'version': '0.1.0'},
        }, timeout=timeout)
        if not isinstance(result, dict):
            raise ValueError('Malformed MCP initialization result.')
        if result.get('protocolVersion') != protocol_version:
            raise ValueError('Unsupported MCP initialization protocol version.')
        if not isinstance(result.get('capabilities'), dict):
            raise ValueError('MCP initialization requires a capabilities object.')
        server_info = result.get('serverInfo')
        if (not isinstance(server_info, dict) or
                any(not isinstance(server_info.get(field), str) or not server_info[field].strip()
                    for field in ('name', 'version'))):
            raise ValueError('MCP initialization requires serverInfo with nonempty name and version strings.')
        with self._lock:
            if self.process is not process:
                raise RuntimeError('MCP transport closed or restarted during initialization.')
            self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return result

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
