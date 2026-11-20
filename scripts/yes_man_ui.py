"""Keyboard-operated Yes Man chat for the desktop navigator and SSH TUI."""
import curses
import os
import signal
from pathlib import Path
from functools import lru_cache
import threading
import re
import shlex
import uuid
import yes_man
import yes_man_tool_settings
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


def secret(nav,label='LLM CONNECTION // API KEY',detail='Enter a replacement key. Empty clears it. Esc keeps the saved key.'):
    field=TextField(); cursor(True)
    try:
        while True:
            nav.draw(label,[],detail=detail)
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
        choice=nav.menu('SETTINGS // LLM CONNECTIONS'+(' // '+yes_man.active_profile() if yes_man.active_profile() else ''),[
            'Server type: '+config['protocol'],'Server address: '+config['url'],
            'Model: '+(config['model'] or '(required)'),
            'API key: '+('Saved' if config['api_key'] else 'None'), 'Save','Test connection','Verify TLS certificate: '+('On' if config['verify_tls'] else 'Off'),'Save as profile','Select profile','Cancel'],
            detail=nav.message or 'Use your LLM API address. Localhost refers to the machine running Fallout.')
        if choice is None or choice==9: return
        if choice==0:
            kind=nav.menu('SERVER TYPE',['OpenAI compatible','Ollama','Cancel'])
            if kind in (0,1):
                config['protocol']=('OpenAI compatible','Ollama')[kind]
                if config['url'] in (yes_man.DEFAULT['url'],'http://localhost:11434'):
                    config['url']='http://localhost:11434' if kind==1 else yes_man.DEFAULT['url']
        elif choice in (1,2,3):
            field=('url','model','api_key')[choice-1]
            value=secret(nav) if choice==3 else nav.text('LLM CONNECTION // '+field.upper(),config[field])
            if value is not None: config[field]=value
        elif choice==4:
            try:
                if config!=yes_man.settings(): nav.yes_man_messages=[]
                yes_man.save(config); nav.message='LLM connection saved.'; return
            except ValueError as error: nav.message=str(error)
        elif choice==5: test_connection(nav,config)
        elif choice==6: config['verify_tls']=not config['verify_tls']
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
            selected=select_profile(nav)
            if selected is not None: config=selected


def select_profile(nav):
    try:
        names=yes_man.profiles()
        if not names:
            nav.message='No profiles saved. Use Settings > LLM Connections first.'; return None
        selected=nav.menu('SELECT LLM PROFILE',names+['Cancel'])
        if selected is None or selected==len(names): return None
        config=yes_man.select_profile(names[selected])
        nav.yes_man_messages=[]
        nav.message='Active profile saved: '+names[selected]
        return config
    except (OSError,ValueError) as error:
        nav.message=str(error)
        return None


def configure_tools(nav):
    config=yes_man_tool_settings.settings()
    while True:
        choice=nav.menu('SETTINGS // TOOLS // WEB SEARCH',[
            'Web search: '+('On' if config['search_enabled'] else 'Off'),
            'SearXNG address: '+(config['search_url'] or '(not configured)'), 'Save','Cancel'],
            detail=nav.message or 'Shared by all LLM profiles.')
        if choice is None or choice==3: return
        if choice==0: config['search_enabled']=not config['search_enabled']
        elif choice==1:
            value=nav.text('SEARXNG SERVER ADDRESS',config['search_url'])
            if value is not None: config['search_url']=value
        elif choice==2:
            try:
                yes_man_tool_settings.save(config)
                nav.yes_man_messages=[]
                nav.message='Web-search settings saved for all LLM profiles.'
                return
            except (OSError,ValueError) as error: nav.message=str(error)


def mcp_servers_panel(nav):
    from mcp_servers import load, validate_server
    native=bool(os.environ.get('FALLOUT_EMBEDDED_SOCKET'))
    def refresh_servers():
        labels=['+ Add Server'] if native else []
        identifiers=[None] if native else []
        try:
            servers=[validate_server(server) for server in load()['servers']]
            if not servers:
                labels.append('No MCP servers configured.'); identifiers.append(None)
            for server in servers:
                # Explicit allowlist: never render whole records or exception text.
                labels.append(server['name']+' // '+server['transport']+' // '+
                              ('Enabled' if server['enabled'] else 'Disabled'))
                identifiers.append(server['id'])
        except (OSError,ValueError,TypeError,KeyError,RecursionError):
            labels.append('Unable to read MCP server configuration.'); identifiers.append(None)
        return labels,identifiers
    labels,identifiers=refresh_servers()
    selected=0
    while True:
        visible=max(1,nav.screen.getmaxyx()[0]-7)
        limit=len(labels)-1 if native else max(0,len(labels)-visible)
        selected=max(0,min(selected,limit))
        nav.draw('MCP Servers',labels,selected,highlight=native,
                 detail='Configure external MCP servers and manage their tools.')
        key=nav.menu_key()
        if key in ('\x1b','\x7f',curses.KEY_BACKSPACE,'q','Q'): return
        if key in ('\n','\r',curses.KEY_ENTER):
            if native and selected==0:
                added=add_mcp_server_form(nav)
                if added is not None:
                    labels,identifiers=refresh_servers()
                    selected=next((index for index,identifier in enumerate(identifiers)
                                   if identifier==added['id']),0)
            elif native and identifiers[selected] is not None:
                changed=mcp_server_actions(nav,identifiers[selected])
                if changed is not None:
                    labels,identifiers=refresh_servers()
                    selected=next((index for index,identifier in enumerate(identifiers)
                                   if identifier==changed['id']),0)
            elif not native: return
        elif key in (curses.KEY_DOWN,'j'): selected+=1
        elif key in (curses.KEY_UP,'k'): selected-=1
        elif key==curses.KEY_NPAGE: selected+=visible
        elif key==curses.KEY_PPAGE: selected-=visible
        elif key==curses.KEY_HOME: selected=0
        elif key==curses.KEY_END: selected=limit


def add_mcp_server_form(nav,server=None):
    """Add or edit saved connection settings without connecting to a server."""
    from mcp_servers import add_server, update_server, validate_server
    original=validate_server(server) if server is not None else None
    draft={'name':'','transport':'streamable-http','url':'','bearer_token':'',
           'command':'','arguments':''}
    if original is not None:
        draft.update(name=original['name'],transport=original['transport'],
                     url=original.get('url',''),command=original.get('command',''),
                     arguments=shlex.join(original.get('args',[])))
    selected=0
    server_id=original['id'] if original is not None else uuid.uuid4().hex
    error=''
    try:
        while True:
            http=draft['transport']=='streamable-http'
            fields=('name','transport','url','bearer_token') if http else ('name','transport','command','arguments')
            labels=['Server name: '+draft['name'],
                    'Transport type: '+('Streamable HTTP' if http else 'stdio')]
            if http:
                labels+=['Endpoint URL: '+draft['url'],
                         'Bearer token: '+('[replacement set]' if draft['bearer_token'] else
                           '(saved; leave blank to retain)' if original and original.get('bearer_token') else '(optional)')]
            else:
                labels+=['Executable command: '+draft['command'],'Arguments: '+draft['arguments']]
            can_add=bool(draft['name'].strip() and draft['url' if http else 'command'].strip())
            selectable=(0,1,2,3,4,5) if can_add else (0,1,2,3,5)
            if selected not in selectable: selected=5
            action='SAVE' if original is not None else 'ADD'
            labels+=[action if can_add else action+' (disabled)','CANCEL']
            nav.draw('EDIT MCP SERVER' if original is not None else 'ADD MCP SERVER',labels,selected,
                     detail=error or ('Connection changes disable the server and clear tool permissions.' if original is not None
                                      else 'New servers are saved disabled. No connection or tool permissions are granted.'))
            key=nav.menu_key()
            position=selectable.index(selected)
            if key in (curses.KEY_UP,'k'): selected=selectable[max(0,position-1)]
            elif key in (curses.KEY_DOWN,'j'): selected=selectable[min(len(selectable)-1,position+1)]
            elif key in ('\x1b','\x7f',curses.KEY_BACKSPACE): return
            elif key in ('\n','\r',curses.KEY_ENTER):
                if selected==5: return
                if selected==4:
                    record={'id':server_id,'name':draft['name'],'transport':draft['transport']}
                    if original is None: record.update(enabled=False,tool_permissions={})
                    if http:
                        record['url']=draft['url']
                        if draft['bearer_token']: record['bearer_token']=draft['bearer_token']
                        elif original and original['transport']=='streamable-http' and 'bearer_token' in original:
                            record['bearer_token']=original['bearer_token']
                    else:
                        try: arguments=shlex.split(draft['arguments'])
                        except ValueError:
                            error='Arguments have unmatched quotes. Use quotes around arguments containing spaces.'
                            continue
                        record.update(command=draft['command'],args=arguments)
                        if original is None: record['env']={}
                    try:
                        added=update_server(server_id,record) if original is not None else add_server(record)
                    except ValueError as failure:
                        # Configuration validators use fixed messages. Redact the
                        # entered token defensively; never show an I/O exception.
                        error=str(failure)
                        for token in (draft['bearer_token'],original.get('bearer_token','') if original else ''):
                            if token: error=error.replace(token,'[redacted]')
                        error=''.join(char for char in error if char.isprintable())[:300]
                        continue
                    except (OSError,TypeError,RecursionError):
                        error='Could not save MCP configuration. Check the configuration file, permissions, and disk space.'
                        continue
                    nav.message='MCP server saved. No connection established.'
                    return added
                error=''
                field=fields[selected]
                if field=='transport':
                    choice=nav.menu('MCP TRANSPORT',['Streamable HTTP','stdio','Cancel'])
                    if choice in (0,1): draft['transport']=('streamable-http','stdio')[choice]
                elif field=='bearer_token':
                    value=secret(nav,'MCP SERVER // BEARER TOKEN',
                                 detail='Leave blank to retain the saved token. Esc keeps the current draft.' if original and original.get('bearer_token')
                                 else 'Optional token. Empty clears the draft. Esc keeps the current draft.')
                    if value is not None: draft[field]=value
                else:
                    value=nav.text(labels[selected].split(':',1)[0].upper(),draft[field])
                    if value is not None: draft[field]=value
    finally:
        draft.clear()


def mcp_server_actions(nav,server_id):
    from mcp_servers import load, validate_server
    while True:
        try:
            server=next((validate_server(row) for row in load()['servers'] if row.get('id')==server_id),None)
            if server is None: raise ValueError
        except (OSError,ValueError,TypeError,AttributeError,KeyError,RecursionError):
            nav.message='Could not read the selected MCP server configuration.'
            return None
        choice=nav.menu('MCP SERVER // '+server['name'],['Edit Server','Test Connection','Discover Tools','Back'],detail=nav.message)
        if choice is None or choice==3: return None
        if choice==0:
            changed=add_mcp_server_form(nav,server)
            if changed is not None: return changed
        elif choice==1: test_mcp_connection(nav,server_id)
        elif choice==2: discover_mcp_tools(nav,server_id)


def discover_mcp_tools(nav,server_id):
    from mcp_servers import load, validate_server
    active=getattr(nav,'mcp_tool_discovery',None)
    if active and not active['done'].is_set():
        nav.message='MCP tool discovery is already running.'
        return
    try:
        server=next((validate_server(row) for row in load()['servers'] if row.get('id')==server_id),None)
        if server is None: raise ValueError
    except (OSError,ValueError,TypeError,AttributeError,KeyError,RecursionError):
        nav.message='Could not read the saved MCP server configuration.'
        return
    state={'done':threading.Event(),'result':None,'context':RequestContext()}
    nav.mcp_tool_discovery=state
    def work(server=server,state=state):
        try:
            from yes_man_mcp_test import run_discovery
            state['result']=run_discovery(server,context=state['context'])
        except Exception:
            state['result']={'ok':False,'error':'Could not complete MCP tool discovery.'}
        finally: state['done'].set()
    try: threading.Thread(target=work,daemon=True).start()
    except RuntimeError:
        state['done'].set()
        nav.message='Could not start MCP tool discovery.'
        return
    nav.screen.timeout(100)
    try:
        while not state['done'].is_set():
            nav.draw('DISCOVER MCP TOOLS',[server['name'],'Initializing and listing tools…'],
                     detail='Timeout: 20 seconds plus bounded cleanup. Esc: Cancel.',highlight=False)
            try: key=nav.menu_key()
            except curses.error: continue
            if key in ('\x1b','\x1d',curses.KEY_BACKSPACE,'\x7f'): return
        result=state['result']
        if state['context'].is_cancelled(): return
        if not result['ok']:
            lines=wrap_chat_line(result['error'],max(1,nav.screen.getmaxyx()[1]-2))
            nav.screen.timeout(-1)
            nav.menu('MCP DISCOVERY FAILED',lines+['Back'])
            return
        # Display only names/descriptions. Ignore permission-like fields supplied
        # by the server; grants come exclusively from saved local configuration.
        permissions=server.get('tool_permissions',{})
        secrets=[value for value in [server.get('bearer_token',''),*server.get('env',{}).values()] if value]
        def display(value):
            for secret_value in sorted(secrets,key=len,reverse=True):
                value=value.replace(secret_value,'[redacted]')
            return ''.join(char if char.isprintable() else ' ' for char in value)
        offset=0; selected=0
        nav.screen.timeout(-1)
        tools=result['tools']
        def permission_label(name):
            permission=permissions.get(name,{})
            if permission.get('enabled') is not True: return 'Disabled'
            return 'Always Allow' if permission.get('approval')=='always_allow' else 'Always Ask'
        while True:
            width=max(1,nav.screen.getmaxyx()[1]-2)
            lines=[]; headers=[]
            for tool in tools:
                heading=wrap_chat_line(display(tool['name'])+' // '+permission_label(tool['name']),width)
                headers.append((len(lines),len(heading)))
                lines.extend(heading)
                lines.extend(wrap_chat_line(display(tool['description']) or '(No description provided.)',width))
                lines.append('')
            if not lines: lines=['No tools returned by this MCP server.']
            visible=max(1,nav.screen.getmaxyx()[0]-7)
            offset=max(0,min(offset,max(0,len(lines)-visible)))
            nav.draw('MCP TOOLS // '+server['name'],lines,offset,highlight=False,refresh=False,
                     detail='Up/Down: select tool. Enter: permissions. Page Up/Down: scroll. Esc: Back.')
            if tools:
                start,count=headers[selected]
                for index in range(start,start+count):
                    if offset<=index<offset+visible:
                        nav.put(4+index-offset,lines[index],curses.A_REVERSE)
            nav.screen.refresh()
            key=nav.menu_key()
            if key in ('\x1b','\x1d','\x7f',curses.KEY_BACKSPACE,'q','Q'): return
            if key in ('\n','\r',curses.KEY_ENTER):
                if not tools: return
                saved=mcp_tool_permission_menu(nav,server,tools[selected],display)
                if saved is not None:
                    permissions[saved['tool_name']]={'enabled':saved['enabled'],'approval':saved['approval']}
            elif key in (curses.KEY_DOWN,'j') and tools:
                selected=min(len(tools)-1,selected+1); offset=headers[selected][0]
            elif key in (curses.KEY_UP,'k') and tools:
                selected=max(0,selected-1); offset=headers[selected][0]
            elif key==curses.KEY_NPAGE: offset+=visible
            elif key==curses.KEY_PPAGE: offset-=visible
            elif key==curses.KEY_HOME: selected=0; offset=0
            elif key==curses.KEY_END:
                selected=max(0,len(tools)-1); offset=headers[selected][0] if tools else 0
    finally:
        state['context'].cancel()
        nav.screen.timeout(-1)


def mcp_tool_permission_menu(nav,server,tool,display):
    from mcp_servers import load, validate_server, validate_tool_permission, set_tool_permission
    try:
        current=next((validate_server(row) for row in load()['servers'] if row.get('id')==server['id']),None)
        if current is None: raise ValueError
        identity_fields=('transport','url','bearer_token','command','args','env','cwd')
        if any(current.get(field)!=server.get(field) for field in identity_fields):
            nav.menu('MCP TOOL PERMISSIONS',['Server connection changed. Discover tools again.','Back'])
            return None
        permission=validate_tool_permission(dict(current['tool_permissions'].get(tool['name'],{}),tool_name=tool['name']))
    except (OSError,ValueError,TypeError,AttributeError,KeyError,RecursionError):
        nav.menu('MCP TOOL PERMISSIONS',['Could not read saved tool permissions.','Back'])
        return None
    configured=0 if not permission['enabled'] else 2 if permission['approval']=='always_allow' else 1
    selected=configured
    error=''
    states=('Disabled','Always Ask','Always Allow')
    while True:
        labels=[('[current] ' if index==configured else '          ')+label for index,label in enumerate(states)]+['Back']
        nav.draw('TOOL PERMISSION // '+display(tool['name']),labels,selected,
                 detail=error or 'Future execution only. This does not enable the server or run the tool.')
        key=nav.menu_key()
        if key in ('\x1b','\x1d','\x7f',curses.KEY_BACKSPACE,'q','Q'): return None
        if key in (curses.KEY_UP,'k'): selected=max(0,selected-1)
        elif key in (curses.KEY_DOWN,'j'): selected=min(3,selected+1)
        elif key in ('\n','\r',curses.KEY_ENTER):
            if selected==3: return None
            choice=validate_tool_permission({'tool_name':tool['name'],'enabled':selected!=0,
                                            'approval':'always_allow' if selected==2 else 'always_ask'})
            try:
                return set_tool_permission(server['id'],choice,expected_server=server)
            except ValueError:
                error='Could not save permissions. The configuration may have changed; rediscover if needed.'
            except (OSError,TypeError,KeyError,RecursionError):
                error='Could not save permissions. Check configuration access and disk space.'


def test_mcp_connection(nav,server_id):
    from mcp_servers import load, validate_server
    active=getattr(nav,'mcp_connection_test',None)
    if active and not active['done'].is_set():
        nav.message='An MCP connection test is already running.'
        return
    try:
        server=next((validate_server(row) for row in load()['servers'] if row.get('id')==server_id),None)
        if server is None: raise ValueError
    except (OSError,ValueError,TypeError,AttributeError,KeyError,RecursionError):
        nav.message='Could not read the saved MCP server configuration.'
        return
    state={'done':threading.Event(),'result':None}
    nav.mcp_connection_test=state
    def work(server=server,state=state):
        try:
            from yes_man_mcp_test import run_test
            state['result']=run_test(server)
        except Exception:
            state['result']={'ok':False,'error':'Could not complete the connection test.'}
        finally: state['done'].set()
    try: threading.Thread(target=work,daemon=True).start()
    except RuntimeError:
        state['done'].set()
        nav.message='Could not start the connection test.'
        return
    nav.screen.timeout(100)
    try:
        while not state['done'].is_set():
            nav.draw('MCP CONNECTION TEST',[server['name'],'Testing MCP initialization…'],
                     detail='Timeout: 20 seconds plus bounded cleanup. Esc: Back.',highlight=False)
            try: key=nav.menu_key()
            except curses.error: continue
            if key in ('\x1b','\x1d'): return
        result=state['result']
        if result['ok']:
            lines=[server['name'],'Connection successful.','Protocol: '+result['protocol']]
        else: lines=[server['name']]+wrap_chat_line(result['error'],max(1,nav.screen.getmaxyx()[1]-2))
    finally: nav.screen.timeout(-1)
    nav.menu('MCP CONNECTION TEST',lines+['Back'])


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
            nav.draw('LLM CONNECTION // TEST CONNECTION',
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
        choice=nav.menu('YES MAN // PERSONAL ASSISTANT',['Chat','New conversation','Select LLM profile','Back'],
                        detail=nav.message or 'Yes Man is ready to help!')
        if choice is None or choice==3: return
        if choice==1: nav.yes_man_messages=[]; nav.message='New conversation started.'
        elif choice==2: select_profile(nav)
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
    except ValueError:
        nav.message='Configure a connection under Settings > LLM Connections.'
        return
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
