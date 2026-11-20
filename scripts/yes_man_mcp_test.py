"""Bounded MCP initialization and read-only discovery, isolated from the GUI."""
import json
import multiprocessing
import os
import signal
import time


def _initialize(server, channel, discover=False):
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
        if discover:
            tools = []
            names = set()
            cursors = set()
            cursor = None
            total_bytes = 0
            for page in range(10):
                listed = transport.request('tools/list', {'cursor': cursor} if cursor is not None else None, timeout=5)
                if not isinstance(listed, dict) or not isinstance(listed.get('tools'), list):
                    raise ValueError
                for tool in listed['tools']:
                    if (not isinstance(tool, dict) or not isinstance(tool.get('name'), str) or
                            not tool['name'].strip() or len(tool['name']) > 256 or
                            not isinstance(tool.get('description', ''), str) or
                            not isinstance(tool.get('inputSchema'), dict) or
                            tool['name'] in names or len(tools) >= 256):
                        raise ValueError
                    definition = {'name': tool['name'], 'description': tool.get('description', '')[:4000],
                                  'inputSchema': tool['inputSchema']}
                    total_bytes += len(json.dumps(definition).encode('utf-8'))
                    if total_bytes > 2 * 1024 * 1024:
                        raise ValueError
                    names.add(tool['name'])
                    tools.append(definition)
                cursor = listed.get('nextCursor')
                if cursor is None:
                    break
                if not isinstance(cursor, str) or not cursor or cursor in cursors or len(cursor) > 4096:
                    raise ValueError
                cursors.add(cursor)
            else:
                raise ValueError
            outcome['tools'] = tools
    except TimeoutError:
        outcome = {'ok': False, 'error': 'Tool discovery timed out.' if discover else 'Connection test timed out.'}
    except ValueError:
        outcome = {'ok': False, 'error': 'Invalid MCP tool list, incompatible initialization, or discovery limit exceeded.' if discover
                   else 'Invalid configuration or incompatible MCP initialization response.'}
    except Exception:
        # Never forward raw exceptions, server messages, or credential values.
        if discover: outcome = {'ok': False, 'error': 'MCP tool discovery failed. Check the server and supported transport.'}
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
    """Run initialization only, without reading tools or persisting changes."""
    return _run(server)


def run_discovery(server, context=None):
    """Initialize and enumerate tools without calling tools or granting access."""
    return _run(server, discover=True, request_context=context)


def _run(server, discover=False, request_context=None):
    """Bound the isolated operation to 20 seconds plus process cleanup."""
    if request_context is not None and request_context.is_cancelled():
        return {'ok': False, 'cancelled': True, 'error': 'Discovery cancelled.'}
    context = multiprocessing.get_context('spawn')
    reader, writer = context.Pipe(duplex=False)
    worker = context.Process(target=_initialize, args=(server, writer, discover), daemon=True)
    pid = None
    started = False
    deadline = time.monotonic() + 20
    outcome = {'ok': False, 'error': 'Tool discovery timed out.' if discover else 'Connection test timed out.'}
    try:
        worker.start()
        started = True
        writer.close()
        while time.monotonic() < deadline:
            if request_context is not None and request_context.is_cancelled():
                outcome = {'ok': False, 'cancelled': True, 'error': 'Discovery cancelled.'}
                break
            if reader.poll(min(.1, max(0, deadline-time.monotonic()))):
                try:
                    message = reader.recv()
                except EOFError:
                    outcome = {'ok': False, 'error': 'MCP discovery stopped before returning a result.' if discover else 'Connection test stopped before returning a result.'}
                    break
                if 'pid' in message:
                    pid = message['pid']
                elif message.get('released'):
                    pid = None
                else:
                    outcome = message
                    break
            elif not worker.is_alive():
                outcome = {'ok': False, 'error': 'MCP discovery stopped before returning a result.' if discover else 'Connection test stopped before returning a result.'}
                break
    except Exception:
        outcome = {'ok': False, 'error': 'Could not run MCP discovery.' if discover else 'Could not run the connection test.'}
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
