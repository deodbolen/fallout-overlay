"""Green network status icons for the XFCE NetworkManager tray applet."""
from pathlib import Path
import configparser

NAME = 'Fallout-PipBoy'
GREEN = '#9dff72'


def svg(shape):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
            f'viewBox="0 0 24 24"><g fill="none" stroke="{GREEN}" '
            'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            + shape + '</g></svg>')


def install(directory, inherited):
    directory = Path(directory)
    index = directory / 'index.theme'
    if inherited == NAME:
        previous = configparser.ConfigParser()
        previous.read(index)
        inherited = previous.get('Icon Theme', 'Inherits', fallback='Adwaita,hicolor')
    inherited = inherited or 'Adwaita,hicolor'
    if 'hicolor' not in inherited.split(','):
        inherited += ',hicolor'
    icons = directory / 'scalable/status'
    icons.mkdir(parents=True, exist_ok=True)
    index.write_text('[Icon Theme]\nName=Fallout Pip-Boy\n'
                     f'Inherits={inherited}\nDirectories=scalable/status\n\n'
                     '[scalable/status]\nSize=24\nType=Scalable\nMinSize=16\nMaxSize=256\nContext=Status\n')

    def write(names, shape):
        for name in names:
            # Both applet-specific names and standard symbolic GTK names.
            for suffix in ('', '-symbolic'):
                (icons / (name + suffix + '.svg')).write_text(svg(shape))

    wired = '<path d="M5 3h14v11H5zM9 3v4m3-4v4m3-4v4M12 14v7m-5 0h10"/>'
    write(['nm-device-wired', 'network-wired', 'network-wired-acquiring'], wired)
    write(['nm-no-connection', 'network-offline', 'network-wired-disconnected'],
          wired + '<path d="m3 16 4 4m0-4-4 4"/>')
    arcs = ['<circle cx="12" cy="20" r="1" fill="'+GREEN+'" stroke="none"/>',
            '<path d="M8 15a6 6 0 0 1 8 0"/>',
            '<path d="M5 11a10 10 0 0 1 14 0"/>',
            '<path d="M2 7a14 14 0 0 1 20 0"/>']
    for level, label in enumerate(('none', 'weak', 'ok', 'good', 'excellent')):
        shape = ''.join(arcs[:max(1, level)])
        write([f'nm-signal-{level * 25:02d}', f'network-wireless-signal-{label}'], shape)
    write(['nm-device-wireless', 'network-wireless', 'network-wireless-connected'], ''.join(arcs))
    write(['network-wireless-disconnected', 'network-wireless-offline', 'nm-device-wired-disconnected'],
          '<path d="m7 7 10 10m0-10L7 17"/>')
    write(['nm-vpn-active-lock', 'network-vpn'], '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>')
    for stage in range(1, 4):
        for frame in range(1, 12):
            write([f'nm-stage{stage:02d}-connecting{frame:02d}'], ''.join(arcs[:1 + frame % 4]))
