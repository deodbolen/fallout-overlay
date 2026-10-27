#!/usr/bin/env python3
"""Read-only terminal key diagnostic; never saves input or changes settings."""
import os
import select
import sys
import termios
import time
import tty
from session_input import InputRouter


def main():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit('Run this in an interactive terminal, such as an SSH session.')
    fd=sys.stdin.fileno()
    original=termios.tcgetattr(fd)
    print('Press F1, F2, Ctrl+O, and Ctrl+P, one at a time.')
    print('On Mac brightness keys, try holding Fn with F1/F2.')
    print('Testing shortcut code from: '+os.path.dirname(os.path.realpath(__file__)))
    print('Only press test keys. Nothing is saved. Press Ctrl+C to exit.')
    print('If a shortcut moves the Mac desktop or produces no output, it is being intercepted locally.',flush=True)
    try:
        tty.setraw(fd)
        last=time.monotonic()
        while True:
            if not select.select([fd],[],[],1)[0]:
                if time.monotonic()-last>=10:
                    os.write(1,b'No key bytes received in the last 10 seconds.\r\n')
                    last=time.monotonic()
                continue
            data=os.read(fd,128)
            if not data or b'\x03' in data: break
            # Group escape sequences split into several SSH packets.
            deadline=time.monotonic()+.25
            while time.monotonic()<deadline and select.select([fd],[],[],.03)[0]:
                chunk=os.read(fd,128)
                if not chunk or b'\x03' in chunk: return
                data+=chunk
                if len(data)>=512: break
            os.write(1,('Received '+repr(data)+'  hex='+data.hex(' ')+'\r\n').encode())
            forwarded,action,_=InputRouter().feed(data)
            os.write(1,('TUI action: '+(action or 'none (not a session shortcut)')+'\r\n').encode())
            last=time.monotonic()
    finally:
        termios.tcsetattr(fd,termios.TCSADRAIN,original)
        print('\nKey test ended.',flush=True)


if __name__=='__main__': main()
