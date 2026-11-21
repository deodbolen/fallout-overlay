"""Standalone, asynchronous GTK approval UI; no MCP execution or persistence."""
import json
import re
import threading
from copy import deepcopy

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib


class ToolApprovalDialog:
    """Own at most one invocation. Callbacks receive (invocation_id, approved).

    request() may be called from a worker. All widgets and callbacks run on the
    GTK main loop. The caller must supply display data, never connection config.
    A True decision applies only to the supplied invocation ID and arguments;
    callers must retain that exact invocation separately from this display.
    """

    def __init__(self, parent):
        self.parent = parent
        self._lock = threading.Lock()
        self._pending = None
        self._closed = False
        parent.connect('destroy', self._parent_closed)

    def _parent_closed(self, *_):
        with self._lock:
            self._closed = True
            state = self._pending
        if state is not None:
            self._finish(state, False)

    def request(self, invocation_id, display_name, server_id, server_name,
                tool_name, arguments, on_complete, context=None):
        """Schedule one proposal; rejected/concurrent requests complete as Deny.

        Returns whether the request was accepted for display, not approval.
        Arguments are bounded/redacted only for display and are never mutated.
        """
        if not callable(on_complete):
            raise ValueError('Approval completion callback must be callable.')
        state = {'id': invocation_id, 'callback': on_complete, 'context': context,
                 'done': False, 'window': None, 'timer': None}
        with self._lock:
            accepted = not self._closed and self._pending is None
            if accepted:
                self._pending = state
        if not accepted:
            GLib.idle_add(self._finish, state, False)
            return False
        try:
            arguments = deepcopy(arguments)
        except Exception:
            GLib.idle_add(self._finish, state, False)
            return False
        GLib.idle_add(self._show, state, display_name, server_id, server_name,
                      tool_name, arguments)
        return True

    def _finish(self, state, approved):
        with self._lock:
            if state['done']:
                return False
            state['done'] = True
            if self._pending is state:
                self._pending = None
        if state['timer'] is not None:
            GLib.source_remove(state['timer'])
            state['timer'] = None
        window = state['window']
        if window is not None:
            window.destroy()
        context = state['context']
        try:
            if context is not None and context.is_cancelled():
                approved = False
        except Exception:
            approved = False
        state['callback'](state['id'], bool(approved))
        return False

    def _show(self, state, display_name, server_id, server_name, tool_name, arguments):
        if state['done']:
            return False
        try:
            def text(value, limit=256):
                if not isinstance(value, str):
                    raise ValueError
                value = ''.join(c if c.isprintable() else ' ' for c in value)
                value = re.sub(r'(?i)bearer\s+\S+', '[redacted]', value)
                return value[:limit] + ('… [truncated]' if len(value) > limit else '')

            budget = [256]
            def safe(value, depth=0):
                budget[0] -= 1
                if budget[0] < 0 or depth > 8:
                    return '[display truncated]'
                if isinstance(value, dict):
                    result = {}
                    for key, item in value.items():
                        if budget[0] <= 0:
                            result['…'] = '[display truncated]'
                            break
                        label = text(key)
                        sensitive = re.search(r'(?i)token|password|secret|credential|authorization|cookie|api.?key|private.?key', key)
                        result[label] = '[redacted]' if sensitive else safe(item, depth + 1)
                    return result
                if isinstance(value, list):
                    result = []
                    for item in value:
                        if budget[0] <= 0:
                            result.append('[display truncated]')
                            break
                        result.append(safe(item, depth + 1))
                    return result
                if isinstance(value, str):
                    return text(value, 512)
                if value is None or type(value) in (bool, int, float):
                    return value
                raise ValueError

            details = ('MCP server: ' + text(server_name) + '\nServer ID: ' + text(server_id) +
                       '\nTool: ' + text(tool_name) + '\n\nProposed arguments (bounded, credentials redacted):\n' +
                       json.dumps(safe(arguments), ensure_ascii=True, indent=2, allow_nan=False))
            if len(details) > 8192:
                details = details[:8192] + '\n[display truncated; original arguments unchanged]'
            window = Gtk.Window(title='MCP Tool Approval', transient_for=self.parent, modal=True)
            state['window'] = window
            window.set_default_size(640, 440)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            box.set_border_width(16)
            window.add(box)
            heading = Gtk.Label(label=text(display_name) + '\nApprove this invocation only. No permanent permission is granted.')
            heading.set_line_wrap(True)
            box.pack_start(heading, False, False, 0)
            scroll = Gtk.ScrolledWindow()
            view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
            view.get_buffer().set_text(details)
            scroll.add(view)
            box.pack_start(scroll, True, True, 0)
            actions = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
            for label in ('Approve Once', 'Deny'):
                actions.add(Gtk.Label(label=label, margin=8))
            box.pack_start(actions, False, False, 0)
            actions.select_row(actions.get_row_at_index(1))
            actions.connect('row-activated', lambda _, row: self._finish(state, row.get_index() == 0))
            def keypress(_, event):
                if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_BackSpace, Gdk.KEY_Back):
                    self._finish(state, False)
                    return True
                if event.keyval in (Gdk.KEY_Up, Gdk.KEY_Down):
                    actions.select_row(actions.get_row_at_index(0 if event.keyval == Gdk.KEY_Up else 1))
                    return True
                if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                    row = actions.get_selected_row()
                    self._finish(state, row is not None and row.get_index() == 0)
                    return True
                return False
            window.connect('key-press-event', keypress)
            window.connect('delete-event', lambda *_: self._finish(state, False) or True)
            window.connect('destroy', lambda *_: self._finish(state, False))
            def poll():
                try:
                    cancelled = state['context'] is not None and state['context'].is_cancelled()
                except Exception:
                    cancelled = True
                if cancelled:
                    state['timer'] = None
                    self._finish(state, False)
                    return False
                return not state['done']
            if not poll():
                return False
            state['timer'] = GLib.timeout_add(100, poll)
            style = Gtk.CssProvider()
            style.load_from_data(b'* { background-color: #09170d; color: #9dff69; } row:selected, row:selected label { background-color: #9dff69; color: #09170d; }')
            def apply_style(widget):
                widget.get_style_context().add_provider(style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
                if isinstance(widget, Gtk.Container):
                    for child in widget.get_children():
                        apply_style(child)
            apply_style(window)
            window.show_all()
            actions.grab_focus()
            actions.select_row(actions.get_row_at_index(1))
        except Exception:
            self._finish(state, False)
        return False
