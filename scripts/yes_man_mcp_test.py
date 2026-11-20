"""Bounded initialization-only MCP checks, isolated from the GUI process."""
import multiprocessing
import os
import signal
import time


def _initialize(server, channel):
    def terminated(*args):
        raise TimeoutError
    signal.signal(signal.SIGTERM, terminated)
    transport = None
    outcome = {'ok': False, 'error': 'MCP initialization failed. Check the connection settings.'}
    try:
        if server['transport'] == 'stdio':
            from yes_man_mcp_stdio import StdioTransport
            transport = StdioTransport(server)
            process = transport.start()
            channel.send({'pid': process.pid})
        else:
            from yes_man_mcp_http import StreamableHttpTransport
            transport = StreamableHttpTransport(server['url'], server.get('bearer_token'))
        result = transport.initialize(timeout=5)
        outcome = {'ok': True, 'protocol': result['protocolVersion']}
    except TimeoutError:
        outcome = {'ok': False, 'error': 'Connection test timed out.'}
    except ValueError:
        outcome = {'ok': False, 'error': 'Invalid configuration or incompatible MCP initialization response.'}
    except Exception:
        # Never forward raw exceptions, server messages, or credential values.
        pass
    finally:
        if server['transport'] == 'stdio' and transport is not None:
            try:
                transport.close()
                channel.send({'released': True})
            except Exception:
                outcome = {'ok': False, 'error': 'Could not finish cleanup of the temporary MCP process.'}
        try:
            channel.send(outcome)
        finally:
            channel.close()


def run_test(server):
    """Return sanitized status after initialization only, without persistence.

    A separate process makes the 20-second overall deadline enforceable even
    when an HTTP peer trickles bytes or blocks the library's socket reads.
    Temporary stdio process-group cleanup is bounded as well. Call off the UI
    thread; no stdout/stderr or credentials are passed through the result channel.
    """
    context = multiprocessing.get_context('spawn')
    reader, writer = context.Pipe(duplex=False)
    worker = context.Process(target=_initialize, args=(server, writer), daemon=True)
    pid = None
    started = False
    deadline = time.monotonic() + 20
    outcome = {'ok': False, 'error': 'Connection test timed out.'}
    try:
        worker.start()
        started = True
        writer.close()
        while time.monotonic() < deadline:
            if reader.poll(min(.1, max(0, deadline-time.monotonic()))):
                try:
                    message = reader.recv()
                except EOFError:
                    outcome = {'ok': False, 'error': 'Connection test stopped before returning a result.'}
                    break
                if 'pid' in message:
                    pid = message['pid']
                elif message.get('released'):
                    pid = None
                else:
                    outcome = message
                    break
            elif not worker.is_alive():
                outcome = {'ok': False, 'error': 'Connection test stopped before returning a result.'}
                break
    except Exception:
        outcome = {'ok': False, 'error': 'Could not run the connection test.'}
    finally:
        if started:
            if pid is not None:
                try: os.killpg(pid, signal.SIGTERM)
                except OSError: pass
            worker.join(timeout=2)
            # Consume a completed cleanup acknowledgement before escalation; the
            # process group must not be targeted after its child was reaped.
            while reader.poll(0):
                try: cleanup_message = reader.recv()
                except EOFError: break
                if cleanup_message.get('released'): pid = None
            if pid is not None:
                try: os.killpg(pid, signal.SIGKILL)
                except OSError: pass
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=2)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=2)
            if not worker.is_alive(): worker.close()
        reader.close()
        writer.close()
    return outcome
