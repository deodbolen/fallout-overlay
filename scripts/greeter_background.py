#!/usr/bin/env python3
"""Install or restore the system LightDM GTK greeter background."""
import configparser
import os
from pathlib import Path
import shutil
import socket
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

CONFIG = Path('/etc/lightdm/lightdm-gtk-greeter.conf')
BACKUP = Path('/var/lib/fallout-ui/greeter-background')
BACKGROUND = Path('/usr/share/backgrounds/fallout-ui-login.svg')
ROOT = Path(__file__).resolve().parent.parent
LOGIN_THEME = Path('/usr/share/themes/Fallout-Login')
LOGO = Path('/usr/share/pixmaps/fallout-vault-tec.png')


def install_login_theme():
    shutil.copytree(ROOT / 'theme', LOGIN_THEME, dirs_exist_ok=True)
    css = LOGIN_THEME / 'gtk-3.0/gtk.css'
    with css.open('a') as stream:
        stream.write('''
/* LightDM login box: softly green surfaces and clear keyboard focus. */
@define-color lightdm-gtk-greeter-override-defaults #000000;
#login_window, #login_window #content_frame, #login_window #buttonbox_frame {
  background-color: #0b160e;
  background-image: none;
  color: #b6ffa3;
}
#login_window entry {
  background-color: #14271a;
  background-image: none;
  color: #b6ffa3;
  border: 1px solid #416b47;
  caret-color: #9dff72;
}
#login_window entry:focus {
  border-color: #9dff72;
  box-shadow: 0 0 0 1px #9dff72;
}
/* Keep branding independent of LightDM's per-user avatar selection. */
#login_window #user_image {
  -gtk-icon-transform: scale(0);
  background-image: url("/usr/share/pixmaps/fallout-vault-tec.png");
  background-repeat: no-repeat;
  background-position: center;
  background-size: contain;
  min-width: 160px;
  min-height: 108px;
}
''')
    # Preserve SVG namespaces for the loader, then deploy a verified PNG.
    # The greeter can read PNG even if its SVG loader is unavailable.
    import gi
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import GdkPixbuf
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    logo = ET.parse(ROOT / 'assets/Vault-Tec_Logo.svg')
    for element in logo.getroot().iter():
        if element.get('fill') not in (None, 'none'):
            element.set('fill', '#9dff72')
    LOGO.parent.mkdir(parents=True, exist_ok=True)
    loader = GdkPixbuf.PixbufLoader.new_with_type('svg')
    loader.write(ET.tostring(logo.getroot(), encoding='utf-8'))
    loader.close()
    pixbuf = loader.get_pixbuf()
    if pixbuf is None:
        raise RuntimeError('Could not render the Vault-Tec logo.')
    pixbuf.savev(str(LOGO), 'png', [], [])
    LOGO.chmod(0o644)
    GdkPixbuf.Pixbuf.new_from_file(str(LOGO))


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
    install_login_theme()
    cfg.set('greeter', 'theme-name', 'Fallout-Login')
    cfg.set('greeter', 'default-user-image', str(LOGO))
    cfg.set('greeter', 'hide-user-image', 'false')
    cfg.set('greeter', 'round-user-image', 'false')
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
