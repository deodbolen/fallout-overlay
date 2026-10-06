"""Curses navigator bridge to the native embedded terminal host."""
import json
import os
import socket


def request(command,**details):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        connection.connect(os.environ['FALLOUT_EMBEDDED_SOCKET'])
        connection.sendall(json.dumps({'command':command,**details}).encode()+b'\n')
        stream=connection.makefile('rb')
        line=stream.readline(65537)
        if not line: raise OSError('Embedded terminal host disconnected.')
        response=json.loads(line)
        if 'error' in response: raise ValueError(response['error'])
        return response

class Process:
    def __init__(self,session): self.session=session
    def poll(self): return 0 if self.session.status=='closed' else None

class Session:
    def __init__(self,record):
        self.id=record['id']; self.label=record['label']; self.process=Process(self)
    @property
    def status(self): return request('status',id=self.id)['status']
    def close(self): request('close',id=self.id)

class Sessions:
    def __init__(self): self.items=[]
    def launch(self,action,label,**details):
        session=Session(request('launch',action=action,label=label,details=details))
        self.items.append(session); return session
    def attach(self,screen,session,on_switch=lambda session: None):
        on_switch(session)
        result=request('attach',id=session.id)
        current=next((s for s in self.items if s.id==result.get('id')),session)
        on_switch(current)
        screen.clear(); screen.refresh()
    def close(self):
        for session in self.items: session.close()
