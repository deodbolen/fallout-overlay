"""Plain UTF-8 clipboard/export. No markup conversion or entity decoding."""
import base64
import os
from pathlib import Path
import re


def plain_text(text):
    # Terminal control strings, including OSC hyperlinks, have no plain-text
    # representation. Preserve their displayed labels and every literal '&',
    # backslash, Markdown delimiter, URL, combining mark and emoji.
    text=re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '',text)
    text=re.sub(r'\x1b[P^_].*?\x1b\\','',text,flags=re.S)
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b[ -/]*[@-~]', '',text)
    return text


def export_text(path,text):
    path=Path(path).expanduser()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='') as stream:
            stream.write(plain_text(text))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def copy_terminal_text(text):
    data=plain_text(text).encode('utf-8')
    if len(data)>1024*1024:
        raise ValueError('Selection exceeds the clipboard request limit. Export it to a text file instead.')
    # Only emitted in response to an explicit user Copy action. The client
    # terminal decides whether remote clipboard requests are permitted.
    packet=memoryview(b'\x1b]52;c;'+base64.b64encode(data)+b'\x07')
    while packet:
        written=os.write(1,packet)
        if written<=0:raise OSError('Terminal clipboard output stopped.')
        packet=packet[written:]


def vte_text(widget,Gio,Vte):
    # get_text()/accessibility text cover only the visible viewport. This API
    # explicitly includes retained scrollback and writes plain UTF-8.
    stream=Gio.MemoryOutputStream.new_resizable()
    try:
        widget.write_contents_sync(stream,Vte.WriteFlags.DEFAULT,None)
        stream.close(None)
        return plain_text(bytes(stream.steal_as_bytes().get_data()).decode('utf-8'))
    finally:
        if not stream.is_closed():stream.close(None)
