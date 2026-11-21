"""Read-only, server-scoped MCP tool eligibility; no execution authorization."""
from copy import deepcopy
import base64
import hashlib
import json

from mcp_servers import validate_tool_permission


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
