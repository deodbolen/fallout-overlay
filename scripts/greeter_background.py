#!/usr/bin/env python3
"""Install or restore the system LightDM GTK greeter background."""
import configparser
import os
from pathlib import Path
import shutil
import socket
import sys
from xml.sax.saxutils import escape

CONFIG = Path('/etc/lightdm/lightdm-gtk-greeter.conf')
BACKUP = Path('/var/lib/fallout-ui/greeter-background')
BACKGROUND = Path('/usr/share/backgrounds/fallout-ui-login.svg')


def login_background(hostname):
    return '''<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
<rect width="1920" height="1080" fill="#000000"/>
<g fill="#9dff72" font-family="DejaVu Sans Mono, monospace" font-size="26" text-anchor="middle">
<text x="960" y="110">ROBCO INDUSTRIES UNIFIED OPERATING SYSTEM</text>
<text x="960" y="148">COPYRIGHT 2075-2077 ROBCO INDUSTRIES</text>
<text x="960" y="186">'''+escape(hostname)+'''</text>
</g></svg>
'''


def main():
    if os.geteuid() != 0:
        raise SystemExit('The login-screen configuration requires sudo.')
    if sys.argv[1] == 'restore':
        if not (BACKUP / 'saved').exists():
            return
        if (BACKUP / 'original.conf').exists():
            shutil.copy2(BACKUP / 'original.conf', CONFIG)
        else:
            CONFIG.unlink(missing_ok=True)
        return
    if not shutil.which('lightdm-gtk-greeter'):
        print('LightDM GTK greeter not installed; login background unchanged.')
        return
    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    if CONFIG.exists():
        cfg.read(CONFIG)
    if not (BACKUP / 'saved').exists():
        BACKUP.mkdir(parents=True, exist_ok=True)
        if CONFIG.exists():
            shutil.copy2(CONFIG, BACKUP / 'original.conf')
        (BACKUP / 'saved').touch()
    if not cfg.has_section('greeter'):
        cfg.add_section('greeter')
    BACKGROUND.parent.mkdir(parents=True, exist_ok=True)
    BACKGROUND.write_text(login_background(socket.gethostname()))
    BACKGROUND.chmod(0o644)
    for section in cfg.sections():
        if section == 'greeter' or section.startswith('monitor:'):
            cfg.set(section, 'background', str(BACKGROUND))
            cfg.set(section, 'user-background', 'false')
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG.with_suffix('.conf.fallout-tmp')
    with temporary.open('w') as stream:
        cfg.write(stream)
    temporary.chmod(0o644)
    temporary.replace(CONFIG)
    print('Black login background with green RobCo header installed; applies at the next login screen.')


if __name__ == '__main__':
    main()
