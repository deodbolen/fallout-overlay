#!/usr/bin/env python3
"""One-shot XFCE genmon collector; no background worker."""
import os, time, json, pathlib, shutil, html, subprocess
P = pathlib.Path

def sample():
    cpu = list(map(int, P('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    disks = {}
    for line in P('/proc/diskstats').read_text().splitlines():
        v = line.split(); name = v[2]
        if (P('/sys/block') / name).exists() and not name.startswith(('loop', 'ram', 'dm-')):
            disks[name] = [int(v[5])*512, int(v[9])*512]
    net = {}
    for line in P('/proc/net/dev').read_text().splitlines()[2:]:
        name, values = line.split(':'); v = values.split()
        if name.strip() != 'lo': net[name.strip()] = [int(v[0]), int(v[8])]
    return {'time': time.monotonic(), 'cpu': cpu, 'disk': disks, 'net': net}

def rates(cur, old, dt):
    return [sum(max(0, v[i]-old.get(k,v)[i]) for k,v in cur.items())/dt for i in (0,1)]

def human(n):
    for unit in ('B','K','M','G','T'):
        if n < 1024: return f'{n:.0f}{unit}'
        n /= 1024
    return f'{n:.0f}P'

def render():
    cache = P(os.environ.get('XDG_CACHE_HOME', str(P.home()/'.cache'))) / 'fallout-ui'
    cache.mkdir(parents=True, exist_ok=True)
    state = cache/'metrics.json'; now = sample()
    try: old = json.loads(state.read_text())
    except (OSError, ValueError): old = now
    state.with_suffix('.tmp').write_text(json.dumps(now)); state.with_suffix('.tmp').replace(state)
    dt = max(.001, now['time']-old['time'])
    total = sum(now['cpu'])-sum(old['cpu']); idle = sum(now['cpu'][3:5])-sum(old['cpu'][3:5])
    cpu = max(0,min(100,100*(1-idle/total))) if total > 0 else 0
    mem = {a: int(b.split()[0])*1024 for a,b in (line.split(':',1) for line in P('/proc/meminfo').read_text().splitlines())}
    used = mem['MemTotal']-mem['MemAvailable']; ram = used/mem['MemTotal']*100
    disk = shutil.disk_usage(P.home()); dr,dw = rates(now['disk'],old['disk'],dt); nr,nw = rates(now['net'],old['net'],dt)
    width = 1920
    try:
        result = subprocess.run(['xrandr','--current'],capture_output=True,text=True,timeout=1)
        import re
        match = re.search(r'current (\d+) x',result.stdout)
        if match: width = int(match[1])
    except (OSError,subprocess.TimeoutExpired): pass
    compact = width < 1500
    parts = [f'CPU {cpu:.0f}%',f'RAM {ram:.0f}%',f'FREE {human(disk.free)}',f'IO {human(dr)}/{human(dw)}',f'NET {human(nr)}/{human(nw)}']
    details = [f'CPU utilization: {cpu:.1f}%',f'Memory: {human(used)} / {human(mem["MemTotal"])}',f'Home filesystem: {human(disk.free)} free / {human(disk.total)}',f'Physical disk read / write: {human(dr)}/s / {human(dw)}/s',f'Network receive / send (excluding loopback): {human(nr)}/s / {human(nw)}/s']
    temps = []
    for sensor in P('/sys/class/hwmon').glob('hwmon*'):
        try:
            if (sensor/'name').read_text().strip() not in ('coretemp','k10temp','zenpower','cpu_thermal'): continue
            temps.extend(int(p.read_text())/1000 for p in sensor.glob('temp*_input'))
        except (OSError,ValueError): pass
    if temps: parts.append(f'{max(temps):.0f}°C'); details.append(f'CPU temperature: {max(temps):.1f}°C')
    for battery in P('/sys/class/power_supply').glob('*'):
        try:
            if (battery/'type').read_text().strip() == 'Battery':
                cap = (battery/'capacity').read_text().strip(); status = (battery/'status').read_text().strip()
                parts.append(f'BAT {cap}%'); details.append(f'Battery: {cap}% ({status})')
        except OSError: pass
    if compact: parts = [s.replace('CPU ','C ').replace('RAM ','M ').replace('FREE ','D ').replace('NET ','N ') for s in parts]
    print('<txt>'+html.escape('  |  '.join(parts))+'</txt><tool>'+html.escape('\n'.join(details))+'</tool>')
if __name__ == '__main__': render()
