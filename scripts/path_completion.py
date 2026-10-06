"""Directory-only completion; relative paths use the source file's directory."""
import os
from pathlib import Path


def directory_matches(value,base):
    if value=='~': return ['~/']
    slash=value.rfind('/')
    prefix=value[:slash+1] if slash>=0 else ''
    fragment=value[slash+1:]
    parent=Path(prefix or '.').expanduser()
    if not parent.is_absolute(): parent=Path(base)/parent
    try:
        children=[child.name for child in parent.iterdir() if child.name.startswith(fragment) and (fragment.startswith('.') or not child.name.startswith('.')) and child.is_dir()]
    except OSError: return []
    return [prefix+name+'/' for name in sorted(children)]


def complete_directory(value,matches,selected=0,explicit=False):
    if not matches: return value
    shared=os.path.commonprefix(matches)
    if not explicit and len(matches)>1 and len(shared)>len(value): return shared
    return matches[min(max(selected,0),len(matches)-1)]
