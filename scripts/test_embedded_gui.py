#!/usr/bin/python3
"""Real VTE GUI smoke test, isolated documents and state; closes itself."""
if __name__ != '__main__':
    import unittest
    raise unittest.SkipTest('Run directly from an XFCE session; this test opens a GTK window.')

import os
from pathlib import Path
import socket
import tempfile
import traceback
import sys
from types import SimpleNamespace

work=tempfile.TemporaryDirectory(prefix='fallout-embedded-check-')
root=Path(work.name)
os.environ['XDG_STATE_HOME']=str(root/'state')
os.environ['XDG_CONFIG_HOME']=str(root/'config')
from embedded_app import Host,Gtk,GLib,Gdk,NAV_FONT,SHELL_FONT,EDITOR_FONT
path=root/'host.sock'
listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); listener.bind(str(path)); listener.listen(16)
host=Host(path,listener)
document=root/'check.txt'; document.write_text('original text\n')
failed=[]; records={}

def guard(callback):
    def run():
        try: callback()
        except Exception:
            failed.append(traceback.format_exc()); host.shutdown()
        return False
    return run

def start_editor():
    assert host.navigator.get_font().to_string()==NAV_FONT
    record=host.launch('editor','Nano test',{'path':str(document),'cwd':str(root)})
    records['editor']=record['id']; host.show_session(record['id'])
    GLib.timeout_add(800,guard(edit_document))

def edit_document():
    record=host.records[records['editor']]
    assert record['pid'] is not None
    assert record['terminal'].get_font().to_string()==EDITOR_FONT
    record['terminal'].feed_child(b'added \x0f')
    GLib.timeout_add(200,guard(confirm_save))

def confirm_save():
    host.records[records['editor']]['terminal'].feed_child(b'\r')
    GLib.timeout_add(200,guard(exit_nano))

def exit_nano():
    host.records[records['editor']]['terminal'].feed_child(b'\x18')
    GLib.timeout_add(600,guard(check_shell))

def check_shell():
    editor=host.records[records['editor']]
    assert document.read_text().startswith('added original text'),document.read_text()
    assert editor['terminal'].get_font().to_string()==SHELL_FONT
    assert host.navigator.get_font().to_string()==NAV_FONT
    record=host.launch('shell','Second local terminal',{'cwd':str(root)})
    records['shell']=record['id']; host.show_session(record['id'])
    GLib.timeout_add(500,guard(check_switching))

def check_switching():
    terminal=host.records[records['shell']]['terminal']
    event=SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK,keyval=Gdk.KEY_Up)
    assert host.session_keys(terminal,event)
    assert host.current==records['editor']
    assert host.static_timer is not None
    assert host.static_until>__import__('time').monotonic()
    event.keyval=Gdk.KEY_Down; host.session_keys(terminal,event)
    assert host.current==records['shell']
    event.keyval=Gdk.KEY_bracketright; host.session_keys(terminal,event)
    assert host.stack.get_visible_child_name()=='navigator'
    assert not host.records[records['editor']]['closed']
    print('PASS: real Nano edit/save; 11pt editor, 14pt shell, 16pt navigator; Ctrl+Up/Down switching; Ctrl+] detach.',flush=True)
    host.shutdown()

GLib.timeout_add(700,guard(start_editor))
GLib.timeout_add_seconds(10,guard(lambda: (_ for _ in ()).throw(AssertionError('GUI smoke test timed out'))))
Gtk.main()
work.cleanup()
if failed:
    print('\n'.join(failed),file=sys.stderr); raise SystemExit(1)
