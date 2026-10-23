"""Visible, horizontally scrolling text fields for both terminal interfaces."""
import curses
import os
import unicodedata


def cells(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W','F') else 1 for c in text)


class TextField:
    def __init__(self,value=''):
        self.replace(value)

    def replace(self,value):
        self.value=value
        self.position=len(value)

    def edit(self,key):
        if key==curses.KEY_LEFT: self.position=max(0,self.position-1)
        elif key==curses.KEY_RIGHT: self.position=min(len(self.value),self.position+1)
        elif key in (curses.KEY_HOME,'\x01'): self.position=0
        elif key in (curses.KEY_END,'\x05'): self.position=len(self.value)
        elif key in (curses.KEY_BACKSPACE,'\x7f','\b'):
            if self.position:
                self.value=self.value[:self.position-1]+self.value[self.position:]
                self.position-=1
        elif key==curses.KEY_DC: self.value=self.value[:self.position]+self.value[self.position+1:]
        elif key=='\x15': self.replace('')
        elif isinstance(key,str) and key.isprintable() and len(self.value)+len(key)<=512:
            self.value=self.value[:self.position]+key+self.value[self.position:]
            self.position+=len(key)


def cursor(visible):
    try: curses.curs_set(1 if visible else 0)
    except curses.error: pass
    if os.isatty(1):
        # DECSCUSR: blinking bar while editing, then restore terminal default.
        os.write(1,b'\x1b[5 q' if visible else b'\x1b[0 q')


def draw_box(screen,field):
    height,width=screen.getmaxyx()
    if height<3 or width<5: return
    top=min(3,height-3)
    left=2 if width>=12 else 0
    capacity=max(1,min(72,width-left-3))
    start=0
    while start<field.position and cells(field.value[start:field.position])>=capacity:
        start+=1
    shown=''
    for char in field.value[start:]:
        char=char if char.isprintable() else '?'
        if cells(shown+char)>capacity: break
        shown+=char
    lines=['+'+'-'*capacity+'+', '|'+shown+' '*(capacity-cells(shown))+'|', '+'+'-'*capacity+'+']
    for offset,line in enumerate(lines):
        try: screen.addnstr(top+offset,left,line,width-left-1,curses.A_BOLD if offset!=1 else curses.A_NORMAL)
        except curses.error: pass
    screen.move(top+1,left+1+cells(field.value[start:field.position]))
    screen.refresh()


def terminal_text(label,initial=''):
    """Use the same field for the session wrapper's custom path prompt."""
    from navigator_input import read_key
    def prompt(screen):
        screen.keypad(True)
        field=TextField(initial)
        cursor(True)
        try:
            while True:
                screen.erase()
                _,width=screen.getmaxyx()
                screen.addnstr(1,0,label,max(1,width-1),curses.A_BOLD)
                draw_box(screen,field)
                key=read_key(screen)
                if key in ('\n','\r',curses.KEY_ENTER): return field.value.strip()
                if key=='\x1b': return None
                field.edit(key)
        finally: cursor(False)
    return curses.wrapper(prompt)
