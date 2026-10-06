#!/usr/bin/env python3
"""Refresh larger/brighter styling without resetting panels or terminal sessions."""
import shutil
import subprocess
import time
from setup import ROOT, HOME, CONFIG, setprop, run
run(['xfconf-query','-c','xfce4-panel','-l'])
shutil.copytree(ROOT/'theme',HOME/'.themes/Fallout-PipBoy',dirs_exist_ok=True)
setprop('xsettings','/Gtk/FontName','DejaVu Sans 12')
setprop('xsettings','/Gtk/MonospaceFontName','DejaVu Sans Mono 14')
setprop('xfwm4','/general/title_font','DejaVu Sans Bold 12')
for p,v,t in [('font-name','DejaVu Sans Mono 14','string'),('font-use-system',False,'bool'),('color-use-theme',False,'bool'),('color-foreground','#b6ffa3','string'),('color-cursor','#9dff72','string')]:
    setprop('xfce4-terminal','/'+p,v,t)
palette='#09110b;#ff6b6b;#9dff72;#ffe478;#8ab4ff;#eda6ff;#89f5ee;#d7f5d0;#6a8c6b;#ff9393;#b6ffa3;#fff3a1;#b4ceff;#f6c5ff;#b6fff6;#f3fff0'
setprop('xfce4-terminal','/color-palette',palette)
setprop('xfce4-panel','/panels/panel-1/size',36,'uint')
setprop('xfce4-panel','/panels/panel-1/icon-size',22,'uint')
run(['xfce4-panel','--quit'])
time.sleep(.4)
gen=CONFIG/'xfce4/panel/genmon-4.rc'
s=gen.read_text().replace('Font=DejaVu Sans Mono 9','Font=DejaVu Sans Mono 12')
gen.write_text(s)
# Refresh CSS and monitor font; shell sessions continue independently of the panel.
setprop('xsettings','/Net/ThemeName','Adwaita-dark')
setprop('xsettings','/Net/ThemeName','Fallout-PipBoy')
subprocess.Popen(['xfce4-panel'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
print('Applied: terminal 14pt, desktop 12pt, panel 36px, brighter green palette.')
