"""Read-only loading of model-independent MCP server configuration."""
import json

from ssh_manager import config_dir


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
