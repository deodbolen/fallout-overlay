"""Model-independent settings for built-in Yes Man tools."""
import json
from ssh_manager import config_dir, atomic_json
from yes_man_search import validate_url

DEFAULT = {'search_enabled': True, 'search_url': 'http://127.0.0.1:8888'}


def settings():
    path = config_dir() / 'yes-man-tools.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        # Preserve the previously active global search choices without importing
        # search settings from whichever LLM profile is selected next.
        try:
            data = json.loads((config_dir() / 'yes-man.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
    if not isinstance(data, dict):
        raise ValueError('Invalid built-in tool settings.')
    return validate({key: data.get(key, value) for key, value in DEFAULT.items()})


def validate(config):
    enabled = config.get('search_enabled', True)
    url = config.get('search_url', DEFAULT['search_url'])
    if not isinstance(enabled, bool) or not isinstance(url, str):
        raise ValueError('Invalid web-search settings.')
    url = url.strip()
    if url or enabled:
        validate_url(url)
    return {'search_enabled': enabled, 'search_url': url}


def save(config):
    atomic_json(config_dir() / 'yes-man-tools.json', validate(config))
