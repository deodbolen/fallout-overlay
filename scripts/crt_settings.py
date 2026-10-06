"""Persistent navigator CRT toggle and desktop autostart."""
import json
import os
from pathlib import Path
import subprocess
import time
from ssh_manager import config_dir, atomic_json, state_dir

SCRIPT=Path(__file__).with_name('crt_overlay.py').resolve()

def runtime_dir(): return Path(os.environ.get('XDG_RUNTIME_DIR',str(Path.home()/'.cache')))/'fallout-ui'

def running():
    try:
        pid=int((runtime_dir()/'crt.pid').read_text())
        return str(SCRIPT).encode() in Path(f'/proc/{pid}/cmdline').read_bytes()
    except (OSError,ValueError): return False

def preferences():
    path=config_dir()/'settings.json'
    return json.loads(path.read_text()) if path.exists() else {}

def enabled(): return bool(preferences().get('crt_overlay',False))

def animation_enabled(): return bool(preferences().get('crt_animation',False))

def write_autostart(on):
    file=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'autostart/fallout-crt.desktop'
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_text('[Desktop Entry]\nType=Application\nName=Fallout CRT scanlines\nExec=/usr/bin/python3 "'+str(SCRIPT)+'"\nOnlyShowIn=XFCE;\nHidden='+('false' if on else 'true')+'\nX-GNOME-Autostart-enabled='+('true' if on else 'false')+'\nTerminal=false\n')

def save(on):
    path=config_dir()/'settings.json'
    data=json.loads(path.read_text()) if path.exists() else {}
    data['crt_overlay']=on; atomic_json(path,data); write_autostart(on or data.get('crt_animation',False))

def stop():
    subprocess.run(['/usr/bin/python3',str(SCRIPT),'--stop'],check=True)
    for _ in range(20):
        if not running(): return
        time.sleep(.05)
    raise ValueError('The CRT overlay did not stop; inspect crt.log.')

def apply_preferences(field,on):
    data=preferences(); previous=dict(data)
    data[field]=on
    stop()
    atomic_json(config_dir()/'settings.json',data)
    active=bool(data.get('crt_overlay',False) or data.get('crt_animation',False))
    write_autostart(active)
    if active:
        folder=state_dir(); folder.mkdir(parents=True,exist_ok=True)
        with (folder/'crt.log').open('a') as stream:
            process=subprocess.Popen(['/usr/bin/python3',str(SCRIPT)],stdout=stream,stderr=stream,start_new_session=True)
        for _ in range(30):
            if process.poll() is not None: break
            if running(): return
            time.sleep(.05)
        atomic_json(config_dir()/'settings.json',previous)
        write_autostart(bool(previous.get('crt_overlay',False) or previous.get('crt_animation',False)))
        raise ValueError('CRT effects could not start. See ~/.local/state/fallout-ui/crt.log.')

def set_enabled(on): apply_preferences('crt_overlay',on)

def set_animation(on): apply_preferences('crt_animation',on)
