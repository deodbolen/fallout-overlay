"""Virtual terminal display with a separate, protected bottom reminder row."""
import copy
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'vendor/python'))
import pyte

FOOTER='Ctrl+]  Hold Ctrl and press ] to return to the navigator | Ctrl+↑/↓ switch sessions | Session stays running'

class TerminalScreen(pyte.Screen):
    def __init__(self,columns,lines,reply=lambda data: None):
        self.reply=reply
        self.normal=None
        super().__init__(columns,lines)

    def write_process_input(self,data):
        self.reply(data.encode())

    def set_mode(self,*modes,**kwargs):
        if kwargs.get('private') and set(modes)&{47,1047,1049} and self.normal is None:
            self.normal={name:copy.deepcopy(getattr(self,name)) for name in ('buffer','cursor','savepoints','margins')}
            self.buffer.clear(); self.cursor_position(); self.margins=None
            self.dirty.update(range(self.lines))
        super().set_mode(*modes,**kwargs)

    def reset_mode(self,*modes,**kwargs):
        if kwargs.get('private') and set(modes)&{47,1047,1049} and self.normal is not None:
            for name,value in self.normal.items(): setattr(self,name,value)
            self.normal=None; self.dirty.update(range(self.lines))
        super().reset_mode(*modes,**kwargs)

    def resize(self,lines=None,columns=None):
        super().resize(lines=lines,columns=columns)
        self.cursor.x=min(self.cursor.x,self.columns-1)
        self.cursor.y=min(self.cursor.y,self.lines-1)
        if self.normal is not None:
            self.normal['cursor'].x=min(self.normal['cursor'].x,self.columns-1)
            self.normal['cursor'].y=min(self.normal['cursor'].y,self.lines-1)


def style(char):
    codes=['0']
    for attribute,code in [('bold','1'),('italics','3'),('underscore','4'),('reverse','7'),('strikethrough','9')]:
        if getattr(char,attribute): codes.append(code)
    colors=['black','red','green','brown','blue','magenta','cyan','white']
    for color,prefix,base in [(char.fg,'38',30),(char.bg,'48',40)]:
        if color=='default': continue
        if color in colors: codes.append(str(base+colors.index(color)))
        elif color.startswith('bright') and color[6:] in colors: codes.append(str(base+60+colors.index(color[6:])))
        elif len(color)==6:
            try: codes.append(prefix+';2;'+';'.join(str(int(color[i:i+2],16)) for i in (0,2,4)))
            except ValueError: pass
    return '\x1b['+';'.join(codes)+'m'


def render(screen,physical_lines,columns,full=False):
    """Paint virtual content; session escape sequences never reach the footer."""
    rows=range(screen.lines) if full else sorted(screen.dirty)
    output=['\x1b[?25l\x1b[?7l']
    for y in rows:
        output.append(f'\x1b[{y+1};1H\x1b[0m\x1b[2K')
        previous=None
        for x in range(screen.columns):
            char=screen.buffer[y][x]
            if not char.data: continue # wide character's second cell
            current=style(char)
            if current!=previous: output.append(current); previous=current
            output.append(char.data)
    footer=FOOTER[:max(0,columns-1)]
    output.append(f'\x1b[{physical_lines};1H\x1b[0;1;7;92m\x1b[2K'+footer+'\x1b[0m')
    output.append(f'\x1b[{min(screen.cursor.y,screen.lines-1)+1};{min(screen.cursor.x,columns-1)+1}H')
    output.append('\x1b[?7h')
    if not screen.cursor.hidden: output.append('\x1b[?25h')
    output.append('\x1b[?1h' if 32 in screen.mode else '\x1b[?1l')
    output.append('\x1b[?2004h' if (2004<<5) in screen.mode else '\x1b[?2004l')
    screen.dirty.clear()
    return ''.join(output).encode('utf-8')
