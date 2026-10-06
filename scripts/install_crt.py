#!/usr/bin/python3
"""Install and start the reversible per-user CRT overlay."""
import json
import shutil
import subprocess
from setup import ROOT,HOME,BACKUP,run
run(['xfconf-query','-c','xfwm4','-p','/general/use_compositing'])
target='.config/autostart/fallout-crt.desktop'
manifest_path=BACKUP/'files.json'
if not manifest_path.exists(): raise SystemExit('Run install.sh first to back up the desktop.')
manifest=json.loads(manifest_path.read_text())
if not any(item['path']==target for item in manifest):
    file=HOME/target
    if file.exists():
        saved=BACKUP/'files'/str(len(manifest)); saved.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(file,saved)
    manifest.append({'path':target,'exists':file.exists()})
    manifest_path.write_text(json.dumps(manifest))
from crt_settings import enabled, set_enabled
set_enabled(enabled())
print('CRT overlay settings installed; saved enable/disable choice preserved.')
