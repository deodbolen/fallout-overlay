"""In-memory single-use approvals owned exclusively by trusted application code."""
import json
import threading


def _arguments_snapshot(arguments):
    """Canonical JSON bytes retain no mutable references to supplied values."""
    def validate(value):
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise ValueError
            for item in value.values():
                validate(item)
        elif type(value) is list:
            for item in value:
                validate(item)
        elif value is not None and type(value) not in (str, bool, int, float):
            raise ValueError

    try:
        if type(arguments) is not dict:
            raise ValueError
        validate(arguments)
        return json.dumps(arguments, sort_keys=True, ensure_ascii=True,
                          separators=(',', ':'), allow_nan=False).encode('ascii')
    except Exception:
        raise ValueError('Invocation arguments must be a JSON-compatible object.') from None


def _identity(invocation_id, model_tool_name, server_id, tool_name):
    values = (invocation_id, model_tool_name, server_id, tool_name)
    if any(type(value) is not str or not value.strip() for value in values):
        raise ValueError('Invocation identity fields must be nonempty strings.')
    return values


class InvocationApproval:
    """Bind one trusted user decision to one exact invocation.

    The caller supplies a unique invocation ID and retains this object locally.
    Never expose record_decision() or this object to model tool arguments or
    deserialize model-provided approval claims. Python objects are not a trust
    boundary against other code running in the same process.

    Consumption is only a single-use approval check, never authorization to
    bypass current saved permissions or connection-identity revalidation.
    """

    def __init__(self, invocation_id, model_tool_name, server_id, tool_name, arguments):
        self._identity = _identity(invocation_id, model_tool_name, server_id, tool_name)
        self._arguments = _arguments_snapshot(arguments)
        self._lock = threading.Lock()
        self._state = 'pending'

    @property
    def state(self):
        """Return pending, approved, denied, cancelled, or consumed."""
        with self._lock:
            return self._state

    def record_decision(self, approved):
        """Trusted UI/application code records one explicit boolean decision."""
        if type(approved) is not bool:
            raise ValueError('Approval decision must be a boolean.')
        with self._lock:
            if self._state != 'pending':
                raise ValueError('Approval decision is no longer pending.')
            self._state = 'approved' if approved else 'denied'

    def cancel(self):
        """Revoke a pending or approved decision; repeated cancellation is safe."""
        with self._lock:
            if self._state in ('pending', 'approved'):
                self._state = 'cancelled'

    def consume(self, invocation_id, model_tool_name, server_id, tool_name, arguments):
        """Return True exactly once for an approved matching invocation.

        Object key ordering is insignificant; array ordering, string contents,
        JSON scalar types, and all identity strings must match exactly. Invalid
        attempts raise ValueError and never revive or consume another approval.
        """
        identity = _identity(invocation_id, model_tool_name, server_id, tool_name)
        snapshot = _arguments_snapshot(arguments)
        with self._lock:
            if self._state != 'approved':
                raise ValueError('Invocation approval is unavailable for consumption.')
            if identity != self._identity or snapshot != self._arguments:
                raise ValueError('Invocation does not match the approved proposal.')
            self._state = 'consumed'
            return True
