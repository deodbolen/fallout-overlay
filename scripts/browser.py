#!/usr/bin/env python3
"""Keyboard directory tree for the RobCo drop-down terminal."""
import curses
from datetime import datetime
from digital_clock import clock_lines
import os
from pathlib import Path
import subprocess

from navigator_tree import Tree

from ssh_manager import Catalog, username, generate_path, remote_directory
from terminal_sessions import Sessions
from path_completion import directory_matches, complete_directory
import crt_settings
import sound_settings
from section_transition import animate as animate_section
from file_actions import source_file, new_name, destination, copy_file, move_file, compress_file, file_info, create_entry
import configparser
import shutil
import shlex
import mimetypes

ENTER = ('\n','\r',curses.KEY_ENTER)

class SectionChanged(Exception):
    """Leave a submenu when the user switches the top-level section."""
    pass

class Navigator:
    def __init__(self,screen):
        self.screen=screen
        self.tree=Tree(Path.home())
        self.catalog=Catalog()
        if os.environ.get('FALLOUT_EMBEDDED_SOCKET'):
            from embedded_client import Sessions as EmbeddedSessions
            self.sessions=EmbeddedSessions()
        else: self.sessions=Sessions()
        self.section=0
        self.sections=['HOME','DATA','SSH','TERMINAL','APPLICATIONS','⚙️']
        self.page='ssh'
        self.selected={}
        self.message=''
        self.apps=None
        self.transition_pending=False

    def sound(self,event):
        if os.environ.get('FALLOUT_EMBEDDED_SOCKET'):
            from embedded_client import request
            request('sound',event=event)

    def navigation_sound(self,key):
        if key in (curses.KEY_UP,curses.KEY_DOWN): self.sound('focus')
        elif key in ENTER: self.sound('ok')
        elif key=='\x1b': self.sound('cancel')

    def switch_section(self,key):
        if key not in (curses.KEY_LEFT,curses.KEY_RIGHT): return False
        step=1 if key==curses.KEY_RIGHT else -1
        self.section=(self.section+step)%len(self.sections)
        self.sound('static'); self.sound('select')
        self.transition_pending=True
        return True

    def menu_key(self):
        key=self.screen.get_wch()
        self.navigation_sound(key)
        if self.switch_section(key): raise SectionChanged()
        return key

    def put(self,y,text,attr=0):
        h,w=self.screen.getmaxyx()
        if 0<=y<h and w>1:
            text=''.join(c if c.isprintable() else '?' for c in str(text))
            try: self.screen.addnstr(y,0,text,w-1,attr)
            except curses.error: pass

    def draw(self,title,labels,selected=0,footer='←→ SECTION  ↑↓ ITEM  ENTER OPEN  ESC BACK',detail='',refresh=True):
        h,w=self.screen.getmaxyx(); self.screen.erase()
        tabs='   '.join(('[  '+s+'  ]' if s=='⚙️' else '['+s+']') if i==self.section else s for i,s in enumerate(self.sections))
        self.put(0,'ROBCO TERMLINK // '+tabs,curses.A_BOLD)
        self.put(1,title,curses.A_BOLD)
        visible=max(1,h-6); offset=max(0,selected-visible+1)
        for index,label in enumerate(labels[offset:offset+visible],offset):
            self.put(3+index-offset,label,curses.A_REVERSE if index==selected else 0)
        self.put(h-2,detail or self.message)
        self.put(h-1,footer)
        if refresh: self.screen.refresh()

    def draw_clock(self):
        now=datetime.now()
        # Present the frame only after the digits are drawn, avoiding a blank flash.
        self.draw('LOCAL TIME',[],footer='←→ CHANGE SECTION  Q EXIT',detail=' ',refresh=False)
        h,w=self.screen.getmaxyx()
        lines=clock_lines(now.strftime('%H:%M'),max(1,w-5),max(1,h-7))
        top=3+max(0,(h-7-len(lines))//2)
        for offset,line in enumerate(lines):
            left=max(0,(w-1-len(line))//2-2)
            self.put(top+offset,' '*left+line)
        date=now.strftime('%A, %B %d, %Y')
        self.put(h-2,date.center(max(1,w-1)))
        self.screen.refresh()

    def menu(self,title,options,detail=''):
        index=0
        while True:
            self.draw(title,options,index,detail=detail)
            key=self.menu_key()
            if key in (curses.KEY_UP,'k'): index=max(0,index-1)
            elif key in (curses.KEY_DOWN,'j'): index=min(len(options)-1,index+1)
            elif key in ENTER: return index
            elif key in ('\x1b','q'): return None

    def text(self,label,initial='',directory_base=None):
        value=initial
        selected=0; explicit=False
        curses.curs_set(1)
        try:
            while True:
                matches=directory_matches(value,directory_base) if directory_base is not None else []
                if directory_base is not None:
                    selected=min(selected,max(0,len(matches)-1))
                    limit=max(1,self.screen.getmaxyx()[0]-8)
                    start=max(0,selected-limit+1)
                    labels=[value,'Available directories:']+[entry for entry in matches[start:start+limit]]
                    if not matches: labels.append('(no matching directories)')
                    self.draw(label,labels,selected-start+2 if matches else 0,footer='TAB COMPLETE  ↑↓ CHOOSE  ENTER ACCEPT  CTRL+U CLEAR  ESC CANCEL')
                    h,w=self.screen.getmaxyx()
                    if h>3 and w>1: self.screen.move(3,min(len(value),w-2)); self.screen.refresh()
                else:
                    self.draw(label,[value],footer='TYPE VALUE  ENTER ACCEPT  ESC CANCEL')
                key=self.screen.get_wch()
                if key in ENTER: return value.strip()
                if key=='\x1b': return None
                if directory_base is not None and key in (curses.KEY_UP,curses.KEY_DOWN,curses.KEY_BTAB):
                    step=1 if key==curses.KEY_DOWN else -1
                    selected=max(0,min(len(matches)-1,selected+step)); explicit=True
                    continue
                if directory_base is not None and key=='\t':
                    value=complete_directory(value,matches,selected,explicit)
                    selected=0; explicit=False
                    continue
                selected=0; explicit=False
                if key in (curses.KEY_BACKSPACE,'\x7f','\b'): value=value[:-1]
                elif key=='\x15': value=''
                elif isinstance(key,str) and key.isprintable() and len(value)<512: value+=key
        finally: curses.curs_set(0)

    def host_form(self,host=None):
        current=dict(host or {'name':'','address':'','user':'','key':''})
        field=0
        while True:
            keys=self.catalog.read()['keys']
            keyname=next((k['name'] for k in keys if k['id']==current['key']),'None (password)')
            labels=['Common name: '+current['name'],'IP or FQDN: '+current['address'],'User: '+(current['user'] or '(logged-in user: '+username(current)+')'),'SSH key: '+keyname,'SAVE','CANCEL']
            self.draw('EDIT HOST' if host else '+ HOST',labels,field)
            key=self.menu_key()
            if key==curses.KEY_UP: field=max(0,field-1)
            elif key==curses.KEY_DOWN: field=min(5,field+1)
            elif key=='\x1b': return
            elif key in ENTER:
                if field<3:
                    name=('name','address','user')[field]
                    value=self.text(labels[field].split(':')[0],current[name])
                    if value is not None: current[name]=value
                elif field==3:
                    choice=self.menu('SSH KEY',['None (password)']+[k['name'] for k in keys]+['Cancel'])
                    if choice is not None and choice<=len(keys): current['key']='' if choice==0 else keys[choice-1]['id']
                elif field==4:
                    try:
                        self.catalog.save_host(current['name'],current['address'],current['user'],current['key'],current.get('id'))
                        self.message='Host saved.'; return
                    except ValueError as error: self.message=str(error)
                else: return

    def launch(self,action,label,**details):
        session=self.sessions.launch(action,label,**details)
        self.section=self.sections.index('TERMINAL')
        self.selected['terminal']=len(self.sessions.items) # + terminal row occupies index 0
        self.message='Ctrl+] returns to the navigator; the session stays running.'
        self.attach_session(session)

    def attach_session(self,session):
        def selected(current):
            self.selected['terminal']=self.sessions.items.index(current)+1
        self.sessions.attach(self.screen,session,selected)

    def choose_key(self):
        keys=self.catalog.read()['keys']
        if not keys:
            self.message='Generate a key under SSH > SSH-KEY first.'; return None
        choice=self.menu('SELECT SSH KEY',[k['name'] for k in keys]+['Cancel'])
        return keys[choice] if choice is not None and choice<len(keys) else None

    def push_form(self,host,key):
        directory='~/.ssh'; selected=0
        while True:
            self.draw('PUSH '+key['name']+' TO '+host['name'],['Remote directory: '+directory,'PUSH','CANCEL'],selected,detail='Only the public key is sent; authorized_keys is preserved.')
            pressed=self.menu_key()
            if pressed==curses.KEY_DOWN: selected=min(2,selected+1)
            elif pressed==curses.KEY_UP: selected=max(0,selected-1)
            elif pressed=='\x1b': return
            elif pressed in ENTER:
                if selected==0:
                    value=self.text('REMOTE SSH DIRECTORY',directory)
                    if value is not None: directory=value
                elif selected==1:
                    try:
                        directory=remote_directory(directory)
                        self.launch('push','Push '+key['name']+' > '+host['name'],host=host,key=key,directory=directory)
                        return
                    except ValueError as error: self.message=str(error)
                else: return

    def host_actions(self,host):
        choice=self.menu(host['name']+' // '+username(host)+'@'+host['address'],['Connect','Edit','Push new key','Cancel'])
        if choice==0:
            key=next((k for k in self.catalog.read()['keys'] if k['id']==host['key']),None)
            if host['key'] and not key:
                self.message='Saved key is missing. Edit the host or choose Push new key.'; return
            self.launch('connect',host['name'],host=host,key=key)
        elif choice==1: self.host_form(host)
        elif choice==2:
            key=self.choose_key()
            if key: self.push_form(host,key)

    def key_actions(self,key):
        choice=self.menu('SSH KEY // '+key['name'],['Push to host','Revoke','Cancel'])
        if choice==0:
            hosts=self.catalog.read()['hosts']
            if not hosts: self.message='Add a host first.'; return
            hostindex=self.menu('PUSH TO HOST',[h['name']+' // '+h['address'] for h in hosts]+['Cancel'])
            if hostindex is not None and hostindex<len(hosts): self.push_form(hosts[hostindex],key)
        elif choice==1:
            records=[r for r in self.catalog.read()['installed'] if r['key']==key['id']]
            if not records: self.message='No successful pushes are tracked for this key.'; return
            names=', '.join(r['host']['name'] for r in records)
            confirm=self.menu('REVOKE '+key['name'],['Revoke from all tracked hosts','Cancel'],detail=names+' // local key will be kept')
            if confirm==0: self.launch('revoke','Revoke '+key['name'],key=key,records=records)

    def applications(self):
        apps={}
        locations=[Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))]+[Path(p) for p in os.environ.get('XDG_DATA_DIRS','/usr/local/share:/usr/share').split(':')]
        for location in locations:
            for path in (location/'applications').glob('*.desktop'):
                if path.name in apps: continue
                cfg=configparser.ConfigParser(interpolation=None,strict=False)
                try:
                    cfg.read(path); item=cfg['Desktop Entry']
                    apps[path.name]=None
                    if item.get('Type')!='Application' or item.getboolean('Hidden',False) or item.getboolean('NoDisplay',False): continue
                    if item.get('TryExec') and not shutil.which(item['TryExec']): continue
                    apps[path.name]={'name':item.get('Name',path.stem),'path':str(path),'terminal':item.getboolean('Terminal',False),'exec':item.get('Exec','')}
                except (OSError,ValueError,KeyError,configparser.Error): continue
        return sorted((v for v in apps.values() if v),key=lambda a:a['name'].casefold())

    def rows(self):
        if self.sections[self.section]=='HOME':
            return 'clock','LOCAL TIME',[],[]
        if self.sections[self.section]=='DATA':
            rows=self.tree.rows()
            labels=[]
            for path,depth,directory in rows:
                marker=('[-]' if path in self.tree.expanded else '[+]') if directory else ' · '
                labels.append('  '*min(depth,20)+marker+' '+('HOME' if path==self.tree.root else path.name+('/' if directory else '')))
            return 'home','DIRECTORY TREE',labels,rows
        if self.sections[self.section]=='SSH':
            data=self.catalog.read()
            if self.page=='ssh': return 'ssh','SSH',['HOST','SSH-KEY'],[]
            if self.page=='hosts':
                hosts=sorted(data['hosts'],key=lambda h:h['name'].casefold())
                return 'hosts','HOST',['+ HOST']+[h['name']+' // '+username(h)+'@'+h['address'] for h in hosts],hosts
            if self.page=='keys': return 'keys','SSH-KEY',['Generate new key','Saved keys'],[]
            keys=sorted(data['keys'],key=lambda k:k['name'].casefold())
            return 'savedkeys','SAVED KEYS',[k['name'] for k in keys] or ['No saved keys'],keys
        if self.sections[self.section]=='TERMINAL':
            return 'terminal','TERMINAL // Ctrl+] detaches a live session',['+ Local terminal']+[s.label+' // '+s.status for s in self.sessions.items],self.sessions.items
        if self.sections[self.section]=='⚙️':
            status='Enabled' if crt_settings.running() and crt_settings.enabled() else 'Disabled'
            animation='Enabled' if crt_settings.running() and crt_settings.animation_enabled() else 'Disabled'
            return 'settings','⚙ SETTINGS',['CRT overlay: '+status,'CRT scan animation: '+animation,'Volume'],[]
        if self.apps is None: self.apps=self.applications()
        return 'apps','APPLICATIONS',[a['name'] for a in self.apps] or ['No applications'],self.apps

    def open_document(self,path):
        path=Path(path)
        mime=mimetypes.guess_type(str(path))[0] or ''
        sample=path.open('rb')
        with sample: data=sample.read(8192)
        text=mime.startswith('text/') or mime in ('application/json','application/xml','application/javascript')
        if not text and b'\0' not in data:
            try: data.decode('utf-8'); text=True
            except UnicodeDecodeError: pass
        if text:
            if not shutil.which('nano'): raise ValueError('Nano is not installed.')
            self.launch('editor','Nano: '+path.name,path=str(path),cwd=str(path.parent))
        else: self.open_gui(path)

    def hide_for_application(self):
        if os.environ.get('FALLOUT_EMBEDDED_SOCKET'):
            from embedded_client import request
            request('hide')

    def open_gui(self,path,application=None):
        path=Path(path).absolute()
        if application is not None:
            executable=Path(application).expanduser()
            if not executable.is_absolute():
                raise ValueError('Enter the full application executable path.')
            if not executable.is_file() or not os.access(executable,os.X_OK):
                raise ValueError('Select an existing executable application.')
            argv=[str(executable),str(path)]
        else: argv=['xdg-open',str(path)]
        subprocess.Popen(argv,cwd=str(path.parent),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.hide_for_application()
        self.message='Opened '+path.name+' with '+(Path(application).name if application else 'the default desktop application')+'.'

    def open_with(self,path):
        application=''
        while True:
            embedded=bool(os.environ.get('FALLOUT_EMBEDDED_SOCKET'))
            options=['Application path: '+(application or '(choose executable)')]
            if embedded: options.append('Browse…')
            options+=['Open','Cancel']
            choice=self.menu('OPEN WITH // '+path.name,options,detail=self.message or 'Choose the application executable, for example /usr/bin/mousepad.')
            if choice is None or choice==len(options)-1: return
            if choice==0:
                value=self.text('APPLICATION EXECUTABLE PATH',application)
                if value is not None: application=value
            elif embedded and choice==1:
                from embedded_client import request
                value=request('choose_application',initial=application).get('path')
                if value: application=value
            else:
                try:
                    self.open_gui(path,application)
                    return
                except (OSError,ValueError) as error: self.message=str(error)

    def new_entry(self,directory):
        choice=self.menu('NEW // '+directory.name,['Directory','File','Cancel'],detail=str(directory))
        if choice not in (0,1): return
        kind=('Directory','File')[choice]
        name=''; index=0
        while True:
            self.draw('NEW '+kind.upper(),['Name: '+name,'CREATE','CANCEL'],index,detail=self.message or 'Inside '+str(directory))
            key=self.menu_key()
            if key==curses.KEY_UP: index=max(0,index-1)
            elif key==curses.KEY_DOWN: index=min(2,index+1)
            elif key=='\x1b': return
            elif key in ENTER:
                if index==0:
                    value=self.text('NAME FOR NEW '+kind.upper(),name)
                    if value is not None:
                        name=value; index=1
                elif index==1:
                    try:
                        path=create_entry(directory,name,kind)
                        self.tree.expanded.add(directory)
                        if name.startswith('.'): self.tree.hidden=True
                        rows=self.tree.rows()
                        self.selected['home']=next((i for i,row in enumerate(rows) if row[0]==path),0)
                        self.message='Created '+kind.lower()+': '+str(path)
                        return
                    except (OSError,ValueError) as error: self.message=str(error)
                else: return

    def file_destination(self,path,operation):
        directory=str(Path.home())+'/'; index=0
        while True:
            self.draw(operation.upper()+' // '+path.name,['Destination directory: '+directory,operation.upper(),'CANCEL'],index,detail=self.message or 'Existing files are never overwritten. Relative paths start at the source directory.')
            key=self.menu_key()
            if key==curses.KEY_UP: index=max(0,index-1)
            elif key==curses.KEY_DOWN: index=min(2,index+1)
            elif key=='\x1b': return
            elif key in ENTER:
                if index==0:
                    value=self.text('DESTINATION DIRECTORY',directory,directory_base=path.parent)
                    if value is not None: directory=value
                elif index==1:
                    try:
                        target=destination(path,directory)
                        self.draw(operation.upper()+' // '+path.name,['Working…'],detail=str(target))
                        if operation=='Copy': copy_file(path,target)
                        else: move_file(path,target)
                        self.message=operation+' complete: '+str(target)
                        return
                    except (OSError,ValueError) as error: self.message=str(error)
                else: return

    def file_actions(self,path):
        source_file(path)
        choice=self.menu('FILE // '+path.name,['Rename','Copy','Move','SCP (coming later)','Delete','Compress','File info','Open','Open GUI','Open with >','Cancel'],detail=str(path))
        if choice==0:
            name=self.text('RENAME // '+path.name,path.name)
            if name is not None:
                target=move_file(path,new_name(path,name))
                rows=self.tree.rows()
                self.selected['home']=next((i for i,row in enumerate(rows) if row[0]==target),self.selected.get('home',0))
                self.message='Renamed to '+target.name
        elif choice in (1,2): self.file_destination(path,'Copy' if choice==1 else 'Move')
        elif choice==3: self.message='SCP is reserved for the next update; no transfer was started.'
        elif choice==4:
            if self.menu('DELETE // '+path.name,['Move to Trash','Cancel'],detail=str(path))==0:
                result=subprocess.run(['gio','trash','--',str(path)],capture_output=True,text=True)
                if result.returncode: raise ValueError(result.stderr.strip() or 'Could not move the file to Trash.')
                self.message='Moved to Trash: '+path.name
        elif choice==5:
            archive=compress_file(path); self.message='Created '+archive.name
        elif choice==6:
            self.menu('FILE INFO',file_info(path)+['Close'],detail='Enter or Esc to close.')
        elif choice==7: self.open_document(path)
        elif choice==8: self.open_gui(path)
        elif choice==9: self.open_with(path)

    def volume_settings(self):
        index=0
        fields=['effects_volume','fan_volume']
        while True:
            levels=sound_settings.levels()
            labels=['Sound effects: '+str(levels['effects_volume'])+'%','Fan hum: '+str(levels['fan_volume'])+'%','Back']
            self.draw('VOLUME',labels,index,'↑↓ SELECT  +/- ADJUST  ENTER SET LEVEL  ESC BACK',self.message or '0% mutes. Changes save and apply immediately.')
            key=self.menu_key()
            if key==curses.KEY_UP: index=max(0,index-1)
            elif key==curses.KEY_DOWN: index=min(2,index+1)
            elif key in ('\x1b',curses.KEY_BACKSPACE,'\x7f'): return
            elif key in ('+','=', '-') and index<2:
                field=fields[index]
                sound_settings.save(field,max(0,min(100,levels[field]+(5 if key in ('+','=') else -5))))
            elif key in ENTER:
                if index==2: return
                field=fields[index]
                value=self.text('VOLUME 0–100 (%)',str(levels[field]))
                if value is not None:
                    try:
                        sound_settings.save(field,value)
                        self.message='Volume saved.'
                    except (ValueError,TypeError): self.message='Enter a number from 0 to 100.'

    def activate(self,page,index,items):
        if page=='home':
            path,depth,directory=items[index]
            if directory:
                if path in self.tree.expanded: self.tree.expanded.remove(path)
                else: self.tree.expanded.add(path)
            else: self.open_document(path)
        elif page=='ssh': self.page='hosts' if index==0 else 'keys'
        elif page=='hosts':
            if index==0: self.host_form()
            else: self.host_actions(items[index-1])
        elif page=='keys':
            if index==0:
                name=self.text('NEW KEY NAME')
                if name:
                    generate_path(name)
                    self.launch('generate','Generate '+name,name=name)
            else: self.page='savedkeys'
        elif page=='savedkeys':
            if items: self.key_actions(items[index])
        elif page=='terminal':
            if index==0: self.launch('shell','Local terminal',cwd=str(Path.home()))
            else:
                session=items[index-1]
                if session.status=='closed':
                    if self.menu(session.label,['Remove from list','Cancel'])==0:
                        session.close(); self.sessions.items.remove(session)
                else: self.attach_session(session)
        elif page=='settings':
            if index==2:
                self.volume_settings(); return
            label='CRT OVERLAY' if index==0 else 'CRT SCAN ANIMATION'
            detail='Faint static scanlines.' if index==0 else 'Five faint phosphor scan lines; one sweep every 12 seconds.'
            choice=self.menu(label,['Enable','Disable','Cancel'],detail=detail+' Clicks pass through.')
            if choice in (0,1):
                toggle=crt_settings.set_enabled if index==0 else crt_settings.set_animation
                toggle(choice==0)
                self.message=label+' '+('enabled.' if choice==0 else 'disabled.')
        elif page=='apps' and items:
            app=items[index]
            if app['terminal']:
                args=[]
                for token in shlex.split(app['exec']):
                    if token in ('%f','%F','%u','%U','%i'): continue
                    args.append(token.replace('%c',app['name']).replace('%k',app['path']).replace('%%','%'))
                if args: self.launch('command',app['name'],argv=args)
            else:
                subprocess.Popen(['gio','launch',app['path']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                self.hide_for_application()

    def run(self):
        self.screen.timeout(300)
        try:
            while True:
                try:
                    page,title,labels,items=self.rows()
                    index=max(0,min(self.selected.get(page,0),len(labels)-1))
                    self.selected[page]=index
                    detail=(self.message or str(items[index][0])) if page=='home' else self.message
                    footer='←→ SECTION  ↑↓ ITEM  ENTER OPEN  CTRL+M MENU  CTRL+N NEW  O OPEN / SHELL  Q EXIT' if page=='home' else '←→ CHANGE SECTION  ↑↓ SELECT ITEM  ENTER OPEN  BACKSPACE BACK  Q EXIT'
                    redraw=self.draw_clock if page=='clock' else lambda: self.draw(title,labels,index,footer,detail)
                    if self.transition_pending:
                        self.transition_pending=False
                        animate_section(self.screen,redraw)
                    else:
                        redraw()
                    try: key=self.screen.get_wch()
                    except curses.error: continue
                    self.message=''
                    self.navigation_sound(key)
                    if self.switch_section(key): pass
                    elif key in (curses.KEY_DOWN,'j'): self.selected[page]=min(len(labels)-1,index+1)
                    elif key in (curses.KEY_UP,'k'): self.selected[page]=max(0,index-1)
                    elif key==curses.KEY_NPAGE: self.selected[page]=min(len(labels)-1,index+max(1,self.screen.getmaxyx()[0]-6))
                    elif key==curses.KEY_PPAGE: self.selected[page]=max(0,index-max(1,self.screen.getmaxyx()[0]-6))
                    elif key in ENTER:
                        self.screen.timeout(-1)
                        try: self.activate(page,index,items)
                        finally: self.screen.timeout(300)
                    elif key in (curses.KEY_BACKSPACE,'\x7f','\x1b'):
                        if page=='home':
                            path=items[index][0]
                            if path in self.tree.expanded: self.tree.expanded.remove(path)
                            else: self.selected[page]=next((i for i,r in enumerate(items) if r[0]==path.parent),0)
                        elif page=='savedkeys': self.page='keys'
                        elif page in ('hosts','keys'): self.page='ssh'
                    elif key=='\x0e' and page=='home':
                        if items[index][2]:
                            self.screen.timeout(-1)
                            try: self.new_entry(items[index][0])
                            finally: self.screen.timeout(300)
                        else: self.message='Highlight a directory, then press Ctrl+N.'
                    elif key in ('o','O') and page=='home':
                        path,_,directory=items[index]
                        if directory: self.launch('shell','Local: '+path.name,cwd=str(path))
                        else: self.open_document(path)
                    elif key in ('m','M','\x0f') and page=='home' and not items[index][2]:
                        self.screen.timeout(-1)
                        try: self.file_actions(items[index][0])
                        finally: self.screen.timeout(300)
                    elif key in ('h','H') and page=='home': self.tree.hidden=not self.tree.hidden
                    elif key in ('s','S') and page=='home':
                        path,_,directory=items[index]
                        self.launch('shell','Local: '+path.name,cwd=str(path if directory else path.parent))
                    elif key in ('q','Q'):
                        active=any(s.process.poll() is None for s in self.sessions.items)
                        self.screen.timeout(-1)
                        try:
                            if not active or self.menu('ACTIVE TERMINALS',['Close sessions and exit','Cancel'])==0: return
                        finally: self.screen.timeout(300)
                except SectionChanged:
                    self.screen.timeout(300)
                    self.message=''
                except (OSError,ValueError) as error:
                    self.message=str(error)
        finally: self.sessions.close()


def browser(screen):
    curses.curs_set(0); screen.keypad(True)
    if curses.has_colors():
        curses.start_color(); curses.use_default_colors(); curses.init_pair(1,curses.COLOR_GREEN,-1)
        screen.bkgd(' ',curses.color_pair(1))
    Navigator(screen).run()

if __name__=='__main__':
    try: curses.wrapper(browser)
    except KeyboardInterrupt: pass
