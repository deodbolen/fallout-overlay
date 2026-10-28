"""Persistent font size for the navigator."""
import json
from ssh_manager import config_dir, atomic_json

DEFAULT_SIZE = 16
MIN_SIZE = 8
MAX_SIZE = 32
MIN_SCROLLBACK = 10000
MAX_SCROLLBACK = 100000


def scrollback_lines():
    try:
        data=json.loads((config_dir()/'settings.json').read_text())
        return max(MIN_SCROLLBACK,min(MAX_SCROLLBACK,int(data.get('terminal_scrollback',MIN_SCROLLBACK))))
    except (OSError,ValueError,TypeError,AttributeError): return MIN_SCROLLBACK


def save_scrollback_lines(value):
    value=int(value)
    if not MIN_SCROLLBACK<=value<=MAX_SCROLLBACK:
        raise ValueError('Scrollback must be between 10,000 and 100,000 lines.')
    path=config_dir()/'settings.json'
    data=json.loads(path.read_text()) if path.exists() else {}
    data['terminal_scrollback']=value
    atomic_json(path,data)


def font_size():
    try:
        data = json.loads((config_dir() / 'settings.json').read_text())
        return max(MIN_SIZE, min(MAX_SIZE, int(data.get('navigator_font_size', DEFAULT_SIZE))))
    except (OSError, ValueError, TypeError, AttributeError):
        return DEFAULT_SIZE


def save_font_size(value):
    value = int(value)
    if not MIN_SIZE <= value <= MAX_SIZE:
        raise ValueError('Font size must be between 8 and 32 points.')
    path = config_dir() / 'settings.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    data['navigator_font_size'] = value
    atomic_json(path, data)


BACKGROUND_MODES=('normal','transparent','black')


def background_mode():
    try:
        data = json.loads((config_dir() / 'settings.json').read_text())
        mode=data.get('navigator_background_mode')
        if mode in BACKGROUND_MODES: return mode
        return 'normal' if data.get('navigator_transparent',True) is False else 'transparent'
    except (OSError, ValueError, AttributeError):
        return 'transparent'


def transparent(): return background_mode()=='transparent'


def save_background_mode(mode):
    if mode not in BACKGROUND_MODES: raise ValueError('Choose normal, transparent, or black.')
    path=config_dir()/'settings.json'
    data=json.loads(path.read_text()) if path.exists() else {}
    data['navigator_background_mode']=mode
    data['navigator_transparent']=mode=='transparent'
    atomic_json(path,data)


def cycle_background():
    mode=BACKGROUND_MODES[(BACKGROUND_MODES.index(background_mode())+1)%len(BACKGROUND_MODES)]
    save_background_mode(mode)
    return mode


def save_transparent(enabled):
    save_background_mode('transparent' if enabled else 'normal')


def section_modifier():
    try:
        data = json.loads((config_dir() / 'settings.json').read_text())
        return 'super' if data.get('section_modifier') == 'super' else 'ctrl'
    except (OSError, ValueError, AttributeError):
        return 'ctrl'


def save_section_modifier(value):
    if value not in ('ctrl', 'super'):
        raise ValueError('Choose Ctrl or Super.')
    path = config_dir() / 'settings.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    data['section_modifier'] = value
    atomic_json(path, data)
