"""Saved remote file-server locations; credentials stay in the desktop keyring."""
import json
import uuid
from urllib.parse import urlsplit
from ssh_manager import atomic_json, config_dir


def validate_uri(value):
    value=value.strip()
    parsed=urlsplit(value)
    if parsed.scheme not in ('smb','sftp') or not parsed.hostname:
        raise ValueError('Use smb://server/share or sftp://user@server/path.')
    if parsed.password is not None:
        raise ValueError('Leave passwords out of the address; authentication prompts when connecting.')
    if parsed.query or parsed.fragment or any(ord(c)<32 for c in value):
        raise ValueError('Invalid server address.')
    if parsed.scheme=='smb' and not parsed.path.strip('/'):
        raise ValueError('Include the SMB share name: smb://server/share.')
    parsed.port  # Validate the port before saving.
    return value


def servers():
    path=config_dir()/'file-servers.json'
    if not path.exists(): return []
    data=json.loads(path.read_text())
    if not isinstance(data,list): raise ValueError('Invalid file-server catalog.')
    return data


def add_server(name,uri):
    name=name.strip()
    if not name: raise ValueError('Server name is required.')
    record={'id':uuid.uuid4().hex,'name':name,'uri':validate_uri(uri)}
    atomic_json(config_dir()/'file-servers.json',servers()+[record])
    return record
