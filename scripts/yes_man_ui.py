"""Keyboard-operated Yes Man chat for the desktop navigator and SSH TUI."""
import curses
import os
import signal
from pathlib import Path
from functools import lru_cache
import threading
import re
import yes_man
from yes_man_request import RequestContext, RequestCancelled
from navigator_input import read_key
from text_entry import TextField, draw_box, cursor, cells


# A separate GUI exit signal avoids relying solely on bytes queued in VTE.
_exit_requested=threading.Event()
_exit_handler_installed=False


def install_exit_handler():
    global _exit_handler_installed
    if not _exit_handler_installed:
        signal.signal(signal.SIGUSR1,lambda *_: _exit_requested.set())
        _exit_handler_installed=True
    _exit_requested.clear()


def secret(nav):
    field=TextField(); cursor(True)
    try:
        while True:
            nav.draw('YES MAN // API KEY',[],detail='Enter a replacement key. Empty clears it. Esc keeps the saved key.')
            masked=TextField('*'*len(field.value)); masked.position=field.position
            draw_box(nav.screen,masked)
            key=read_key(nav.screen)
            if key in ('\n','\r',curses.KEY_ENTER): return field.value
            if key=='\x1b': return None
            field.edit(key)
    finally: cursor(False)


def configure(nav):
    config=yes_man.settings()
    while True:
        choice=nav.menu('YES MAN // SERVER'+(' // '+yes_man.active_profile() if yes_man.active_profile() else ''),[
            'Server type: '+config['protocol'],'Server address: '+config['url'],
            'Model: '+(config['model'] or '(required)'),
            'API key: '+('Saved' if config['api_key'] else 'None'), 'Save','Test connection','Verify TLS certificate: '+('On' if config['verify_tls'] else 'Off'),'Save as profile','Select profile','Web search: '+('On' if config['search_enabled'] else 'Off'),'SearXNG address: '+(config['search_url'] or '(not configured)'),'Cancel'],
            detail=nav.message or 'Use your LLM API address. Localhost refers to the machine running Fallout.')
        if choice is None or choice==11: return
        if choice==0:
            kind=nav.menu('SERVER TYPE',['OpenAI compatible','Ollama','Cancel'])
            if kind in (0,1):
                config['protocol']=('OpenAI compatible','Ollama')[kind]
                if config['url'] in (yes_man.DEFAULT['url'],'http://localhost:11434'):
                    config['url']='http://localhost:11434' if kind==1 else yes_man.DEFAULT['url']
        elif choice in (1,2,3):
            field=('url','model','api_key')[choice-1]
            value=secret(nav) if choice==3 else nav.text('YES MAN // '+field.upper(),config[field])
            if value is not None: config[field]=value
        elif choice==4:
            try:
                if config!=yes_man.settings(): nav.yes_man_messages=[]
                yes_man.save(config); nav.message='Yes Man server saved.'; return
            except ValueError as error: nav.message=str(error)
        elif choice==5: test_connection(nav,config)
        elif choice==6: config['verify_tls']=not config['verify_tls']
        elif choice==9: config['search_enabled']=not config['search_enabled']
        elif choice==10:
            value=nav.text('SEARXNG SERVER ADDRESS',config['search_url'])
            if value is not None: config['search_url']=value
        elif choice==7:
            name=nav.text('SAVE LLM PROFILE AS')
            if name is None: continue
            try:
                overwrite=name.strip() in yes_man.profiles()
                if overwrite and nav.menu('REPLACE PROFILE // '+name.strip(),['Cancel','Replace'])!=1: continue
                yes_man.save_profile(name,config,overwrite=overwrite)
                nav.yes_man_messages=[]
                nav.message='Profile saved and selected: '+name.strip()
            except (OSError,ValueError) as error: nav.message=str(error)
        elif choice==8:
            try:
                names=yes_man.profiles()
                if not names: nav.message='No saved profiles. Use Save as profile first.'; continue
                selected=nav.menu('SELECT LLM PROFILE',names+['Cancel'])
                if selected is None or selected==len(names): continue
                config=yes_man.select_profile(names[selected])
                nav.yes_man_messages=[]
                nav.message='Active profile saved: '+names[selected]
            except (OSError,ValueError) as error: nav.message=str(error)



def test_connection(nav,config):
    try: config=yes_man.validate(config)
    except ValueError as error:
        nav.message=str(error); return
    done=threading.Event(); errors=[]
    def work():
        try: yes_man.reply(dict(config,search_enabled=False),[{'role':'user','content':'Connection test. Reply with OK.'}])
        except Exception as error: errors.append(error)
        finally: done.set()
    threading.Thread(target=work,daemon=True).start()
    nav.screen.timeout(100)
    frame=0
    try:
        while not done.is_set():
            nav.draw('YES MAN // TEST CONNECTION',
                     ['Checking server and model'+'.'*(frame%3+1),yes_man.endpoint(config),config['model']],
                     detail='Sending a short test message. Esc returns to settings.',highlight=False)
            frame+=1
            try: key=read_key(nav.screen,100)
            except curses.error: continue
            if key=='\x1b':
                nav.message='Connection test dismissed.'; return
        nav.message=('Connection failed: '+str(errors[0])) if errors else 'Connection successful! Server and model replied.'
    finally: nav.screen.timeout(-1)


def run(nav):
    if not hasattr(nav,'yes_man_messages'): nav.yes_man_messages=[]
    while True:
        choice=nav.menu('YES MAN // PERSONAL ASSISTANT',['Chat','Configure LLM server','New conversation','Back'],
                        detail=nav.message or 'Yes Man is ready to help!')
        if choice is None or choice==3: return
        if choice==1: configure(nav)
        elif choice==2: nav.yes_man_messages=[]; nav.message='New conversation started.'
        else:
            chat(nav)
            return


def portrait(visible):
    if not os.environ.get('FALLOUT_EMBEDDED_SOCKET'): return False
    from embedded_client import request
    request('yes_man_portrait',visible=visible,timeout=2)
    return True


def wrap_chat_line(text,width):
    """Keep words together; split only words wider than the full panel."""
    width=max(1,width)
    lines=[]; current=''; spacing=''
    for token in re.findall(r'\s+|\S+',text):
        if token.isspace():
            spacing=token.expandtabs(4)
            continue
        gap=spacing if current else ''
        if current and cells(current+gap+token)>width:
            lines.append(current); current=''; gap=''
        current+=gap
        for char in token:
            if current and cells(current+char)>width:
                lines.append(current); current=''
            current+=char
        spacing=''
    lines.append(current)
    return lines


@lru_cache(maxsize=1)
def cli_portrait():
    lines=Path(__file__).resolve().parent.parent.joinpath('assets/yes-man-cli.txt').read_text(encoding='utf-8').splitlines()
    lines=[''.join(char if char.isprintable() else ' ' for char in line).rstrip() for line in lines]
    while lines and not lines[0].strip(): lines.pop(0)
    while lines and not lines[-1].strip(): lines.pop()
    margin=min((len(line)-len(line.lstrip()) for line in lines if line.strip()),default=0)
    return tuple(line[margin:] for line in lines)


@lru_cache(maxsize=16)
def fit_cli_portrait(width,height):
    lines=cli_portrait()
    source_width=max((len(line) for line in lines),default=0)
    if not lines or not source_width or width<1 or height<1: return ()
    scale=min(1,width/source_width,height/len(lines))
    columns=max(1,int(source_width*scale)); rows=max(1,int(len(lines)*scale))
    padded=[line.ljust(source_width) for line in lines]
    return tuple(''.join(padded[min(len(lines)-1,int((y+.5)/scale))]
                              [min(source_width-1,int((x+.5)/scale))]
                         for x in range(columns)) for y in range(rows))


def chat_panel(nav,messages,field,offset,status,native):
    screen=nav.screen; height,width=screen.getmaxyx()
    left=int(width*.35) if width>=60 else 1
    right=width-2; top=4; bottom=height-4
    capacity=max(1,right-left-3); visible=max(1,bottom-top-5)
    nav.draw('YES MAN // CHAT',[],detail=status,refresh=False)
    attr=curses.color_pair(1)
    try:
        if curses.has_colors() and curses.can_change_color() and curses.COLORS>20:
            curses.init_color(20,25,90,40)
            curses.init_pair(2,curses.COLOR_GREEN,20)
            attr=curses.color_pair(2)
    except curses.error: pass
    def put(row,col,text,style=0):
        if row<0 or row>=height-1 or col<0 or col>=width-1: return
        try: screen.addnstr(row,col,text,max(1,width-col-1),attr|style)
        except curses.error: pass
    for row in range(top,bottom+1): put(row,left,' '*max(1,right-left+1))
    put(top,left,'┌'+'─'*max(1,right-left-1)+'┐')
    put(bottom,left,'└'+'─'*max(1,right-left-1)+'┘')
    for row in range(top+1,bottom):
        put(row,left,'│'); put(row,right,'│')
    put(bottom-3,left,'├'+'─'*max(1,right-left-1)+'┤')
    put(bottom-2,left+2,'MESSAGE',curses.A_BOLD)
    if not native and left>4:
        artwork=fit_cli_portrait(left-4,max(1,bottom-top-2))
        art_width=max((cells(line) for line in artwork),default=0)
        art_left=max(1,(left-art_width)//2)
        art_top=top+max(0,(bottom-top-len(artwork))//2)
        for row,line in enumerate(artwork,art_top): put(row,art_left,line)
    lines=[]
    for message in messages:
        lines.append('YOU' if message['role']=='user' else 'YES MAN')
        for line in message['content'].splitlines():
            lines.extend(wrap_chat_line(line,capacity))
        lines.append('')
    offset=max(0,min(offset,max(0,len(lines)-visible)))
    for row,line in enumerate(lines[offset:offset+visible],top+1): put(row,left+2,line)
    start=0
    while start<field.position and cells(field.value[start:field.position])>=capacity: start+=1
    shown=''
    for char in field.value[start:]:
        if cells(shown+char)>capacity: break
        shown+=char
    put(bottom-1,left+2,shown)
    try: screen.move(bottom-1,left+2+cells(field.value[start:field.position]))
    except curses.error: pass
    screen.refresh()
    return offset,visible


def chat(nav):
    config=yes_man.settings()
    try: yes_man.validate(config)
    except ValueError: configure(nav); return
    messages=nav.yes_man_messages; offset=10**9
    status='Enter: Send   ↑↓: Scroll   Esc: Back'
    field=TextField()
    task=None; result=[]; errors=[]; done=threading.Event()
    request_context=None
    install_exit_handler()
    native=portrait(True)
    nav.screen.timeout(100); cursor(True)
    try:
        while True:
            if _exit_requested.is_set(): return
            offset,visible=chat_panel(nav,messages,field,offset,status,native)
            if _exit_requested.is_set(): return
            if task and done.is_set():
                task=None
                if request_context.is_cancelled():
                    continue
                if errors:
                    status=str(errors[0])+'  Enter: Retry'
                    if not field.value: field.replace(pending['content'])
                else:
                    messages.append({'role':'assistant','content':result[0]})
                    offset=10**9; status='Enter: Send   ↑↓: Scroll   Esc: Back'
            try: key=read_key(nav.screen,100)
            except curses.error: continue
            if key in ('\x1b','\x1d'): return
            if key in (curses.KEY_UP,curses.KEY_PPAGE): offset=max(0,offset-(visible if key==curses.KEY_PPAGE else 1))
            elif key in (curses.KEY_DOWN,curses.KEY_NPAGE): offset+=visible if key==curses.KEY_NPAGE else 1
            elif key in ('\n','\r',curses.KEY_ENTER) and task is None:
                value=field.value.strip()
                if not value: continue
                field.replace('')
                pending={'role':'user','content':value}; result=[]; errors=[]; done=threading.Event()
                request_context=RequestContext()
                # Replace a failed pending message only when explicitly retrying it.
                if messages and messages[-1]['role']=='user': messages.pop()
                messages.append(pending)
                snapshot=list(messages)
                offset=10**9
                # Bind task state so leaving this screen never changes another request.
                def work(config=config,messages=snapshot,result=result,errors=errors,done=done,
                         context=request_context):
                    try:
                        context.raise_if_cancelled()
                        response=yes_man.reply(config,messages,context=context)
                        context.raise_if_cancelled()
                        result.append(response)
                    except RequestCancelled:
                        pass
                    except Exception as error:
                        if not context.is_cancelled(): errors.append(error)
                    finally: done.set()
                task=threading.Thread(target=work,daemon=True); task.start()
                status='Yes Man is thinking…  You can type your next message.'
            else: field.edit(key)
    finally:
        if request_context is not None: request_context.cancel()
        cursor(False)
        try: portrait(False)
        finally:
            nav.screen.timeout(-1)
            nav.screen.clear()
            nav.screen.refresh()
