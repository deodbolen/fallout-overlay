#!/usr/bin/python3
"""Native GTK host: navigator and each session get their own VTE view and font."""
import json
import random
import time
import os
from pathlib import Path
import signal
import socket
import struct
import sys
import threading
import uuid
import fcntl
import cairo
import gi
ROOT=Path(__file__).resolve().parent.parent
# Bind to the VTE library already installed on Debian, with a project-local typelib.
gi.require_version('Gtk','3.0')
try:
    gi.require_version('Vte','2.91')
except ValueError:
    # Compatibility fallback for existing installs; new installs use Debian's matching typelib.
    gi.require_version('GIRepository','2.0')
    from gi.repository import GIRepository
    GIRepository.Repository.prepend_search_path(str(ROOT/'vendor/typelib'))
    gi.require_version('Vte','2.91')
gi.require_foreign('cairo')
from gi.repository import Gtk,Gdk,GLib,Vte,Pango,PangoCairo,GdkPixbuf
from ssh_manager import atomic_json,state_dir
from sounds import Sounds
import navigator_settings

NAV_FONT='DejaVu Sans Mono 16'
SHELL_FONT='DejaVu Sans Mono 14'
EDITOR_FONT='DejaVu Sans Mono 11'


def runtime():
    directory=Path(os.environ.get('XDG_RUNTIME_DIR',str(Path.home()/'.cache')))/'fallout-ui'
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    return directory


def color(value):
    result=Gdk.RGBA(); result.parse(value); return result

class Host:
    def __init__(self,path,listener):
        self.sounds=Sounds()
        self.path=path; self.listener=listener; self.records={}; self.current=None
        self.waiter=None; self.closed=False; self.nav_pid=None
        self.transparent=navigator_settings.transparent()
        self.window=Gtk.Window(title='ROBCO TERMLINK')
        visual=self.window.get_screen().get_rgba_visual()
        if visual: self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        self.window.connect('draw',self.clear_window)
        self.window.set_decorated(False); self.window.set_keep_above(True)
        self.window.connect('delete-event',self.delete)
        self.window.connect('destroy',lambda *args: Gtk.main_quit())
        self.window.maximize()
        self.box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.window.add(self.box)
        self.heading=Gtk.Label(); self.heading.set_xalign(0)
        self.heading.set_margin_start(8); self.heading.set_margin_top(4); self.heading.set_margin_bottom(4)
        self.box.pack_start(self.heading,False,False,0)
        overlay=Gtk.Overlay(); self.box.pack_start(overlay,True,True,0)
        self.background=Gtk.DrawingArea(); self.background.connect('draw',self.draw_background)
        overlay.add(self.background)
        self.pixbuf=GdkPixbuf.Pixbuf.new_from_file(str(ROOT/'assets/navigator-background.svg'))
        self.stack=Gtk.Stack(); self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        overlay.add_overlay(self.stack)
        self.static_until=0; self.static_timer=None
        self.footer=Gtk.Label(label='Ctrl+]  Navigator  |  Ctrl+↑/↓  Sessions  |  Ctrl+Shift+C  Copy  |  Ctrl+Shift+V  Paste')
        self.footer.set_xalign(0); self.footer.set_margin_start(8); self.footer.set_margin_end(8)
        self.footer.set_margin_top(4); self.footer.set_margin_bottom(4)
        self.footer.set_name('session-reminder')
        self.box.pack_end(self.footer,False,False,0)
        css=Gtk.CssProvider()
        css.load_from_data(b'window { background: transparent; color: #b6ffa3; } vte-terminal { background: transparent; } label { color: #b6ffa3; } #session-reminder { font-family: \"DejaVu Sans Mono\"; font-size: 11pt; }')
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.clock_value=''
        self.nav_font_size=navigator_settings.font_size()
        self.navigator=self.terminal('DejaVu Sans Mono '+str(self.nav_font_size))
        self.navigator.connect_after('draw',self.draw_clock)
        self.navigator.connect('key-press-event',self.nav_keys)
        self.navigator.connect('child-exited',self.nav_exited)
        self.stack.add_named(self.navigator,'navigator')
        env=dict(os.environ,FALLOUT_EMBEDDED_SOCKET=str(path),TERM='xterm-256color')
        self.spawn(self.navigator,[sys.executable,str(ROOT/'scripts/browser.py')],str(Path.home()),env,self.nav_spawned)
        self.window.show_all(); self.show_navigator(); self.sounds.play('load')
        threading.Thread(target=self.serve,daemon=True).start()
        GLib.timeout_add(250,self.refresh)

    def terminal(self,font):
        terminal=Vte.Terminal()
        terminal.set_clear_background(False)
        terminal.connect('draw',self.draw_background)
        terminal.connect_after('draw',self.draw_static)
        terminal.connect('button-press-event',self.terminal_menu)
        terminal.connect('key-press-event',self.typing_sound)
        terminal.set_font(Pango.FontDescription(font))
        terminal.set_color_foreground(color('#b6ffa3'))
        terminal.set_color_background(color('rgba(5,10,6,0)'))
        terminal.set_color_cursor(color('#9dff72'))
        palette='#09110b;#ff6b6b;#9dff72;#ffe478;#8ab4ff;#eda6ff;#89f5ee;#d7f5d0;#6a8c6b;#ff9393;#b6ffa3;#fff3a1;#b4ceff;#f6c5ff;#b6fff6;#f3fff0'
        terminal.set_colors(color('#b6ffa3'),color('rgba(5,10,6,0)'),[color(c) for c in palette.split(';')])
        terminal.set_scrollback_lines(10000); terminal.set_audible_bell(False)
        terminal.set_mouse_autohide(True)
        return terminal

    def clear_window(self,widget,context):
        context.save()
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0,0,0,0)
        context.paint(); context.restore()
        return False

    def draw_background(self,widget,context):
        if self.transparent and self.window.get_screen().is_composited(): return False
        size=widget.get_allocation()
        context.set_source_rgb(5/255,10/255,6/255); context.paint()
        context.save(); context.scale(size.width/self.pixbuf.get_width(),size.height/self.pixbuf.get_height())
        Gdk.cairo_set_source_pixbuf(context,self.pixbuf,0,0); context.paint(); context.restore()
        return False

    def draw_clock(self,widget,context):
        if not self.clock_value: return False
        size=widget.get_allocation()
        cell_w=max(1,widget.get_char_width()); cell_h=max(1,widget.get_char_height())
        columns=max(1,size.width//cell_w); rows=max(1,size.height//cell_h)
        # Match the first clock's five-row glyphs and original scaling limits.
        scale=max(1,min(max(1,rows-7)//5,columns//27//2))
        target_h=min(5*scale*cell_h,max(1,size.height-7*cell_h))
        layout=widget.create_pango_layout(self.clock_value)
        font=Pango.FontDescription('DejaVu Sans Book')
        font.set_absolute_size(100*Pango.SCALE)
        layout.set_font_description(font)
        ink,_=layout.get_pixel_extents()
        factor=min(target_h/max(1,ink.height),max(1,size.width-5*cell_w)/max(1,ink.width))
        font.set_absolute_size(100*factor*Pango.SCALE)
        layout.set_font_description(font)
        ink,_=layout.get_pixel_extents()
        x=max(0,(size.width-ink.width)/2-10*cell_w)-ink.x
        y=3*cell_h+max(0,(size.height-7*cell_h-ink.height)/2)-ink.y
        context.save(); Gdk.cairo_set_source_rgba(context,color('#9dff72'))
        context.move_to(x,y); PangoCairo.show_layout(context,layout); context.restore()
        return False

    def draw_static(self,widget,context):
        remaining=self.static_until-time.monotonic()
        if remaining<=0: return False
        size=widget.get_allocation(); fade=min(1,remaining/.24)
        rng=random.Random()
        context.set_source_rgba(.61,1,.45,.48*fade*fade)
        for _ in range(int(size.width*size.height/260)):
            context.rectangle(rng.randrange(max(1,size.width)),rng.randrange(max(1,size.height)),rng.randrange(2,10),1)
        context.fill()
        y=int(size.height*(1-fade))
        context.set_source_rgba(.61,1,.45,.32*fade)
        context.rectangle(0,y,size.width,2); context.fill()
        return False

    def animate_session_switch(self):
        self.sounds.play('static')
        self.static_until=time.monotonic()+.24
        self.stack.get_visible_child().queue_draw()
        if self.static_timer is None:
            self.static_timer=GLib.timeout_add(25,self.static_frame)

    def static_frame(self):
        child=self.stack.get_visible_child()
        if self.closed or child is None:
            self.static_timer=None
            return False
        child.queue_draw()
        if self.closed or time.monotonic()>=self.static_until:
            self.static_timer=None
            return False
        return True

    def spawn(self,terminal,argv,cwd,env,callback):
        terminal.spawn_async(Vte.PtyFlags.DEFAULT,cwd,argv,[k+'='+v for k,v in env.items()],GLib.SpawnFlags.DEFAULT,None,None,-1,None,callback,None)

    def nav_spawned(self,terminal,pid,error,*args):
        if error:
            print(error,file=sys.stderr); self.shutdown()
        else: self.nav_pid=pid

    def typing_sound(self,widget,event):
        if not event.state&(Gdk.ModifierType.CONTROL_MASK|Gdk.ModifierType.MOD1_MASK):
            code=Gdk.keyval_to_unicode(event.keyval)
            if event.keyval==Gdk.KEY_BackSpace or (code and chr(code).isprintable()): self.sounds.play('type')
        return False

    def sudo_feedback(self,widget):
        # Only retry-message counts are retained; screen text is never logged.
        text=widget.get_accessible().get_text(0,-1) or ''
        count=text.count('Sorry, try again.')
        previous=getattr(widget,'sudo_retry_count',0)
        if count>previous: self.sounds.play('bad')
        widget.sudo_retry_count=count

    def nav_keys(self,widget,event):
        if event.state&Gdk.ModifierType.CONTROL_MASK and event.keyval in (Gdk.KEY_m,Gdk.KEY_M):
            widget.feed_child(b'\x0f'); return True
        return False

    def terminal_menu(self,widget,event):
        if event.button!=3: return False
        menu=Gtk.Menu()
        copy=Gtk.MenuItem(label='Copy   Ctrl+Shift+C')
        copy.set_sensitive(widget.get_has_selection())
        copy.connect('activate',lambda item: widget.copy_clipboard_format(Vte.Format.TEXT))
        menu.append(copy)
        paste=Gtk.MenuItem(label='Paste   Ctrl+Shift+V')
        paste.connect('activate',lambda item: widget.paste_clipboard())
        menu.append(paste)
        select=Gtk.MenuItem(label='Select all   Ctrl+Shift+A')
        select.connect('activate',lambda item: widget.select_all())
        menu.append(select)
        menu.show_all(); menu.popup_at_pointer(event)
        return True

    def keyboard_selection(self,widget,step):
        accessible=widget.get_accessible()
        text=accessible.get_text(0,-1)
        state=getattr(widget,'keyboard_selection_range',None)
        if state is None:
            anchor=accessible.get_caret_offset()
            state=(anchor,anchor)
        anchor,end=state
        start=text.rfind('\n',0,end)+1
        column=end-start
        if step<0:
            previous=max(0,start-1)
            line=text.rfind('\n',0,previous)+1
            end=min(previous,line+column)
        else:
            boundary=text.find('\n',end)
            if boundary<0: end=len(text)
            else:
                line=boundary+1
                boundary=text.find('\n',line)
                end=min(len(text) if boundary<0 else boundary,line+column)
        low,high=sorted((anchor,end))
        if accessible.get_n_selections(): accessible.set_selection(0,low,high)
        elif low!=high: accessible.add_selection(low,high)
        widget.keyboard_selection_range=(anchor,end)

    def session_keys(self,widget,event):
        if event.keyval in (Gdk.KEY_Return,Gdk.KEY_KP_Enter):
            self.sounds.play('ok')
        if event.state&Gdk.ModifierType.SHIFT_MASK and not event.state&Gdk.ModifierType.CONTROL_MASK and event.keyval in (Gdk.KEY_Up,Gdk.KEY_Down):
            self.keyboard_selection(widget,-1 if event.keyval==Gdk.KEY_Up else 1)
            return True
        if not (event.state&Gdk.ModifierType.CONTROL_MASK and event.state&Gdk.ModifierType.SHIFT_MASK):
            widget.keyboard_selection_range=None
        modifiers=Gdk.ModifierType.CONTROL_MASK|Gdk.ModifierType.SHIFT_MASK
        if event.state&modifiers==modifiers:
            key=Gdk.keyval_to_lower(event.keyval)
            if key==Gdk.KEY_c:
                widget.copy_clipboard_format(Vte.Format.TEXT); return True
            if key==Gdk.KEY_v:
                widget.paste_clipboard(); return True
            if key==Gdk.KEY_a:
                widget.select_all(); return True
        if event.state&Gdk.ModifierType.CONTROL_MASK:
            if event.keyval==Gdk.KEY_bracketright: self.detach(); return True
            if event.keyval in (Gdk.KEY_Up,Gdk.KEY_Down):
                self.cycle(-1 if event.keyval==Gdk.KEY_Up else 1); return True
        return False

    def launch(self,action,label,details):
        if action not in ('connect','push','revoke','generate','shell','editor','command'): raise ValueError('Unknown terminal action.')
        sid=uuid.uuid4().hex; path=state_dir()/'sessions'/(sid+'.json')
        atomic_json(path,{'id':sid,'action':action,'label':label,'status':'starting',**details})
        terminal=self.terminal(EDITOR_FONT if action=='editor' else SHELL_FONT)
        terminal.connect('key-press-event',self.session_keys)
        terminal.connect('child-exited',lambda widget,status: self.child_exited(sid,status))
        terminal.connect('contents-changed',self.sudo_feedback)
        record={'id':sid,'label':label,'action':action,'path':path,'terminal':terminal,'pid':None,'closed':False,'font':EDITOR_FONT if action=='editor' else SHELL_FONT}
        self.records[sid]=record; self.stack.add_named(terminal,sid); terminal.show()
        def spawned(widget,pid,error,*args):
            if error:
                record['closed']=True; terminal.feed(('Cannot start terminal: '+str(error)).encode())
            else: record['pid']=pid
        env=dict(os.environ,TERM='xterm-256color',FALLOUT_SOUND_SOCKET=str(self.path))
        env.pop('FALLOUT_EMBEDDED_SOCKET',None)
        self.spawn(terminal,[sys.executable,str(ROOT/'scripts/session.py'),str(path)],str(details.get('cwd',Path.home())),env,spawned)
        return {'id':sid,'label':label}

    def status(self,record):
        if record['closed']: return 'closed'
        try: return json.loads(record['path'].read_text()).get('status','starting')
        except (OSError,ValueError): return 'starting'

    def show_session(self,sid):
        if sid not in self.records: raise ValueError('Session not found.')
        record=self.records[sid]
        if self.current is not None and self.current!=sid: self.animate_session_switch()
        self.current=sid; self.stack.set_visible_child_name(sid)
        self.heading.set_text('TERMINAL // '+record['label']); self.heading.show(); self.footer.show()
        GLib.idle_add(record['terminal'].grab_focus)

    def show_navigator(self):
        self.stack.set_visible_child_name('navigator'); self.heading.hide(); self.footer.hide()
        GLib.idle_add(self.navigator.grab_focus)

    def detach(self):
        selected=self.current; self.current=None; self.show_navigator()
        if self.waiter:
            self.waiter({'id':selected}); self.waiter=None

    def cycle(self,step):
        active=[sid for sid,record in self.records.items() if self.status(record) in ('running','starting')]
        if not active: return
        index=active.index(self.current) if self.current in active else (-1 if step==1 else 0)
        self.show_session(active[(index+step)%len(active)])

    def child_exited(self,sid,status):
        record=self.records[sid]; record['closed']=True
        if self.current==sid: self.detach()

    def refresh(self):
        if self.closed: return False
        self.sounds.refresh()
        transparent=navigator_settings.transparent()
        if transparent!=self.transparent:
            self.transparent=transparent
            self.window.queue_draw()
        size=navigator_settings.font_size()
        if size!=self.nav_font_size:
            self.navigator.set_font(Pango.FontDescription('DejaVu Sans Mono '+str(size)))
            self.nav_font_size=size
        for record in self.records.values():
            if record['closed']: continue
            try: data=json.loads(record['path'].read_text())
            except (OSError,ValueError): continue
            font=EDITOR_FONT if record['action']=='editor' and data.get('view')!='shell' else SHELL_FONT
            if font!=record['font']:
                record['terminal'].set_font(Pango.FontDescription(font)); record['font']=font
        return True

    def close_session(self,sid):
        record=self.records.get(sid)
        if not record or record['closed']: return
        try:
            pty=record['terminal'].get_pty()
            if pty:
                foreground=os.tcgetpgrp(pty.get_fd())
                if foreground!=os.getpgrp(): os.killpg(foreground,signal.SIGHUP)
        except OSError: pass
        if record['pid']:
            try: os.killpg(record['pid'],signal.SIGHUP)
            except OSError: pass
        record['closed']=True
        if self.current==sid: self.detach()

    def serve(self):
        while not self.closed:
            try: connection,_=self.listener.accept()
            except OSError: break
            threading.Thread(target=self.handle,args=(connection,),daemon=True).start()

    def handle(self,connection):
        with connection:
            try:
                _,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if uid!=os.getuid(): raise ValueError('Unauthorized client.')
                stream=connection.makefile('rb'); line=stream.readline(65537)
                if len(line)>65536: raise ValueError('Request too large.')
                request=json.loads(line); done=threading.Event(); response={}
                def reply(value): response.update(value); done.set()
                def dispatch():
                    try:
                        command=request['command']
                        if command=='launch': reply(self.launch(request['action'],request['label'],request.get('details',{})))
                        elif command=='clock':
                            self.clock_value=str(request.get('value',''))[:5]
                            self.navigator.queue_draw(); reply({})
                        elif command=='choose_application': reply({'path':self.choose_application(request.get('initial',''))})
                        elif command=='status': reply({'status':self.status(self.records[request['id']])})
                        elif command=='close': self.close_session(request['id']); reply({})
                        elif command=='attach':
                            if self.waiter: raise ValueError('A terminal is already attached.')
                            self.show_session(request['id']); self.waiter=reply
                        elif command=='sound':
                            self.sounds.play(request.get('event','')); reply({})
                        elif command=='hide':
                            self.window.hide(); reply({})
                        elif command=='toggle':
                            self.sounds.play('load')
                            if self.window.get_visible(): self.window.hide()
                            else: self.window.show(); self.window.present()
                            reply({})
                        else: raise ValueError('Unknown host command.')
                    except Exception as error: reply({'error':str(error)})
                    return False
                GLib.idle_add(dispatch)
                while not done.wait(.2):
                    if self.closed: return
                connection.sendall(json.dumps(response).encode()+b'\n')
            except (OSError,ValueError,KeyError) as error:
                try: connection.sendall(json.dumps({'error':str(error)}).encode()+b'\n')
                except OSError: pass

    def choose_application(self,initial):
        dialog=Gtk.FileChooserDialog(title='Choose application executable',parent=self.window,action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons('Cancel',Gtk.ResponseType.CANCEL,'Select',Gtk.ResponseType.OK)
        dialog.set_current_folder('/usr/bin')
        if initial and Path(initial).expanduser().is_file():
            dialog.set_filename(str(Path(initial).expanduser()))
        try:
            if dialog.run()==Gtk.ResponseType.OK: return dialog.get_filename()
            return None
        finally: dialog.destroy()

    def delete(self,*args):
        live=any(not record['closed'] for record in self.records.values())
        if live:
            dialog=Gtk.MessageDialog(transient_for=self.window,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text='Close all terminal sessions and exit?')
            choice=dialog.run(); dialog.destroy()
            if choice!=Gtk.ResponseType.OK: return True
        self.shutdown(); return True

    def nav_exited(self,*args): self.shutdown()

    def shutdown(self):
        if self.closed: return
        for sid in list(self.records): self.close_session(sid)
        self.closed=True
        self.sounds.close()
        self.listener.close(); self.path.unlink(missing_ok=True)
        if self.nav_pid:
            try: os.killpg(self.nav_pid,signal.SIGHUP)
            except OSError: pass
        self.window.destroy()


def main():
    path=runtime()/'embedded.sock'
    # Subsequent F12 invocations toggle the existing host without killing sessions.
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            client.connect(str(path)); client.sendall(b'{"command":"toggle"}\n'); client.recv(4096)
        return
    except OSError: pass
    lock=(runtime()/'embedded.lock').open('a')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: return
    path.unlink(missing_ok=True)
    listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); listener.bind(str(path)); os.chmod(path,0o600); listener.listen(16)
    host=Host(path,listener)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,lambda: (host.shutdown(),False)[1])
    try: Gtk.main()
    finally:
        host.shutdown(); lock.close()

if __name__=='__main__': main()
