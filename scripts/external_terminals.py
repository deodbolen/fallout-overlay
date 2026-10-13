"""Yield the navigator to newly opened desktop terminal windows on X11."""
import os

TERMINALS = frozenset({
    'xfce4-terminal', 'xfce4-terminal-dropdown', 'xterm', 'uxterm',
    'gnome-terminal', 'gnome-terminal-server', 'konsole', 'kitty',
    'alacritty', 'terminator', 'tilix', 'mate-terminal', 'lxterminal',
    'qterminal', 'org.gnome.terminal', 'org.wezfurlong.wezterm', 'wezterm',
})


def is_external_terminal(window, own_pid=None):
    if window.get_pid() == (os.getpid() if own_pid is None else own_pid):
        return False
    classes = (window.get_class_group_name(), window.get_class_instance_name())
    return any((value or '').lower() in TERMINALS for value in classes)


def watch(host):
    import gi
    gi.require_version('Wnck', '3.0')
    from gi.repository import Wnck, GLib
    screen = Wnck.Screen.get_default()
    if screen is None:
        return None
    # Establish the initial inventory before watching newly opened windows.
    screen.force_update()

    def inspect(window):
        if not host.closed and host.window.get_visible() and is_external_terminal(window):
            host.window.hide()
        return False

    def opened(screen, window):
        # Some applications publish WM_CLASS after mapping their window.
        window.connect('class-changed', lambda window: inspect(window))
        GLib.timeout_add(200, inspect, window)

    screen.connect('window-opened', opened)
    return screen
