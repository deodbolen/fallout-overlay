#!/usr/bin/env python3
import pathlib, subprocess, shutil, json, sys, configparser, xml.etree.ElementTree as ET, os
ROOT=pathlib.Path(__file__).resolve().parent.parent
HOME=pathlib.Path.home(); CONFIG=HOME/'.config'; BACKUP=HOME/'.local/state/fallout-ui/original'
CHANNELS=['xfce4-panel','xsettings','xfwm4','xfce4-desktop','xfce4-keyboard-shortcuts','xfce4-terminal']
def run(args,check=True): return subprocess.run(args,text=True,capture_output=True,check=check)
def query(c,p): return run(['xfconf-query','-c',c,'-p',p],False)
def setprop(c,p,value,kind='string'):
    args=['xfconf-query','-c',c,'-p',p,'-n']
    if isinstance(value,list):
        args+=['-a']
        for v in value: args+=['-t',kind,'-s',str(v)]
    else: args+=['-t',kind,'-s',str(value).lower() if isinstance(value,bool) else str(value)]
    run(args)
def reset(c,p): run(['xfconf-query','-c',c,'-p',p,'-r','-R'],False)
def restore_xml(c,path):
    if not path.exists(): return
    def walk(node,prefix=''):
        for el in node.findall('property'):
            p=prefix+'/'+el.attrib['name']; t=el.attrib['type']
            if t=='array':
                values=el.findall('value')
                if values:
                    args=['xfconf-query','-c',c,'-p',p,'-n','-a']
                    for v in values: args+=['-t',v.attrib['type'],'-s',v.attrib['value']]
                    run(args)
            elif t!='empty': setprop(c,p,el.attrib['value'],t)
            walk(el,p)
    reset(c,'/'); walk(ET.parse(path).getroot())
def preflight():
    if os.geteuid()==0: raise SystemExit('Run the desktop installer as your XFCE user, without sudo.')
    if not os.environ.get('DISPLAY'): raise SystemExit('Run install.sh from a terminal inside your logged-in XFCE X11 session.')
    required=['scripts/terminal.sh','scripts/bashrc','assets/navigator-background.svg','logo/pip-boy-logo.png','theme/gtk-3.0/gtk.css','fallout-sounds/fansound/ui_hacking_fanhum_lp.wav']
    missing=[name for name in required if not (ROOT/name).is_file()]
    if missing: raise SystemExit('Copy the complete Fallout-UI folder. Missing: '+', '.join(missing))
    probe="import gi,cairo;gi.require_version('Gtk','3.0');gi.require_version('Vte','2.91');gi.require_version('Gst','1.0');from gi.repository import Gtk,Vte,Gst;Gst.init(None);assert Gst.ElementFactory.find('playbin')"
    run(['/usr/bin/python3','-c',probe])

def main():
    if sys.argv[1]=='install': preflight()
    run(['xfconf-query','-c','xfce4-panel','-l']) # Fail before any writes if session unavailable.
    targets=['.config/xfce4/panel','.config/xfce4/terminal','.themes/Fallout-PipBoy']
    if sys.argv[1]=='restore':
        if not BACKUP.exists(): raise SystemExit('No original backup found.')
        run(['/usr/bin/python3',str(ROOT/'scripts/crt_overlay.py'),'--stop'],False)
        run(['xfce4-panel','--quit'],False)
        for c in CHANNELS: restore_xml(c,BACKUP/(c+'.xml'))
        manifest=json.loads((BACKUP/'files.json').read_text())
        for i,item in enumerate(manifest):
            dest=HOME/item['path']
            if dest.is_dir(): shutil.rmtree(dest)
            elif dest.exists(): dest.unlink()
            if item['exists']:
                dest.parent.mkdir(parents=True,exist_ok=True)
                src=BACKUP/'files'/str(i)
                if src.is_dir(): shutil.copytree(src,dest)
                else: shutil.copy2(src,dest)
        subprocess.Popen(['xfce4-panel'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        print('Original XFCE configuration restored. Log out/in to refresh existing application windows.'); return
    # Never overwrite original baseline on repeat install.
    if not BACKUP.exists():
        BACKUP.mkdir(parents=True)
        for c in CHANNELS:
            src=CONFIG/'xfce4/xfconf/xfce-perchannel-xml'/(c+'.xml')
            if src.exists(): shutil.copy2(src,BACKUP/src.name)
        manifest=[]
        for i,t in enumerate(targets):
            src=HOME/t; manifest.append({'path':t,'exists':src.exists()})
            if src.exists():
                dest=BACKUP/'files'/str(i); dest.parent.mkdir(parents=True,exist_ok=True)
                if src.is_dir(): shutil.copytree(src,dest)
                else: shutil.copy2(src,dest)
        (BACKUP/'files.json').write_text(json.dumps(manifest))
    # Newer XFCE Terminal stores preferences in its own xfconf channel.
    terminal_snapshot=BACKUP/'xfce4-terminal.xml'
    terminal_source=CONFIG/'xfce4/xfconf/xfce-perchannel-xml/xfce4-terminal.xml'
    if not terminal_snapshot.exists() and terminal_source.exists(): shutil.copy2(terminal_source,terminal_snapshot)
    shutil.copytree(ROOT/'theme',HOME/'.themes/Fallout-PipBoy',dirs_exist_ok=True)
    # Preserve terminal preferences outside the keys we change.
    term=CONFIG/'xfce4/terminal/terminalrc'; term.parent.mkdir(parents=True,exist_ok=True)
    cfg=configparser.ConfigParser(); cfg.optionxform=str
    if term.exists(): cfg.read(term)
    if not cfg.has_section('Configuration'): cfg.add_section('Configuration')
    palette='#09110b;#ff6b6b;#9dff72;#ffe478;#8ab4ff;#eda6ff;#89f5ee;#d7f5d0;#6a8c6b;#ff9393;#b6ffa3;#fff3a1;#b4ceff;#f6c5ff;#b6fff6;#f3fff0'
    prefs={'ColorPalette':palette,'ColorUseTheme':'FALSE','FontUseSystem':'FALSE','FontName':'DejaVu Sans Mono 14','ColorForeground':'#b6ffa3','ColorBackground':'#050a06','ColorCursor':'#9dff72','BackgroundMode':'TERMINAL_BACKGROUND_IMAGE','BackgroundImageFile':str(ROOT/'assets/navigator-background.svg'),'BackgroundImageStyle':'TERMINAL_BACKGROUND_STYLE_STRETCHED','BackgroundImageShading':'0.0','DropdownAlwaysShowTabs':'FALSE','DropdownShowBorders':'FALSE','MiscAlwaysShowTabs':'FALSE','MiscMenubarDefault':'FALSE','MiscBell':'FALSE','DropdownWidth':'100','DropdownHeight':'100','DropdownOpacity':'100','DropdownAnimationTime':'0','DropdownPosition':'0','DropdownMoveToActive':'TRUE'}
    for k,v in prefs.items(): cfg.set('Configuration',k,v)
    with term.open('w') as f: cfg.write(f,space_around_delimiters=False)
    for name,value,kind in [('font-name','DejaVu Sans Mono 14','string'),('color-foreground','#b6ffa3','string'),('color-background','#050a06','string'),('color-cursor','#9dff72','string'),('dropdown-width',100,'uint'),('dropdown-height',100,'uint'),('dropdown-opacity',100,'uint'),('dropdown-animation-time',0,'uint'),('misc-menubar-default',False,'bool'),('misc-bell',False,'bool'),('dropdown-always-show-tabs',False,'bool'),('dropdown-show-borders',False,'bool'),('misc-always-show-tabs',False,'bool'),('color-use-theme',False,'bool'),('font-use-system',False,'bool'),('color-palette',palette,'string'),('background-mode','TERMINAL_BACKGROUND_IMAGE','string'),('background-image-file',str(ROOT/'assets/navigator-background.svg'),'string'),('background-image-style','TERMINAL_BACKGROUND_STYLE_STRETCHED','string'),('background-image-shading',0.0,'double')]:
        setprop('xfce4-terminal','/'+name,value,kind)
    setprop('xsettings','/Net/ThemeName','Fallout-PipBoy'); setprop('xsettings','/Gtk/MonospaceFontName','DejaVu Sans Mono 14')
    setprop('xsettings','/Gtk/FontName','DejaVu Sans 12')
    setprop('xfwm4','/general/title_font','DejaVu Sans Bold 12')
    setprop('xfwm4','/general/theme','Fallout-PipBoy')
    # Update all existing monitor/workspace wallpaper properties.
    props=run(['xfconf-query','-c','xfce4-desktop','-l']).stdout.splitlines()
    for p in props:
        if p.endswith(('/last-image','/image-path')):
            setprop('xfce4-desktop',p,str(ROOT/'logo/pip-boy-logo.png'))
            setprop('xfce4-desktop',p.rsplit('/',1)[0]+'/image-style',4,'int')
        if p.endswith('/image-style'): setprop('xfce4-desktop',p,4,'int')
    command=__import__('shlex').quote(str(ROOT/'scripts/terminal.sh')); key='F12'
    for candidate in ('F12','<Primary><Alt>F12'):
        existing=query('xfce4-keyboard-shortcuts','/commands/custom/'+candidate)
        wm=query('xfce4-keyboard-shortcuts','/xfwm4/custom/'+candidate)
        if (existing.returncode or existing.stdout.strip()==command) and wm.returncode:
            key=candidate; break
    else: raise SystemExit('Both terminal shortcuts are occupied; original backup is available for restore.')
    setprop('xfce4-keyboard-shortcuts','/commands/custom/'+key,command)
    run(['xfce4-panel','--quit'],False)
    reset('xfce4-panel','/panels'); reset('xfce4-panel','/plugins')
    setprop('xfce4-panel','/panels',[1],'int')
    panel='/panels/panel-1'
    for p,v,t in [('position','p=6;x=0;y=0','string'),('size',36,'uint'),('length',100,'uint'),('position-locked',True,'bool'),('icon-size',22,'uint'),('plugin-ids',[1,2,3,4,5,6],'int')]: setprop('xfce4-panel',panel+'/'+p,v,t)
    for i,name in enumerate(['applicationsmenu','tasklist','separator','genmon','systray','clock'],1): setprop('xfce4-panel',f'/plugins/plugin-{i}',name)
    setprop('xfce4-panel','/plugins/plugin-2/show-labels',False,'bool'); setprop('xfce4-panel','/plugins/plugin-2/grouping',1,'uint')
    setprop('xfce4-panel','/plugins/plugin-3/expand',True,'bool'); setprop('xfce4-panel','/plugins/plugin-3/style',0,'uint')
    setprop('xfce4-panel','/plugins/plugin-6/digital-time-format','%a %H:%M')
    gen=CONFIG/'xfce4/panel/genmon-4.rc'; gen.parent.mkdir(parents=True,exist_ok=True)
    gen.write_text(f'Command=/usr/bin/python3 "{ROOT}/scripts/metrics.py"\nUseLabel=0\nText=\nUpdatePeriod=2000\nFont=DejaVu Sans Mono 12\n')
    subprocess.Popen(['xfce4-panel'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    # CRT is opt-in; desktop installation must not start a full-screen overlay.
    print(f'Installed. Terminal shortcut: {key}. Backup: {BACKUP}')
if __name__=='__main__': main()
