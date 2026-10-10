"""Persistent font size for the navigator."""
import json
from ssh_manager import config_dir, atomic_json

DEFAULT_SIZE = 16
MIN_SIZE = 8
MAX_SIZE = 32


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


def transparent():
    try:
        data = json.loads((config_dir() / 'settings.json').read_text())
        return data.get('navigator_transparent', True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def save_transparent(enabled):
    path = config_dir() / 'settings.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    data['navigator_transparent'] = bool(enabled)
    atomic_json(path, data)
