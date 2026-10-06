"""Local host/key catalog and argument-safe OpenSSH operations."""
import contextlib
import fcntl
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid


def config_dir():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'fallout-ui'


def state_dir():
    return Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state'))/'fallout-ui'


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('x') as stream:
            os.chmod(temp, 0o600)
            json.dump(data, stream, indent=2)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class Catalog:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else config_dir()
        self.path = self.directory/'ssh.json'

    def read(self):
        if not self.path.exists(): return {'hosts': [], 'keys': [], 'installed': []}
        data = json.loads(self.path.read_text())
        if not isinstance(data,dict) or any(not isinstance(data.get(k),list) for k in ('hosts','keys','installed')):
            raise ValueError('Invalid SSH catalog; original file was left untouched.')
        return data

    def update(self, change):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory/'ssh.lock').open('a') as lock:
            os.chmod(self.directory/'ssh.lock',0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.read(); change(data); atomic_json(self.path,data)

    def save_host(self, name, address, user='', key='', identifier=None):
        name, address, user = name.strip(), address.strip(), user.strip()
        if not name: raise ValueError('Common name is required.')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:%_-]*',address):
            raise ValueError('Enter an IP address or FQDN, without a user, port, or spaces.')
        if user and not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',user):
            raise ValueError('Invalid SSH username.')
        host={'id':identifier or uuid.uuid4().hex,'name':name,'address':address,'user':user,'key':key}
        def change(data):
            if key and not any(k['id']==key for k in data['keys']): raise ValueError('Selected key is no longer saved.')
            data['hosts']=[h for h in data['hosts'] if h['id']!=host['id']]+[host]
        self.update(change)
        return host

    def add_key(self,name,path,identifier=None):
        item={'id':identifier or uuid.uuid4().hex,'name':name,'path':str(path)}
        self.update(lambda data: data['keys'].append(item))
        return item

    def installed(self,host,key,directory):
        blob=public_key(key)[1]
        record={'id':uuid.uuid4().hex,'host':{**host,'user':username(host)},'key':key['id'],'directory':directory,'blob':blob}
        def change(data):
            identity=lambda i:(i['host']['address'],username(i['host']),i['directory'],i['blob'])
            if not any(identity(i)==identity(record) for i in data['installed']): data['installed'].append(record)
            for saved in data['hosts']:
                if saved['id']==host['id'] and saved['address']==host['address'] and username(saved)==username(host): saved['key']=key['id']
        self.update(change)


def username(host): return host.get('user') or getpass.getuser()


def target(host): return username(host)+'@'+host['address']


def ssh_args(host,key=None,password_only=False,key_only=False):
    args=['ssh','-o','ConnectTimeout=15','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3']
    if key:
        path=Path(key['path']).expanduser()
        if not path.is_file(): raise ValueError('Private key is missing: '+str(path))
        args+=['-i',str(path),'-o','IdentitiesOnly=yes']
    if password_only: args+=['-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password,keyboard-interactive']
    if key_only: args+=['-o','PreferredAuthentications=publickey','-o','PasswordAuthentication=no','-o','KbdInteractiveAuthentication=no']
    return args+[target(host)]


def public_key(key):
    lines=Path(key['path']+'.pub').read_text().splitlines()
    if len(lines)!=1: raise ValueError('Expected one public key in the .pub file.')
    parts=lines[0].split()
    if len(parts)<2 or not re.fullmatch(r'[A-Za-z0-9+/=]+',parts[1]) or not parts[0].startswith(('ssh-','ecdsa-','sk-')):
        raise ValueError('Invalid public key.')
    return parts[0],parts[1],lines[0]


def remote_directory(value):
    value=value.strip()
    if not value or any(ord(c)<32 for c in value): raise ValueError('Remote directory is required; control characters are not allowed.')
    if value in ('/','.','~'): raise ValueError('Use a dedicated SSH directory, such as ~/.ssh.')
    return value


def remote_command(directory,blob,mode,line=''):
    directory=remote_directory(directory)
    # Every user-controlled string is shell quoted. Only the public key goes remotely.
    script=r'''set -eu
umask 077
directory=DIR
case "$directory" in '~/'*) directory="$HOME/${directory#\~/}";; esac
file="$directory/authorized_keys"
'''.replace('DIR',shlex.quote(directory))
    if mode=='push':
        script+='mkdir -p "$directory"\nchmod 700 "$directory"\n'
    else: script+='[ -f "$file" ] || exit 0\n'
    script+='''[ ! -L "$file" ] || { echo 'Refusing a symlinked authorized_keys file.' >&2; exit 1; }
lock="$directory/.fallout-key-lock"
mkdir "$lock" 2>/dev/null || { echo 'Key file is busy; retry later.' >&2; exit 1; }
tmp=''
trap 'test -z "$tmp" || rm -f "$tmp"; rmdir "$lock"' EXIT HUP INT TERM
'''
    quoted_blob=shlex.quote(blob)
    if mode=='push':
        script+=f'''if [ -f "$file" ] && awk -v key={quoted_blob} '{{for(i=1;i<=NF;i++) if($i==key) found=1}} END {{exit !found}}' "$file"; then exit 0; fi
'''
    script+='tmp=$(mktemp "$directory/.authorized_keys.XXXXXX")\n'
    if mode=='push':
        script+='[ ! -f "$file" ] || cat "$file" > "$tmp"\n'
        script+=f"printf '\\n%s\\n' {shlex.quote(line)} >> \"$tmp\"\n"
    elif mode=='revoke':
        script+=f'''awk -v key={quoted_blob} '{{remove=0; for(i=1;i<=NF;i++) if($i==key) remove=1; if(!remove) print}}' "$file" > "$tmp"
'''
    else: raise ValueError('Unknown key operation.')
    script+='chmod 600 "$tmp"\nmv "$tmp" "$file"\ntmp=\n'
    return 'sh -c '+shlex.quote(script)


def generate_path(name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',name):
        raise ValueError('Key name: use letters, numbers, underscores or dashes (max 64).')
    path=Path.home()/'.ssh'/('fallout_'+name)
    if path.exists() or Path(str(path)+'.pub').exists(): raise ValueError('That key filename already exists.')
    return path

