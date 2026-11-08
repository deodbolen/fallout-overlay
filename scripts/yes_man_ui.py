"""Keyboard-operated Yes Man chat for the desktop navigator and SSH TUI."""
import curses
import threading
import textwrap
import yes_man
from navigator_input import read_key
from text_entry import TextField, draw_box, cursor


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
        choice=nav.menu('YES MAN // SERVER',[
            'Server type: '+config['protocol'],'Server address: '+config['url'],
            'Model: '+(config['model'] or '(required)'),
            'API key: '+('Saved' if config['api_key'] else 'None'), 'Save','Test connection','Cancel'],
            detail=nav.message or 'Use your LLM API address. Localhost refers to the machine running Fallout.')
        if choice is None or choice==6: return
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
            try: yes_man.save(config); nav.message='Yes Man server saved.'; return
            except ValueError as error: nav.message=str(error)
        elif choice==5: test_connection(nav,config)


def test_connection(nav,config):
    try: config=yes_man.validate(config)
    except ValueError as error:
        nav.message=str(error); return
    done=threading.Event(); errors=[]
    def work():
        try: yes_man.reply(config,[{'role':'user','content':'Connection test. Reply with OK.'}])
        except Exception as error: errors.append(error)
        finally: done.set()
    threading.Thread(target=work,daemon=True).start()
    delay=nav.screen.getdelay()
    nav.screen.timeout(100)
    frame=0
    try:
        while not done.is_set():
            nav.draw('YES MAN // TEST CONNECTION',
                     ['Checking server and model'+'.'*(frame%3+1),config['url'],config['model']],
                     detail='Sending a short test message. Esc returns to settings.',highlight=False)
            frame+=1
            try: key=read_key(nav.screen)
            except curses.error: continue
            if key=='\x1b':
                nav.message='Connection test dismissed.'; return
        nav.message=('Connection failed: '+str(errors[0])) if errors else 'Connection successful! Server and model replied.'
    finally: nav.screen.timeout(delay)


def run(nav):
    if not hasattr(nav,'yes_man_messages'): nav.yes_man_messages=[]
    while True:
        choice=nav.menu('YES MAN // PERSONAL ASSISTANT',['Chat','Configure LLM server','New conversation','Back'],
                        detail=nav.message or 'Yes Man is ready to help!')
        if choice is None or choice==3: return
        if choice==1: configure(nav)
        elif choice==2: nav.yes_man_messages=[]; nav.message='New conversation started.'
        else: chat(nav)


def chat(nav):
    config=yes_man.settings()
    try: yes_man.validate(config)
    except ValueError: configure(nav); return
    messages=nav.yes_man_messages; offset=0; status='N: New message   ↑↓: Scroll   Esc: Back'
    task=None; result=[]; errors=[]; done=threading.Event()
    nav.screen.timeout(100)
    try:
        while True:
            width=nav.screen.getmaxyx()[1]; visible=max(1,nav.screen.getmaxyx()[0]-6)
            lines=['          YES MAN', '        .----------.', '        |  ^    ^  |', '        |   \\__/   |', '        \'----------\'','']
            for message in messages:
                lines.append('YOU' if message['role']=='user' else 'YES MAN')
                for line in message['content'].splitlines():
                    lines.extend(textwrap.wrap(line,max(1,width-2),replace_whitespace=False,drop_whitespace=False) or [''])
                lines.append('')
            offset=max(0,min(offset,max(0,len(lines)-visible)))
            nav.draw('YES MAN // '+config['model'],lines,offset,detail=status,highlight=False)
            if task and done.is_set():
                task=None
                if errors: status=str(errors[0])+'  N: Retry / new message'
                else:
                    messages.extend([pending,{'role':'assistant','content':result[0]}])
                    offset=10**9; status='N: New message   ↑↓: Scroll   Esc: Back'
            try: key=read_key(nav.screen)
            except curses.error: continue
            if key=='\x1b': return
            if key in (curses.KEY_UP,curses.KEY_PPAGE): offset=max(0,offset-(visible if key==curses.KEY_PPAGE else 1))
            elif key in (curses.KEY_DOWN,curses.KEY_NPAGE): offset+=visible if key==curses.KEY_NPAGE else 1
            elif key in ('n','N','\n','\r') and task is None:
                nav.screen.timeout(-1)
                try: value=nav.text('MESSAGE TO YES MAN')
                finally: nav.screen.timeout(100)
                if not value: continue
                pending={'role':'user','content':value}; result=[]; errors=[]; done=threading.Event()
                snapshot=list(messages)+[pending]
                # Bind task state so leaving this screen never changes another request.
                def work(config=config,messages=snapshot,result=result,errors=errors,done=done):
                    try: result.append(yes_man.reply(config,messages))
                    except Exception as error: errors.append(error)
                    finally: done.set()
                task=threading.Thread(target=work,daemon=True); task.start()
                status='Yes Man is thinking…  Esc: Back'
    finally: nav.screen.timeout(-1)
