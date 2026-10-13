#!/usr/bin/env python3
"""Read-only report of the network applet's desktop icon configuration."""
import os
from pathlib import Path
import subprocess


def main():
    result = subprocess.run(['xfconf-query', '-c', 'xsettings', '-p', '/Net/IconThemeName'],
                            capture_output=True, text=True)
    print('XFCE icon theme:', (result.stdout or result.stderr).strip())
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    settings = Gtk.Settings.get_default()
    if settings is None:
        raise SystemExit('Run this inside your XFCE desktop terminal.')
    print('GTK active icon theme:', settings.get_property('gtk-icon-theme-name'))
    theme = Gtk.IconTheme.get_default()
    for name in ('nm-device-wired', 'network-wired', 'nm-signal-100'):
        info = theme.lookup_icon(name, 22, Gtk.IconLookupFlags.FORCE_SIZE)
        print(name + ':', info.get_filename() if info else 'NOT FOUND')
    index = Path.home() / '.icons/Fallout-PipBoy/index.theme'
    print('Installed Fallout icon theme:', 'present' if index.exists() else 'MISSING')
    print('Network applet processes:')
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if proc.stat().st_uid != os.getuid() or (proc/'comm').read_text().strip() != 'nm-applet':
                continue
            print(' PID', proc.name, (proc/'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace'))
            # Only print relevant desktop settings, never the full environment.
            env = dict(part.split(b'=', 1) for part in (proc/'environ').read_bytes().split(b'\0') if b'=' in part)
            for key in ('DISPLAY', 'XDG_CONFIG_HOME', 'XDG_DATA_DIRS', 'GTK_THEME', 'GTK2_RC_FILES'):
                if key.encode() in env:
                    print(' ', key + '=' + env[key.encode()].decode(errors='replace'))
        except (OSError, ValueError):
            continue


if __name__ == '__main__':
    main()
