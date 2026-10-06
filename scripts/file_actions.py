"""Single-file operations that preserve existing destination files."""
from datetime import datetime
import errno
import grp
import os
from pathlib import Path
import pwd
import shutil
import stat
import zipfile


def source_file(path):
    path=Path(path)
    mode=path.lstat().st_mode
    if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
        raise ValueError('Select a file; folder operations are not available yet.')
    return path


def new_name(source,name):
    source=source_file(source)
    if not name or name in ('.','..') or '/' in name or any(ord(c)<32 for c in name):
        raise ValueError('Enter a filename without a directory path.')
    result=source.with_name(name)
    if result==source: raise ValueError('The filename has not changed.')
    return result


def destination(source,directory):
    source=source_file(source)
    if not directory.strip(): raise ValueError('Enter a destination directory.')
    folder=Path(directory).expanduser()
    if not folder.is_absolute(): folder=source.parent/folder
    if not folder.is_dir(): raise ValueError('Destination directory does not exist.')
    return folder/source.name


def copy_file(source,target):
    source=source_file(source); target=Path(target)
    if source.is_symlink():
        os.symlink(os.readlink(source),target)
        return target
    created=False
    try:
        with source.open('rb') as reader, target.open('xb') as writer:
            created=True
            shutil.copyfileobj(reader,writer,1024*1024)
        shutil.copystat(source,target)
    except BaseException:
        if created: target.unlink(missing_ok=True)
        raise
    return target


def move_file(source,target):
    source=source_file(source); target=Path(target)
    try: os.link(source,target,follow_symlinks=False)
    except OSError as error:
        if error.errno!=errno.EXDEV: raise
        copy_file(source,target)
    try: source.unlink()
    except OSError:
        # Original file is still present; remove only the new copy/link we created.
        target.unlink(missing_ok=True)
        raise
    return target


def compress_file(source):
    source=source_file(source); archive=source.with_name(source.name+'.zip')
    created=False
    try:
        with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as output:
            created=True
            if source.is_symlink():
                info=zipfile.ZipInfo(source.name)
                info.create_system=3
                info.external_attr=(stat.S_IFLNK | 0o777)<<16
                output.writestr(info,os.readlink(source))
            else: output.write(source,arcname=source.name)
    except BaseException:
        if created: archive.unlink(missing_ok=True)
        raise
    return archive


def file_info(source):
    source=Path(source); info=source.lstat()
    try: owner=pwd.getpwuid(info.st_uid).pw_name
    except KeyError: owner=str(info.st_uid)
    try: group=grp.getgrgid(info.st_gid).gr_name
    except KeyError: group=str(info.st_gid)
    kind='Symbolic link' if stat.S_ISLNK(info.st_mode) else 'Regular file' if stat.S_ISREG(info.st_mode) else 'Directory' if stat.S_ISDIR(info.st_mode) else 'Special file'
    lines=['Name: '+source.name,'Directory: '+str(source.parent),'Type: '+kind,f'Size: {info.st_size:,} bytes','Permissions: '+stat.filemode(info.st_mode),f'Owner: {owner} / {group}','Modified: '+datetime.fromtimestamp(info.st_mtime).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')]
    if source.is_symlink(): lines.append('Link target: '+os.readlink(source))
    return lines


def create_entry(directory,name,kind):
    directory=Path(directory)
    if not directory.is_dir(): raise ValueError('Select an existing directory.')
    if not name or name in ('.','..') or '/' in name or any(ord(c)<32 for c in name):
        raise ValueError('Enter a name without a directory path.')
    path=directory/name
    if kind=='Directory': path.mkdir()
    elif kind=='File':
        with path.open('xb'): pass
    else: raise ValueError('Choose File or Directory.')
    return path
