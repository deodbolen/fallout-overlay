#!/usr/bin/python3
"""End-to-end IPC launch, attach/detach, status, close and window toggle."""
import os
from pathlib import Path
import socket
import tempfile
import threading
import traceback
from embedded_app import Host,Gtk,GLib
from embedded_client import request

work=tempfile.TemporaryDirectory(prefix='fallout-rpc-check-'); root=Path(work.name)
os.environ['XDG_STATE_HOME']=str(root/'state')
path=root/'host.sock'; listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
listener.bind(str(path)); listener.listen(16)
host=Host(path,listener)
os.environ['FALLOUT_EMBEDDED_SOCKET']=str(path)
errors=[]

def check():
    try:
        record=request('launch',action='shell',label='RPC shell',details={'cwd':str(root)})
        assert request('status',id=record['id'])['status'] in ('starting','running')
        GLib.idle_add(lambda: (GLib.timeout_add(500,lambda: (host.detach(),False)[1]),False)[1])
        assert request('attach',id=record['id'])['id']==record['id']
        request('toggle'); request('toggle')
        request('close',id=record['id'])
        assert request('status',id=record['id'])['status']=='closed'
        print('PASS: embedded RPC launch, status, attach/detach, F12 toggle and close.',flush=True)
    except Exception: errors.append(traceback.format_exc())
    finally: GLib.idle_add(lambda: (host.shutdown(),False)[1])
GLib.timeout_add(500,lambda: (threading.Thread(target=check,daemon=True).start(),False)[1])
GLib.timeout_add_seconds(8,lambda: (errors.append('RPC test timed out'),host.shutdown(),False)[2])
Gtk.main(); work.cleanup()
if errors: raise SystemExit('\n'.join(errors))
