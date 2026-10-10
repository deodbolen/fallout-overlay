#!/usr/bin/env python3
"""Install or restore the system LightDM GTK greeter background."""
import configparser
import os
from pathlib import Path
import shutil
import sys

CONFIG = Path('/etc/lightdm/lightdm-gtk-greeter.conf')
BACKUP = Path('/var/lib/fallout-ui/greeter-background')


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
    for section in cfg.sections():
        if section == 'greeter' or section.startswith('monitor:'):
            cfg.set(section, 'background', '#000000')
            cfg.set(section, 'user-background', 'false')
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG.with_suffix('.conf.fallout-tmp')
    with temporary.open('w') as stream:
        cfg.write(stream)
    temporary.chmod(0o644)
    temporary.replace(CONFIG)
    print('Login-screen background set to black; applies at the next login screen.')


if __name__ == '__main__':
    main()
