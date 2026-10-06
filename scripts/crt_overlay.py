#!/usr/bin/python3
"""Faint static CRT scanlines on transparent, non-interactive X11 windows."""
import fcntl
import os
from pathlib import Path
import signal
import sys
import time
import crt_settings
import cairo
import gi
gi.require_version('Gtk','3.0')
gi.require_version('GdkX11','3.0')
gi.require_foreign('cairo')
from gi.repository import Gtk, Gdk, GLib, GdkX11
from x11_input import make_click_through
from crt_scan import draw_scan
from sounds import Sounds

SPACING=4
OPACITY=0.065
runtime=Path(os.environ.get('XDG_RUNTIME_DIR',str(Path.home()/'.cache')))/'fallout-ui'

class Overlay(Gtk.Window):
    def __init__(self,geometry,static=True,animation=False):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.static=static
        self.animation=animation
        self.started=time.monotonic()
        self.set_title('Fallout CRT overlay')
        self.set_decorated(False)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.stick()
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_app_paintable(True)
        visual=self.get_screen().get_rgba_visual()
        if visual is None: raise RuntimeError('The desktop does not provide an RGBA visual.')
        self.set_visual(visual)
        self.move(geometry.x,geometry.y)
        self.set_default_size(geometry.width,geometry.height)
        self.connect('realize',self.realized)
        self.connect('map',self.set_pass_through)
        self.connect('size-allocate',self.set_pass_through)

    def realized(self,*args):
        native=self.get_window()
        native.set_override_redirect(True)
        native.input_shape_combine_region(cairo.Region(),0,0)
        self.set_pass_through()

    def set_pass_through(self,*args):
        # Keep GTK's saved input shape empty so mapping/resizing preserves it.
        self.input_shape_combine_region(cairo.Region())
        native=self.get_window()
        if native is not None:
            native.input_shape_combine_region(cairo.Region(),0,0)
            native.set_pass_through(True)
            native.get_display().sync()
            try: make_click_through(native.get_xid())
            except Exception as error:
                print('CRT overlay stopped: '+str(error),file=sys.stderr,flush=True)
                self.destroy()
                GLib.idle_add(Gtk.main_quit)

    def do_draw(self,context):
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0,0,0,0)
        context.paint()
        context.set_operator(cairo.OPERATOR_OVER)
        context.set_source_rgba(0,0,0,OPACITY)
        size=self.get_allocation()
        if self.static:
            for y in range(0,size.height,SPACING): context.rectangle(0,y,size.width,1)
            context.fill()
        if self.animation:
            draw_scan(context,size.width,size.height,time.monotonic()-self.started)
        return False


def main():
    runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
    pidfile=runtime/'crt.pid'
    if '--stop' in sys.argv:
        try:
            pid=int(pidfile.read_text())
            command=Path(f'/proc/{pid}/cmdline').read_bytes()
            if str(Path(__file__).resolve()).encode() in command: os.kill(pid,signal.SIGTERM)
        except (OSError,ValueError): pass
        return
    lock=(runtime/'crt.lock').open('a')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: return
    display=Gdk.Display.get_default()
    if display is None: raise SystemExit('CRT overlay requires a desktop session.')
    screen=Gdk.Screen.get_default()
    if not screen.is_composited(): raise SystemExit('CRT overlay requires XFCE compositing.')
    pidfile.write_text(str(os.getpid()))
    windows=[]
    static=crt_settings.enabled()
    animation=crt_settings.animation_enabled() or '--verify-animation' in sys.argv
    def rebuild(*args):
        for window in windows: window.destroy()
        windows.clear()
        for i in range(display.get_n_monitors()):
            window=Overlay(display.get_monitor(i).get_geometry(),static,animation); window.show_all(); windows.append(window)
    rebuild()
    sounds=Sounds(); sounds.play('fan',loop=True)
    GLib.timeout_add(250,sounds.refresh)
    screen.connect('monitors-changed',rebuild)
    if animation:
        def animate():
            for window in windows: window.queue_draw()
            return True
        GLib.timeout_add(33,animate)
    def raise_overlays():
        for window in windows:
            if window.get_window():
                window.set_pass_through()
                window.get_window().raise_()
        return True
    GLib.timeout_add_seconds(2,raise_overlays)
    def stop(*args):
        Gtk.main_quit(); return False
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,stop)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGINT,stop)
    if '--verify' in sys.argv:
        def verify():
            for window in windows:
                if not window.get_window(): raise RuntimeError('Overlay window disappeared.')
                make_click_through(window.get_window().get_xid())
            print('Verified: all CRT overlay windows have empty X11 input regions.',flush=True)
            Gtk.main_quit(); return False
        GLib.timeout_add(500,verify)
        GLib.timeout_add_seconds(3,stop)
    try: Gtk.main()
    finally:
        sounds.close()
        for window in windows: window.destroy()
        pidfile.unlink(missing_ok=True)
        lock.close()

if __name__=='__main__': main()
