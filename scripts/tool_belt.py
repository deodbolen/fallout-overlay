"""Persist favorite desktop application IDs, using the installed app catalog."""
import json
from pathlib import Path
from ssh_manager import config_dir, atomic_json


def favorites():
    try:
        data=json.loads((config_dir()/'tool-belt.json').read_text())
        if not isinstance(data,list): return []
        return list(dict.fromkeys(value for value in data if isinstance(value,str)))
    except (OSError,ValueError):
        return []


def identifier(app):
    return Path(app['path']).name


def contains(app):
    return identifier(app) in favorites()


def set_favorite(app,enabled):
    saved=favorites()
    identity=identifier(app)
    if enabled and identity not in saved: saved.append(identity)
    if not enabled: saved=[value for value in saved if value!=identity]
    atomic_json(config_dir()/'tool-belt.json',saved)


def applications(installed):
    by_id={identifier(app):app for app in installed}
    return [by_id[identity] for identity in favorites() if identity in by_id]
