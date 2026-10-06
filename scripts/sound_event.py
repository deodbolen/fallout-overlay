#!/usr/bin/python3
"""Send a named sound event; no command/password payload."""
import os
import sys

def emit(event):
    path=os.environ.get('FALLOUT_SOUND_SOCKET')
    if path:
        from embedded_client import request
        previous=os.environ.get('FALLOUT_EMBEDDED_SOCKET')
        os.environ['FALLOUT_EMBEDDED_SOCKET']=path
        try: request('sound',event=event)
        except (OSError,ValueError): pass
        finally:
            if previous is None: os.environ.pop('FALLOUT_EMBEDDED_SOCKET',None)
            else: os.environ['FALLOUT_EMBEDDED_SOCKET']=previous

if __name__=='__main__': emit(sys.argv[1])
