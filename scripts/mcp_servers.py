"""Load and persist model-independent MCP server configuration."""
import json
import ipaddress
import fcntl
import os
import re
from urllib.parse import urlsplit

from ssh_manager import atomic_json, config_dir


def load():
    """Return the stored document, or an empty version-1 document if absent."""
    path = config_dir() / 'mcp-servers.json'
    try:
        content = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return {'schema_version': 1, 'servers': []}
    try:
        document = json.loads(content)
    except json.JSONDecodeError:
        raise ValueError('Invalid JSON in MCP server configuration.') from None
    if (not isinstance(document, dict) or
            type(document.get('schema_version')) is not int or
            document['schema_version'] != 1 or
            not isinstance(document.get('servers'), list)):
        raise ValueError('Invalid MCP server configuration: expected schema_version 1 and a servers array.')
    return document


def save(document):
    """Atomically save a version-1 document with owner-only file permissions."""
    if (not isinstance(document, dict) or
            type(document.get('schema_version')) is not int or
            document['schema_version'] != 1 or
            not isinstance(document.get('servers'), list)):
        raise ValueError('Invalid MCP server configuration: expected schema_version 1 and a servers array.')
    servers = [validate_server(server) for server in document['servers']]
    identifiers = [server['id'] for server in servers]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError('Duplicate MCP server IDs are not allowed.')
    normalized = dict(document)
    normalized['servers'] = servers
    atomic_json(config_dir() / 'mcp-servers.json', normalized)


def add_server(server):
    """Add and return a normalized server under a complete transaction lock.

    Concurrent additions share this advisory lock. Future read-modify-write
    operations must use the same lock; direct save() remains a document writer.
    """
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / 'mcp-servers.lock').open('a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        document = load()
        normalized = validate_server(server)
        if any(validate_server(existing)['id'] == normalized['id']
               for existing in document['servers']):
            raise ValueError('Duplicate MCP server IDs are not allowed.')
        updated = dict(document)
        updated['servers'] = document['servers'] + [normalized]
        save(updated)
        return normalized


def remove_server(server_id):
    """Remove and return one server under the shared configuration lock."""
    if not isinstance(server_id, str) or not server_id.strip():
        raise ValueError('MCP server ID must be a nonempty string.')
    server_id = server_id.strip()
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / 'mcp-servers.lock').open('a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        document = load()
        for index, server in enumerate(document['servers']):
            if validate_server(server)['id'] == server_id:
                updated = dict(document)
                updated['servers'] = document['servers'][:index] + document['servers'][index + 1:]
                save(updated)
                return server
        raise ValueError('MCP server ID was not found.')


def validate_server(server):
    """Return a normalized copy, without I/O or modifying the input.

    IDs and display names are trimmed. Commands, arguments, environment values,
    and bearer tokens are preserved literally. Local HTTP endpoints and query
    strings are allowed; URL credentials and fragments are not. Unknown fields
    are retained, but fields belonging to the other transport are rejected.
    """
    if not isinstance(server, dict):
        raise ValueError('MCP server must be a dictionary.')
    result = dict(server)
    for field in ('id', 'name'):
        value = server.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError('MCP server requires a nonempty ' + field + ' string.')
        result[field] = value.strip()
    transport = server.get('transport')
    if transport not in ('stdio', 'streamable-http'):
        raise ValueError('Unsupported MCP transport; use stdio or streamable-http.')
    if not isinstance(server.get('enabled'), bool):
        raise ValueError('MCP server enabled must be a boolean.')

    if transport == 'stdio':
        if 'url' in server or 'bearer_token' in server:
            raise ValueError('stdio servers cannot contain url or bearer_token fields.')
        command = server.get('command')
        if not isinstance(command, str) or not command.strip():
            raise ValueError('stdio server requires a nonempty command string.')
        args = server.get('args', [])
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            raise ValueError('stdio server args must be a list of strings.')
        env = server.get('env', {})
        if (not isinstance(env, dict) or
                any(not isinstance(key, str) or not isinstance(value, str)
                    for key, value in env.items())):
            raise ValueError('stdio server env must contain string keys and values.')
        result['args'] = list(args)
        result['env'] = dict(env)
    else:
        if any(field in server for field in ('command', 'args', 'env')):
            raise ValueError('streamable-http servers cannot contain command, args, or env fields.')
        url = server.get('url')
        if not isinstance(url, str) or not url.strip():
            raise ValueError('streamable-http server requires an HTTP or HTTPS URL.')
        url = url.strip()
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            if (parsed.scheme not in ('http', 'https') or not host or
                    parsed.username is not None or parsed.password is not None or
                    '#' in url or '\\' in url or
                    any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url) or
                    (parsed.port is not None and not 1 <= parsed.port <= 65535)):
                raise ValueError
            try:
                ipaddress.ip_address(host)
            except ValueError:
                hostname = host.encode('idna').decode('ascii').rstrip('.')
                if (len(hostname) > 253 or not hostname or
                        any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                            for label in hostname.split('.'))):
                    raise ValueError
        except (ValueError, UnicodeError):
            raise ValueError('Invalid MCP server HTTP or HTTPS URL.') from None
        if 'bearer_token' in server and not isinstance(server['bearer_token'], str):
            raise ValueError('MCP server bearer_token must be a string.')
        result['url'] = url
    return result
