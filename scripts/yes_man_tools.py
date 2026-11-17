"""Provider-independent, in-memory tool registration and dispatch."""
from copy import deepcopy


class ToolRegistry:
    """Keep ordered function-tool definitions and their argument handlers.

    Definitions use the existing function-tool envelope:
    {"type": "function", "function": {"name", "description", "parameters"}}.
    Each handler receives the arguments supplied to execute() as one value.
    """

    def __init__(self):
        self._tools = {}

    def register(self, name, definition, handler):
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Tool name must be a nonempty string.')
        if name in self._tools:
            raise ValueError('Tool name is already registered.')
        if not isinstance(definition, dict) or definition.get('type') != 'function':
            raise ValueError('Tool definition must be a function-tool dictionary.')
        function = definition.get('function')
        if not isinstance(function, dict) or function.get('name') != name:
            raise ValueError('Tool definition function name must match the registered name.')
        description = function.get('description')
        if not isinstance(description, str) or not description.strip():
            raise ValueError('Tool definition requires a nonempty description string.')
        parameters = function.get('parameters')
        if not isinstance(parameters, dict) or parameters.get('type') != 'object':
            raise ValueError('Tool parameters must be an object JSON schema.')
        if not callable(handler):
            raise ValueError('Tool handler must be callable.')
        self._tools[name] = (deepcopy(definition), handler)

    def definitions(self):
        """Return independent definitions in registration order."""
        return [deepcopy(definition) for definition, _ in self._tools.values()]

    def execute(self, name, arguments):
        """Pass arguments to the registered handler and return its result."""
        if not isinstance(name, str) or name not in self._tools:
            raise ValueError('Unknown tool name.')
        return self._tools[name][1](arguments)
