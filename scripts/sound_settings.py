"""Persist fan and effect levels without changing CRT preferences."""
import json
from ssh_manager import config_dir,atomic_json
DEFAULTS={'fan_volume':45,'effects_volume':85}
def levels():
    try: data=json.loads((config_dir()/'settings.json').read_text())
    except (OSError,ValueError): data={}
    result={}
    for field,default in DEFAULTS.items():
        try: result[field]=max(0,min(100,int(data.get(field,default))))
        except (ValueError,TypeError): result[field]=default
    return result

def save(field,value):
    if field not in DEFAULTS: raise ValueError('Unknown volume control.')
    value=int(value)
    if not 0<=value<=100: raise ValueError('Volume must be between 0 and 100.')
    path=config_dir()/'settings.json'
    data=json.loads(path.read_text()) if path.exists() else {}
    data[field]=value; atomic_json(path,data)
