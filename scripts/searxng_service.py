"""Installer-managed, rootless local SearXNG service for Yes Man."""
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.request import urlopen
from urllib.error import URLError
from ssh_manager import config_dir, state_dir

URL='http://127.0.0.1:8888'
IMAGE='docker.io/searxng/searxng:latest'
UNIT='fallout-searxng.service'
MARKER='# Managed by Fallout UI: local SearXNG\n'


def run(args,**options):
    return subprocess.run(args,check=True,text=True,**options)


def quote(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'


def service_text(image,config,cache):
    return MARKER+f'''[Unit]
Description=Fallout Yes Man local web search
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/podman run --rm --pull=never --name fallout-searxng --publish 127.0.0.1:8888:8080 --volume {quote(str(config)+':/etc/searxng')} --volume {quote(str(cache)+':/var/cache/searxng')} {quote(image)}
ExecStop=/usr/bin/podman stop --time 10 fallout-searxng
Restart=on-failure
RestartSec=5
TimeoutStartSec=120
TimeoutStopSec=30

[Install]
WantedBy=default.target
'''


def unit_path():
    return Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'systemd/user'/UNIT


def migrate_settings():
    """Preserve the active legacy search choices in the independent tool file."""
    from yes_man_tool_settings import settings, save
    if (config_dir()/'yes-man-tools.json').exists(): return
    config=settings()
    if not config['search_url']: config['search_url']=URL
    save(config)


def install():
    if os.geteuid()==0: raise ValueError('Install the search service as your desktop user, without sudo.')
    run(['systemctl','--user','show-environment'],stdout=subprocess.DEVNULL)
    run(['podman','info'],stdout=subprocess.DEVNULL)
    target=unit_path()
    if target.exists() and not target.read_text().startswith(MARKER):
        raise ValueError('An unmanaged fallout-searxng.service already exists; refusing to replace it.')
    directory=config_dir()/'searxng'; cache=state_dir()/'searxng-cache'
    directory.mkdir(parents=True,exist_ok=True); cache.mkdir(parents=True,exist_ok=True)
    settings=directory/'settings.yml'
    if not settings.exists():
        # Container runtime user must be able to read the mounted configuration.
        directory.chmod(0o755)
        with settings.open('x') as output:
            output.write('use_default_settings: true\nserver:\n  secret_key: "'+secrets.token_hex(32)+
                         '"\n  bind_address: "0.0.0.0"\n  port: 8080\n  limiter: false\n  image_proxy: false\nsearch:\n  formats:\n    - html\n    - json\n')
        settings.chmod(0o644)
    # Keep the installed image between reinstalls; pin the unit to its digest.
    exists=subprocess.run(['podman','image','exists',IMAGE],check=False).returncode==0
    if not exists: run(['podman','pull',IMAGE])
    image=run(['podman','image','inspect','--format','{{index .RepoDigests 0}}',IMAGE],capture_output=True).stdout.strip()
    if '@sha256:' not in image or any(char.isspace() for char in image):
        raise ValueError('Could not determine the SearXNG image digest.')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(service_text(image,directory,cache))
    run(['systemctl','--user','daemon-reload'])
    run(['systemctl','--user','enable',UNIT])
    run(['systemctl','--user','restart',UNIT])
    # Readiness uses the local health endpoint, not an external web search.
    deadline=time.monotonic()+45
    while True:
        try:
            with urlopen(URL+'/healthz',timeout=2) as response:
                ready=response.read(64).strip()==b'OK'
            if ready: break
        except (URLError,OSError,ValueError): pass
        if time.monotonic()>=deadline:
            raise ValueError('Local SearXNG did not become ready. Run: journalctl --user -u '+UNIT+' -n 50')
        time.sleep(.5)
    migrate_settings()
    print('Local Yes Man web search installed: '+URL,flush=True)


def restore():
    target=unit_path()
    if not target.exists() or not target.read_text().startswith(MARKER): return
    run(['systemctl','--user','disable','--now',UNIT])
    target.unlink()
    run(['systemctl','--user','daemon-reload'])
    # Keep search settings, cached image and data for a later reinstall.


if __name__=='__main__':
    import sys
    try:
        if len(sys.argv)!=2 or sys.argv[1] not in ('install','restore'): raise ValueError('Use install or restore.')
        (install if sys.argv[1]=='install' else restore)()
    except (OSError,ValueError,subprocess.CalledProcessError) as error:
        raise SystemExit('SearXNG setup failed: '+str(error)) from None
