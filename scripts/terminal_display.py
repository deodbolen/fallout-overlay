"""Virtual terminal display with a separate, protected bottom reminder row."""
import copy
from collections import deque
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'vendor/python'))
import pyte
from wcwidth import wcwidth,wcswidth

FOOTER='F1/F2 Sessions | F3/F4 History | F5 Copy view | Ctrl+] Navigator'


def graphemes(text):
    cluster=''
    for char in text:
        regional=lambda c:'\U0001f1e6'<=c<='\U0001f1ff'
        if cluster and (wcwidth(char)==0 or '\U0001f3fb'<=char<='\U0001f3ff' or cluster.endswith('\u200d') or
                        (regional(char) and len(cluster)==1 and regional(cluster))):
            cluster+=char
        else:
            if cluster:yield cluster
            cluster=char
    if cluster:yield cluster


def text_slice(text,start,width):
    position=0;result='';used=0
    for cluster in graphemes(text.expandtabs(8)):
        length=max(0,wcswidth(cluster))
        if position<start:
            position+=length
            continue
        if used+length>width:break
        result+=cluster;used+=length;position+=length
    return result

class TerminalScreen(pyte.Screen):
    def __init__(self,columns,lines,reply=lambda data: None,history_limit=10000):
        self.reply=reply
        self.normal=None
        self.history=deque()
        self.history_limit=max(10000,int(history_limit))
        self.history_lines=0
        self.scroll_offset=0
        self.cluster=None
        super().__init__(columns,lines)

    def write_process_input(self,data):
        self.reply(data.encode())

    @property
    def display(self):
        return [''.join(self.buffer[y][x].data for x in range(self.columns)) for y in range(self.lines)]

    def archive(self,row):
        self.history.append(row)
        self.history_lines+=not getattr(row,'softwrap',False)
        if self.scroll_offset: self.scroll_offset+=1
        while self.history_lines>self.history_limit:
            removed=self.history.popleft()
            self.history_lines-=not getattr(removed,'softwrap',False)

    def set_history_limit(self,value):
        self.history_limit=max(10000,int(value))
        while self.history_lines>self.history_limit:
            row=self.history.popleft()
            self.history_lines-=not getattr(row,'softwrap',False)
        self.scroll_offset=min(self.scroll_offset,len(self.history))

    def index(self):
        top,bottom=self.margins or (0,self.lines-1)
        if self.normal is None and top==0 and bottom==self.lines-1 and self.cursor.y==bottom:
            self.archive(self.buffer[top])
        super().index()

    def linefeed(self):
        if not getattr(self,'wrapping',False):
            self.buffer[self.cursor.y].hardline=True
        super().linefeed()
        self.cluster=None

    def draw(self,data):
        # Store grapheme clusters in their leading cell. Continuation cells are
        # empty, so CJK, combining marks, VS16, emoji modifiers and ZWJ sequences
        # are exported once and never split into unrelated terminal cells.
        data=data.translate(self.g1_charset if self.charset else self.g0_charset)
        for char in data:
            row=self.buffer[self.cursor.y]
            prior=self.cluster
            if prior:
                oldrow,x=prior
                old=oldrow[x]
                oldwidth=max(1,wcswidth(old.data))
                regional=lambda c: '\U0001f1e6'<=c<='\U0001f1ff'
                joins=(wcwidth(char)==0 or '\U0001f3fb'<=char<='\U0001f3ff' or
                       old.data.endswith('\u200d') or (regional(char) and len(old.data)==1 and regional(old.data)))
                if oldrow is row and self.cursor.x==x+oldwidth and joins:
                    text=old.data+char
                    width=max(1,wcswidth(text))
                    if x+width>self.columns and pyte.modes.DECAWM in self.mode:
                        oldrow.pop(x,None);oldrow.text_end=x;oldrow.softwrap=True
                        self.wrapping=True
                        try:self.carriage_return();self.linefeed()
                        finally:self.wrapping=False
                        row=self.buffer[self.cursor.y]
                        row[0]=old._replace(data=text)
                        if width==2 and self.columns>1:row[1]=old._replace(data='')
                        row.text_end=width;self.cursor.x=min(width,self.columns)
                        self.cluster=(row,0);self.dirty.update(range(self.lines))
                        continue
                    oldrow[x]=old._replace(data=text)
                    for column in range(x+1,min(self.columns,x+width)): oldrow[column]=old._replace(data='')
                    self.cursor.x=min(self.columns,x+width)
                    oldrow.text_end=max(getattr(oldrow,'text_end',0),self.cursor.x)
                    self.dirty.add(self.cursor.y)
                    continue
            width=wcwidth(char)
            if width<=0: continue
            if self.cursor.x+width>self.columns and pyte.modes.DECAWM in self.mode:
                row.softwrap=True
                self.wrapping=True
                try:
                    self.carriage_return(); self.linefeed()
                finally: self.wrapping=False
                row=self.buffer[self.cursor.y]
            elif self.cursor.x>=self.columns:
                self.cursor.x=max(0,self.columns-width)
            if pyte.modes.IRM in self.mode: self.insert_characters(width)
            x=self.cursor.x
            # Replace complete wide cells rather than leaving an orphan stub.
            if row[x].data=='' and x:
                row[x-1]=self.cursor.attrs._replace(data=' ')
            if wcswidth(row[x].data)>1 and x+1<self.columns:
                row[x+1]=self.cursor.attrs._replace(data=' ')
            row[x]=self.cursor.attrs._replace(data=char)
            if width==2 and x+1<self.columns: row[x+1]=self.cursor.attrs._replace(data='')
            self.cursor.x=min(self.columns,x+width)
            row.text_end=max(getattr(row,'text_end',0),self.cursor.x)
            self.cluster=(row,x)
            self.dirty.add(self.cursor.y)

    def erase_in_line(self,how=0,private=False):
        row=self.buffer[self.cursor.y]
        super().erase_in_line(how,private)
        if how in (0,2):
            row.text_end=0 if how==2 else min(getattr(row,'text_end',0),self.cursor.x)
            row.softwrap=False
            row.hardline=False
        self.cluster=None

    def insert_characters(self,count=None):
        row=self.buffer[self.cursor.y];extent=getattr(row,'text_end',0)
        super().insert_characters(count)
        if self.cursor.x<extent:row.text_end=min(self.columns,extent+(count or 1))

    def delete_characters(self,count=None):
        row=self.buffer[self.cursor.y];extent=getattr(row,'text_end',0)
        super().delete_characters(count)
        if self.cursor.x<extent:row.text_end=max(self.cursor.x,extent-(count or 1))

    def erase_in_display(self,how=0,private=False):
        super().erase_in_display(how,private)
        rows=range(self.lines) if how in (2,3) else range(self.cursor.y+1,self.lines) if how==0 else range(self.cursor.y)
        for y in rows:
            row=self.buffer[y]; row.text_end=0; row.softwrap=False; row.hardline=False
        if how==3 and self.normal is None:
            self.history.clear(); self.history_lines=0; self.scroll_offset=0
        self.cluster=None

    @staticmethod
    def row_text(row):
        return ''.join(row[x].data for x in range(getattr(row,'text_end',0)))

    def all_rows(self):
        buffer=self.normal['buffer'] if self.normal else self.buffer
        count=self.normal['lines'] if self.normal else self.lines
        return list(self.history)+[buffer[y] for y in range(count)]

    def export_text(self):
        rows=self.all_rows()
        while rows and not getattr(rows[-1],'text_end',0) and not getattr(rows[-1],'hardline',False): rows.pop()
        parts=[]
        for index,row in enumerate(rows):
            parts.append(self.row_text(row))
            if not getattr(row,'softwrap',False) and (index<len(rows)-1 or getattr(row,'hardline',False)):
                parts.append('\n')
        return ''.join(parts)

    def scroll(self,amount):
        if self.normal is not None: return
        self.scroll_offset=max(0,min(len(self.history),self.scroll_offset+amount))
        self.dirty.update(range(self.lines))

    def view_rows(self):
        if not self.scroll_offset: return [self.buffer[y] for y in range(self.lines)]
        self.scroll_offset=min(self.scroll_offset,len(self.history))
        rows=list(self.history)+[self.buffer[y] for y in range(self.lines)]
        end=len(rows)-self.scroll_offset
        return rows[max(0,end-self.lines):end]

    def set_mode(self,*modes,**kwargs):
        if kwargs.get('private') and set(modes)&{47,1047,1049} and self.normal is None:
            self.normal={name:copy.deepcopy(getattr(self,name)) for name in ('buffer','cursor','savepoints','margins','mode','charset','g0_charset','g1_charset','tabstops','lines','columns')}
            self.buffer.clear(); self.cursor_position(); self.margins=None; self.cluster=None; self.scroll_offset=0
            self.dirty.update(range(self.lines))
        super().set_mode(*modes,**kwargs)

    def reset_mode(self,*modes,**kwargs):
        if kwargs.get('private') and set(modes)&{47,1047,1049} and self.normal is not None:
            lines,columns=self.lines,self.columns
            for name,value in self.normal.items(): setattr(self,name,value)
            self.normal=None; self.cluster=None
            self.resize(lines,columns)
            self.dirty.update(range(self.lines))
        super().reset_mode(*modes,**kwargs)

    def resize(self,lines=None,columns=None):
        lines,columns=lines or self.lines,columns or self.columns
        if (lines,columns)==(self.lines,self.columns): return
        if self.normal is not None:
            super().resize(lines=lines,columns=columns)
            self.cluster=None
            return
        # Reflow complete logical lines, retaining both history and styled cells.
        oldrows=list(self.history)+[self.buffer[y] for y in range(self.lines)]
        cursor_row=len(self.history)+self.cursor.y
        groups=[]; group=[]; cursor_group=None; cursor_offset=0; offset=0
        for index,row in enumerate(oldrows):
            if index==cursor_row: cursor_group=len(groups); cursor_offset=offset+self.cursor.x
            extent=getattr(row,'text_end',0)
            group.extend(row[x] for x in range(extent) if row[x].data)
            offset+=extent
            if not getattr(row,'softwrap',False):
                groups.append((group,getattr(row,'hardline',False)));group=[];offset=0
        if group: groups.append((group,False))
        rebuilt=[]; new_cursor=(0,0)
        for number,(characters,hardline) in enumerate(groups):
            row=pyte.screens.StaticDefaultDict(self.default_char); position=0
            start=len(rebuilt)
            for char in characters:
                width=max(1,wcswidth(char.data))
                if position+width>columns:
                    row.softwrap=True; row.text_end=position; rebuilt.append(row)
                    row=pyte.screens.StaticDefaultDict(self.default_char);position=0
                row[position]=char
                if width==2 and position+1<columns:row[position+1]=char._replace(data='')
                position+=width
            row.text_end=position;row.hardline=hardline;rebuilt.append(row)
            if number==cursor_group:
                remaining=cursor_offset
                for index in range(start,len(rebuilt)):
                    length=getattr(rebuilt[index],'text_end',0)
                    if remaining<=length or index==len(rebuilt)-1:
                        new_cursor=(index,min(remaining,columns));break
                    remaining-=length
        while len(rebuilt)>lines and new_cursor[0]<len(rebuilt)-lines and not getattr(rebuilt[-1],'text_end',0) and not getattr(rebuilt[-1],'hardline',False):rebuilt.pop()
        visible_start=max(0,len(rebuilt)-lines)
        self.history.clear();self.history_lines=0
        for row in rebuilt[:visible_start]:self.archive(row)
        self.buffer.clear()
        for y,row in enumerate(rebuilt[visible_start:]):self.buffer[y]=row
        self.lines,self.columns=lines,columns
        self.cursor.y=max(0,min(lines-1,new_cursor[0]-visible_start));self.cursor.x=new_cursor[1]
        self.margins=None;self.cluster=None;self.scroll_offset=min(self.scroll_offset,len(self.history))
        self.tabstops=set(range(8,columns,8));self.dirty=set(range(lines))


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


def render(screen,physical_lines,columns,full=False,session_status=''):
    """Paint virtual content; session escape sequences never reach the footer."""
    rows=range(screen.lines) if full or screen.scroll_offset else sorted(y for y in screen.dirty if 0<=y<screen.lines)
    visible=screen.view_rows()
    output=['\x1b[?25l\x1b[?7l']
    for y in rows:
        output.append(f'\x1b[{y+1};1H\x1b[0m\x1b[2K')
        previous=None
        row=visible[y]
        end=min(screen.columns,max(getattr(row,'text_end',0),max((x+1 for x,char in row.items() if char.bg!='default'),default=0)))
        for x in range(end):
            char=row[x]
            if not char.data: continue # wide character's second cell
            current=style(char)
            if current!=previous: output.append(current); previous=current
            output.append(char.data)
    marker=f'History -{screen.scroll_offset} | ' if screen.scroll_offset else ''
    footer=(marker+(session_status+' | ' if session_status else '')+FOOTER)[:max(0,columns-1)]
    output.append(f'\x1b[{physical_lines};1H\x1b[0;1;7;92m\x1b[2K'+footer+'\x1b[0m')
    output.append(f'\x1b[{min(screen.cursor.y,screen.lines-1)+1};{min(screen.cursor.x,columns-1)+1}H')
    output.append('\x1b[?7h')
    if not screen.cursor.hidden and not screen.scroll_offset: output.append('\x1b[?25h')
    output.append('\x1b[?1h' if 32 in screen.mode else '\x1b[?1l')
    output.append('\x1b[?2004h' if (2004<<5) in screen.mode else '\x1b[?2004l')
    screen.dirty.clear()
    return ''.join(output).encode('utf-8')
