#!/usr/bin/env python3
"""Interactive operations inside an attached navigator PTY. Never store passwords."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from ssh_manager import Catalog, atomic_json, ssh_args, public_key, remote_command, generate_path


def interactive_ssh(args):
    errors=[]
    proc=subprocess.Popen(args,stderr=subprocess.PIPE)
    def relay():
        while True:
            chunk=os.read(proc.stderr.fileno(),4096)
            if not chunk: break
            os.write(2,chunk)
            errors.append(chunk)
            if sum(map(len,errors))>65536: errors.pop(0)
    thread=threading.Thread(target=relay); thread.start()
    code=proc.wait(); thread.join()
    return code,b''.join(errors).decode(errors='replace')


def push(host,key,directory):
    kind,blob,line=public_key(key)
    command=remote_command(directory,blob,'push',line)
    print('\nInstalling PUBLIC key on '+host['name']+' in '+directory+'/authorized_keys')
    print('OpenSSH will prompt for authentication as needed. Private keys stay local.')
    code=subprocess.call(ssh_args(host,key)+[command])
    if code==0:
        Catalog().installed(host,key,directory)
        print('Public key installed successfully.')
    return code


def connect(host,key):
    if not key: return subprocess.call(ssh_args(host,password_only=True))
    code,errors=interactive_ssh(ssh_args(host,key,key_only=True))
    if code==255 and 'Permission denied' in errors:
        choice=input('\nKey authentication failed. Push this public key? [y/N] ').strip().lower()
        if choice=='y':
            directory=input('Remote SSH directory [~/.ssh]: ').strip() or '~/.ssh'
            if push(host,key,directory)==0:
                return subprocess.call(ssh_args(host,key,key_only=True))
        else: print('Connection cancelled. Host and key were not changed.')
    elif code==255: print('\nSSH could not connect. Check the address, network, and host-key messages above.')
    return code


def revoke(records,key):
    result=0
    for record in records:
        host=record['host']
        print('\nRevoking public key from '+host['name']+' ('+host['address']+') / '+record['directory'])
        command=remote_command(record['directory'],record['blob'],'revoke')
        code=subprocess.call(ssh_args(host,key)+[command])
        if code==0:
            Catalog().update(lambda data: data.__setitem__('installed',[i for i in data['installed'] if i['id']!=record['id']]))
            print('Revoked. Local key retained.')
        else:
            print('Revocation failed; this host remains tracked for retry.'); result=code
    return result


def main(path):
    job=json.loads(path.read_text()); job.update(pid=os.getpid(),status='running'); atomic_json(path,job)
    code=1
    try:
        action=job['action']
        if action=='connect': code=connect(job['host'],job.get('key'))
        elif action=='push': code=push(job['host'],job['key'],job['directory'])
        elif action=='revoke': code=revoke(job['records'],job['key'])
        elif action=='generate':
            name=job['name']; key_path=generate_path(name)
            key_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            print('Generate Ed25519 key. Enter a passphrase when prompted, or leave it blank.')
            code=subprocess.call(['ssh-keygen','-t','ed25519','-f',str(key_path),'-C','fallout:'+name])
            if code==0:
                os.chmod(key_path,0o600); Catalog().add_key(name,key_path)
                print('Key saved. Select it under SSH > SSH-KEY > Saved keys.')
        elif action=='editor':
            code=subprocess.call(['nano','--',job['path']],cwd=job['cwd'])
            if code==0:
                job['view']='shell'; atomic_json(path,job)
                code=subprocess.call(['bash','--rcfile',str(Path(__file__).with_name('bashrc'))],cwd=job['cwd'])
        elif action=='command': code=subprocess.call(job['argv'])
        elif action=='shell': code=subprocess.call(['bash','--rcfile',str(Path(__file__).with_name('bashrc'))],cwd=job.get('cwd',str(Path.home())))
        else: raise ValueError('Unknown session action.')
    except (OSError,ValueError,KeyboardInterrupt) as error:
        print('\n'+str(error))
    finally:
        job.update(status='finished' if code==0 else 'failed',exit_code=code); atomic_json(path,job)
    try: input('\nSession ended. Press Enter to return to the navigator. ')
    except (EOFError,KeyboardInterrupt): pass

if __name__=='__main__': main(Path(sys.argv[1]))
