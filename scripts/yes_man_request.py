"""Thread-safe cooperative cancellation for a Yes Man request."""
import threading


class RequestCancelled(Exception):
    """The request has been explicitly cancelled."""


class RequestContext:
    def __init__(self):
        self._cancelled = threading.Event()

    def cancel(self):
        """Request cancellation; repeated calls are safe."""
        self._cancelled.set()

    def is_cancelled(self):
        return self._cancelled.is_set()

    def raise_if_cancelled(self):
        if self.is_cancelled():
            raise RequestCancelled('Request cancelled.')
