"""Read-only, server-scoped MCP tool eligibility; no execution authorization."""
from copy import deepcopy
import base64
import hashlib
import json

from mcp_servers import validate_tool_permission


def prepare_conversation_mcp_tools(registry, discovered_by_server):
    """Prepare a fresh non-executable MCP snapshot for one conversation request.

    discovered_by_server is a trusted application-owned dict mapping exact saved
    server IDs to tools/list metadata lists: [{name, description, inputSchema}].
    No live discovery occurs. Unknown IDs, duplicate saved IDs, malformed tools,
    and stale permissions fail closed. Servers and tools are sorted by exact ID
    and name so equivalent inputs produce the same ordering. The result has
    exactly definitions and tool_mapping; it is not execution authority.
    """
    from mcp_servers import load, validate_server
    from yes_man_tools import ToolRegistry

    try:
        if not isinstance(registry, ToolRegistry) or not isinstance(discovered_by_server, dict):
            raise ValueError
        discovered = deepcopy(discovered_by_server)
        if any(not isinstance(key, str) or not key.strip() for key in discovered):
            raise ValueError
        servers = {}
        for record in load()['servers']:
            server = validate_server(record)
            if server['id'] in servers:
                raise ValueError
            servers[server['id']] = server
        if set(discovered) - set(servers):
            raise ValueError
        eligible = []
        for server_id in sorted(discovered):
            server = servers[server_id]
            tools = discovered[server_id]
            # Validate discovery independently of authorization, even for a
            # disabled server. This temporary copy grants no tool permissions.
            validation_server = dict(server, enabled=True, tool_permissions={})
            eligible_tools(validation_server, tools)
            for tool in tools:
                json.dumps(tool['inputSchema'], allow_nan=False)
            if server['enabled']:
                eligible.extend(eligible_tools(server, sorted(tools, key=lambda tool: tool['name'])))
        records = model_tool_definitions(eligible)
        return stage_mcp_tool_definitions(records, registry)
    except Exception:
        raise ValueError('Conversation MCP tools could not be prepared consistently.') from None


def stage_mcp_tool_definitions(model_records, registry):
    """Stage trusted model_tool_definitions() records without executable handlers.

    Return {'definitions': [function-tool envelopes], 'tool_mapping': bindings}.
    The supplied conversation-local ToolRegistry is inspected, never modified.
    Current permissions must match the staged policies; callers must rebuild
    stale records. This snapshot is not execution authorization and is not
    automatically advertised to a model or installed in any registry.
    """
    from yes_man_tools import ToolRegistry

    try:
        if not isinstance(registry, ToolRegistry):
            raise ValueError
        records = deepcopy(model_records)
        mapping = build_tool_mapping(records)
        existing = registry.definitions()
        names = [definition['function']['name'] for definition in existing]
        if len(names) != len(set(names)):
            raise ValueError
        if set(mapping).intersection(set(names) | {'web_search'}):
            raise ValueError
        # Reconstruct only the canonical envelope, discarding arbitrary outer
        # metadata so no connection configuration is forwarded to a model.
        canonical = model_tool_definitions([{
            'server_id': record['server_id'], 'name': record['tool_name'],
            'description': record['definition']['function']['description'],
            'inputSchema': record['definition']['function']['parameters'],
            'permission': record['permission']} for record in records])
        if build_tool_mapping(canonical) != mapping:
            raise ValueError
        for name, binding in mapping.items():
            if revalidate_tool_permission(name, mapping) != binding:
                raise ValueError
        return {'definitions': [record['definition'] for record in canonical],
                'tool_mapping': mapping}
    except Exception:
        raise ValueError('MCP tool definitions could not be staged consistently.') from None


def coordinate_tool_invocation(model_tool_name, arguments, tool_mapping, dialog,
                                context, on_complete):
    """Coordinate one trusted invocation asynchronously; return its fresh ID.

    on_complete(outcome) runs once on the GTK main loop. Outcomes contain
    invocation_id and status (success, denied, cancelled, error), plus result
    on success or a fixed error message on error. The caller owns context;
    cancellation cannot interrupt an already-blocking transport operation.
    """
    import threading
    import uuid
    from gi.repository import GLib
    from yes_man_request import RequestContext, RequestCancelled
    from yes_man_mcp_authorization import InvocationApproval, _arguments_snapshot
    from yes_man_mcp_approval import request_invocation_approval

    if not callable(on_complete):
        raise ValueError('Invocation completion callback must be callable.')
    invocation_id = uuid.uuid4().hex
    request_context = context if context is not None else RequestContext()
    lock = threading.Lock()
    state = {'completed': False, 'attempted': False, 'approval_handled': False}

    def complete(status, result=None):
        with lock:
            if state['completed']:
                return
            state['completed'] = True
        def deliver():
            outcome = {'invocation_id': invocation_id, 'status': status}
            try:
                if request_context.is_cancelled():
                    outcome['status'] = 'cancelled'
            except Exception:
                outcome['status'] = 'error'
            if outcome['status'] == 'success':
                outcome['result'] = result
            elif outcome['status'] == 'error':
                outcome['error'] = 'MCP invocation could not be completed or authorized.'
            on_complete(outcome)
            return False
        GLib.idle_add(deliver)

    try:
        # Copy before handing control to workers or an asynchronous dialog.
        proposed = json.loads(_arguments_snapshot(arguments))
        mapping = deepcopy(tool_mapping)
    except Exception:
        complete('error')
        return invocation_id

    def execute(authorization, approval=None):
        with lock:
            if state['completed'] or state['attempted']:
                return
            state['attempted'] = True
        try:
            request_context.raise_if_cancelled()
            # Reject policy switches while the user was considering approval;
            # the dispatcher performs another check and checks after initialize.
            if revalidate_tool_permission(model_tool_name, mapping) != authorization:
                raise ValueError
            result = invoke_authorized_tool(model_tool_name, proposed, mapping,
                                            context=request_context,
                                            invocation_id=invocation_id, approval=approval)
            complete('success', result)
        except RequestCancelled:
            complete('cancelled')
        except Exception:
            complete('error')

    def start_worker(work):
        try:
            threading.Thread(target=work, daemon=True).start()
        except Exception:
            complete('error')

    def prepare():
        try:
            request_context.raise_if_cancelled()
            authorization = revalidate_tool_permission(model_tool_name, mapping)
            if authorization['approval'] == 'always_allow':
                execute(authorization)
                return
            if authorization['approval'] != 'always_ask':
                raise ValueError
            approval = InvocationApproval(invocation_id, model_tool_name,
                                          authorization['server_id'],
                                          authorization['tool_name'], proposed)
            # Names are display-only; resolve the server label from local
            # storage, never from model arguments or tool-provided metadata.
            from mcp_servers import load, validate_server
            server = next(validate_server(row) for row in load()['servers']
                          if row.get('id') == authorization['server_id'])

            def resolved(returned, approved):
                with lock:
                    if state['approval_handled'] or state['completed']:
                        return
                    state['approval_handled'] = True
                try:
                    request_context.raise_if_cancelled()
                    if returned is not approval or approved is not True or approval.state != 'approved':
                        approval.cancel()
                        complete('denied')
                        return
                    start_worker(lambda: execute(authorization, approval))
                except RequestCancelled:
                    approval.cancel()
                    complete('cancelled')
                except Exception:
                    approval.cancel()
                    complete('error')

            request_invocation_approval(dialog, approval,
                                        display_name=authorization['tool_name'],
                                        server_name=server['name'], on_complete=resolved,
                                        context=request_context)
        except RequestCancelled:
            complete('cancelled')
        except Exception:
            complete('error')

    start_worker(prepare)
    return invocation_id


def invoke_authorized_tool(model_tool_name, arguments, tool_mapping, context=None,
                           *, invocation_id=None, approval=None):
    """Execute one currently permitted invocation, without retries.

    Always Ask requires a trusted, exact single-use InvocationApproval. It is
    consumed before transport construction and never restored after failure.

    Cancellation is cooperative between blocking transport operations. Each
    protocol operation uses the existing ten-second transport timeout; HTTP's
    timeout is a socket timeout, not a whole-operation deadline. HTTP owns no
    persistent connection; stdio is always closed by this lifecycle owner.
    """
    from mcp_servers import load, validate_server
    from yes_man_request import RequestCancelled
    from yes_man_mcp_authorization import InvocationApproval
    import sys

    transport = None
    try:
        def checkpoint():
            if context is not None:
                context.raise_if_cancelled()

        def check_json(value):
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise ValueError
                for item in value.values():
                    check_json(item)
            elif isinstance(value, list):
                for item in value:
                    check_json(item)
            elif value is not None and type(value) not in (str, bool, int, float):
                raise ValueError

        def saved_server(authorization):
            records = [validate_server(row) for row in load()['servers']]
            ids = [row['id'] for row in records]
            if len(set(ids)) != len(ids):
                raise ValueError
            server = next((row for row in records if row['id'] == authorization['server_id']), None)
            if server is None or not server['enabled']:
                raise ValueError
            permission = validate_tool_permission(dict(
                server['tool_permissions'].get(authorization['tool_name'], {}),
                tool_name=authorization['tool_name']))
            if not permission['enabled'] or permission['approval'] != authorization['approval']:
                raise ValueError
            return server

        checkpoint()
        if not isinstance(arguments, dict):
            raise ValueError
        check_json(arguments)
        # Snapshot arguments and trusted bindings before any blocking work.
        proposed = json.loads(json.dumps(arguments, allow_nan=False))
        mapping = deepcopy(tool_mapping)
        authorization = revalidate_tool_permission(model_tool_name, mapping)
        if authorization['approval'] not in ('always_allow', 'always_ask'):
            raise ValueError
        server = saved_server(authorization)
        checkpoint()
        if authorization['approval'] == 'always_ask':
            if not isinstance(approval, InvocationApproval):
                raise ValueError
            InvocationApproval.consume(approval, invocation_id, model_tool_name,
                                       authorization['server_id'], authorization['tool_name'], proposed)
        checkpoint()
        transport = create_runtime_transport(server)
        checkpoint()
        if server['transport'] == 'stdio':
            transport.start()
        checkpoint()
        transport.initialize(timeout=10)
        checkpoint()
        current = revalidate_tool_permission(model_tool_name, mapping)
        if current != authorization:
            raise ValueError
        latest = saved_server(current)
        identity_fields = ('id', 'transport', 'url', 'bearer_token', 'command', 'args', 'env', 'cwd')
        if any(latest.get(field) != server.get(field) for field in identity_fields):
            raise ValueError
        checkpoint()
        result = transport.request('tools/call', {
            'name': authorization['tool_name'], 'arguments': proposed}, timeout=10)
        checkpoint()
        return result
    except RequestCancelled:
        raise
    except Exception:
        raise RuntimeError('MCP tool invocation failed or was not authorized.') from None
    finally:
        if transport is not None:
            unwinding = sys.exc_info()[0] is not None
            close = getattr(transport, 'close', None)
            if close is not None:
                try:
                    close()
                except Exception:
                    if not unwinding:
                        raise RuntimeError('MCP transport cleanup failed; invocation outcome may be unknown.') from None


def create_runtime_transport(server):
    """Construct an inert transport from trusted local server configuration.

    Never pass model-generated arguments here. Construction neither starts nor
    connects the transport, and does not replace runtime permission validation.
    The caller owns the returned transport's eventual lifecycle.
    """
    try:
        from mcp_servers import validate_server

        validated = validate_server(server)
        if not validated['enabled']:
            raise ValueError
        if validated['transport'] == 'stdio':
            from yes_man_mcp_stdio import StdioTransport

            return StdioTransport(validated)
        if validated['transport'] == 'streamable-http':
            from yes_man_mcp_http import StreamableHttpTransport

            return StreamableHttpTransport(validated['url'], validated.get('bearer_token'))
        raise ValueError
    except Exception:
        raise ValueError('Could not construct an enabled MCP runtime transport.') from None


def revalidate_tool_permission(model_tool_name, tool_mapping):
    """Return the current saved policy for a trusted, server-scoped binding.

    Always Ask still requires future runtime approval. This read-only snapshot
    neither grants execution nor prevents later configuration changes; callers
    must enforce it at the execution boundary. All failures deny authorization.
    """
    from mcp_servers import load, validate_server

    try:
        if (not isinstance(model_tool_name, str) or not model_tool_name.strip() or
                not isinstance(tool_mapping, dict) or model_tool_name not in tool_mapping):
            raise ValueError
        binding = tool_mapping[model_tool_name]
        if not isinstance(binding, dict):
            raise ValueError
        server_id = binding.get('server_id')
        tool_name = binding.get('tool_name')
        if (not isinstance(server_id, str) or not server_id.strip() or
                not isinstance(tool_name, str) or not tool_name.strip()):
            raise ValueError
        # Validate the entire current document and reject ambiguous server IDs.
        # Never use the mapping's cached approval policy to authorize anything.
        document = load()
        servers = [validate_server(record) for record in document['servers']]
        identifiers = [server['id'] for server in servers]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError
        server = next((record for record in servers if record['id'] == server_id), None)
        if server is None or not server['enabled']:
            raise ValueError
        saved = server['tool_permissions'].get(tool_name)
        if not isinstance(saved, dict):
            raise ValueError
        permission = validate_tool_permission(dict(saved, tool_name=tool_name))
        if not permission['enabled']:
            raise ValueError
        return {'server_id': server_id, 'tool_name': tool_name,
                'approval': permission['approval']}
    except Exception:
        # Validators and storage errors must not leak connection configuration.
        raise ValueError('MCP tool authorization could not be confirmed.') from None


def eligible_tools(server, discovered_tools):
    """Return independent tool records eligible for future registration.

    Records contain server_id, name, description, inputSchema, and permission
    (tool_name, enabled, approval). Eligibility never authorizes execution or
    satisfies the interactive approval required by always_ask.
    Malformed definitions or permissions raise ValueError without side effects.
    """
    if not isinstance(server, dict) or not isinstance(server.get('enabled'), bool):
        raise ValueError('Expected a validated MCP server configuration.')
    if not server['enabled']:
        return []
    server_id = server.get('id')
    permissions = server.get('tool_permissions', {})
    if (not isinstance(server_id, str) or not server_id.strip() or
            not isinstance(permissions, dict)):
        raise ValueError('Expected a validated MCP server configuration.')
    if not isinstance(discovered_tools, list):
        raise ValueError('Discovered MCP tools must be a list.')
    result = []
    names = set()
    for tool in discovered_tools:
        if not isinstance(tool, dict):
            raise ValueError('Invalid discovered MCP tool definition.')
        name = tool.get('name')
        description = tool.get('description', '')
        schema = tool.get('inputSchema')
        if (not isinstance(name, str) or not name.strip() or
                not isinstance(description, str) or not isinstance(schema, dict) or
                schema.get('type') != 'object'):
            raise ValueError('Invalid discovered MCP tool definition.')
        if name in names:
            raise ValueError('Duplicate discovered MCP tool name within one server.')
        names.add(name)
        saved = permissions.get(name, {})
        if not isinstance(saved, dict):
            raise ValueError('Invalid MCP tool permission.')
        if 'tool_name' in saved and saved['tool_name'] != name:
            raise ValueError('MCP tool permission name conflicts with its dictionary key.')
        permission = validate_tool_permission(dict(saved, tool_name=name))
        if not permission['enabled']:
            continue
        # Whitelist output fields: never copy connection settings or arbitrary
        # server-supplied metadata into a future registration record.
        result.append({'server_id': server_id, 'name': name,
                       'description': description, 'inputSchema': deepcopy(schema),
                       'permission': permission})
    return result


def build_tool_mapping(model_records):
    """Build local identity bindings from trusted adapter output, never model arguments.

    Values contain only server_id, tool_name, and approval. A binding is not
    execution authorization; future dispatch must still enforce permissions.
    """
    if not isinstance(model_records, list):
        raise ValueError('Model MCP records must be a list.')
    mapping = {}
    identities = set()
    for record in model_records:
        if not isinstance(record, dict):
            raise ValueError('Invalid model MCP tool record.')
        definition = record.get('definition')
        if not isinstance(definition, dict) or definition.get('type') != 'function':
            raise ValueError('Invalid model MCP tool definition.')
        function = definition.get('function')
        if not isinstance(function, dict):
            raise ValueError('Invalid model MCP tool function.')
        model_name = function.get('name')
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError('Model MCP tool name must be a nonempty string.')
        if model_name == 'web_search':
            raise ValueError('MCP tool name conflicts with a built-in tool.')
        if model_name in mapping:
            raise ValueError('Duplicate model MCP tool name.')
        permission = record.get('permission')
        if not isinstance(permission, dict) or 'approval' not in permission:
            raise ValueError('Model MCP tool requires an explicit saved approval policy.')
        # Reuse the adapter's validation and canonical, server-scoped naming.
        # This also reserves the mcp_ namespace and rejects substituted names.
        normalized = model_tool_definitions([{
            'server_id': record.get('server_id'), 'name': record.get('tool_name'),
            'description': function.get('description'),
            'inputSchema': function.get('parameters'), 'permission': permission}])[0]
        if model_name != normalized['definition']['function']['name']:
            raise ValueError('Model MCP tool name does not match its original identity.')
        identity = (normalized['server_id'], normalized['tool_name'])
        if identity in identities:
            raise ValueError('Duplicate original MCP tool identity.')
        identities.add(identity)
        mapping[model_name] = {'server_id': identity[0], 'tool_name': identity[1],
                               'approval': normalized['permission']['approval']}
    return mapping


def model_tool_definitions(eligible_records):
    """Adapt eligible records without registering or authorizing any tool.

    Each returned record contains a registry-compatible ``definition`` envelope
    plus separate ``server_id``, ``tool_name``, and ``permission`` metadata.
    Only the definition belongs in a model request; the other fields provide
    an exact local dispatch binding and retain the future approval requirement.
    """
    if not isinstance(eligible_records, list):
        raise ValueError('Eligible MCP records must be a list.')
    result = []
    identities = set()
    identifiers = set()
    for record in eligible_records:
        if not isinstance(record, dict):
            raise ValueError('Invalid eligible MCP tool record.')
        server_id = record.get('server_id')
        name = record.get('name')
        description = record.get('description')
        schema = record.get('inputSchema')
        if (not isinstance(server_id, str) or not server_id.strip() or
                not isinstance(name, str) or not name.strip() or
                not isinstance(description, str) or not description.strip() or
                not isinstance(schema, dict) or schema.get('type') != 'object'):
            raise ValueError('Invalid eligible MCP tool record or registry definition.')
        permission = validate_tool_permission(record.get('permission'))
        if permission['tool_name'] != name or not permission['enabled']:
            raise ValueError('Eligible MCP tool requires a matching enabled permission.')
        identity = (server_id, name)
        if identity in identities:
            raise ValueError('Duplicate eligible MCP tool identity.')
        identities.add(identity)
        try:
            # An encoded pair avoids ambiguous concatenation. A full SHA-256
            # digest in base32 yields a stable 56-character ASCII identifier,
            # within the function-name limit and outside built-in names.
            encoded = json.dumps(identity, ensure_ascii=True, separators=(',', ':')).encode('ascii')
            identifier = 'mcp_' + base64.b32encode(hashlib.sha256(encoded).digest()).decode('ascii').rstrip('=').lower()
            parameters = deepcopy(schema)
            json.dumps(parameters, allow_nan=False)
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise ValueError('MCP input schema must be JSON serializable.') from None
        if identifier in identifiers:
            raise ValueError('Conflicting model-facing MCP tool identifiers.')
        identifiers.add(identifier)
        result.append({'server_id': server_id, 'tool_name': name,
                       'permission': permission,
                       'definition': {'type': 'function', 'function': {
                           'name': identifier, 'description': description,
                           'parameters': parameters}}})
    return result
