"""Read-only Linux system dashboard; procfs rates use monotonic sample deltas."""
import os
from pathlib import Path
import platform
import shutil
import socket
import struct
import time
import textwrap


def read(path):
    try: return Path(path).read_text().strip()
    except OSError: return ''


def size(value):
    for unit in ('B','KiB','MiB','GiB','TiB','PiB'):
        if abs(value)<1024: return f'{value:.1f} {unit}'
        value/=1024
    return f'{value:.1f} EiB'


def rate(current,previous,seconds):
    if previous is None or seconds<=0 or current<previous: return None
    return (current-previous)/seconds


def cpu_percent(current,previous):
    if previous is None or any(a<b for a,b in zip(current,previous)): return None
    delta=[a-b for a,b in zip(current,previous)]
    total=sum(delta)
    return max(0,min(100,100*(total-delta[3]-delta[4])/total)) if total>0 else 0


def percent(value):
    if value is None: return 'sampling…'
    return f'{value:5.1f}%'


def meter(value,width=12):
    filled=round(width*max(0,min(100,value or 0))/100)
    return '['+'#'*filled+'-'*(width-filled)+']'


class SystemDashboard:
    def __init__(self):
        self.last=None
        self.sample_time=None
        self.cached=[]
        info=read('/proc/cpuinfo')
        self.model=next((line.split(':',1)[1].strip() for line in info.splitlines()
                         if line.startswith(('model name','Hardware'))),'Unknown CPU')
        self.hostname=socket.gethostname()
        self.kernel=platform.release()
        try: self.distribution=platform.freedesktop_os_release().get('PRETTY_NAME','Linux')
        except (OSError,AttributeError): self.distribution=platform.system()

    def sample(self):
        cpus={}
        tasks={}
        for line in read('/proc/stat').splitlines():
            parts=line.split()
            if parts and parts[0].startswith('cpu'):
                # Guest times are already counted in user/nice; never add them twice.
                counters=list(map(int,parts[1:9]))
                cpus[parts[0]]=counters+[0]*(8-len(counters))
            elif len(parts)==2 and parts[0] in ('ctxt','processes','procs_running','procs_blocked'):
                tasks[parts[0]]=int(parts[1])
        memory={}
        for line in read('/proc/meminfo').splitlines():
            key,value=line.split(':',1)
            memory[key]=int(value.split()[0])*1024
        disks={}
        for line in read('/proc/diskstats').splitlines():
            fields=line.split()
            if len(fields)<14: continue
            name=fields[2]
            if not (Path('/sys/block')/name).exists() or name.startswith(('loop','ram','zram','dm-')): continue
            disks[name]=(int(fields[5])*512,int(fields[9])*512,
                         int(fields[3])+int(fields[7]),int(fields[12]))
        networks={}
        for line in read('/proc/net/dev').splitlines()[2:]:
            name,data=line.split(':',1)
            name=name.strip(); values=data.split()
            if name=='lo' or len(values)<16: continue
            networks[name]=(int(values[0]),int(values[8]),int(values[2])+int(values[10]),int(values[3])+int(values[11]))
        vm={}
        for line in read('/proc/vmstat').splitlines():
            key,value=line.split()
            if key in ('pswpin','pswpout'): vm[key]=int(value)*os.sysconf('SC_PAGE_SIZE')
        return {'time':time.monotonic(),'cpus':cpus,'memory':memory,'disks':disks,
                'networks':networks,'tasks':tasks,'vm':vm}

    def lines(self,width=100):
        now=time.monotonic()
        if self.sample_time is not None and now-self.sample_time<1: return self.cached
        sample=self.sample()
        old=self.last or {}
        seconds=sample['time']-old.get('time',sample['time'])
        cpus=sample['cpus']; memory=sample['memory']; tasks=sample['tasks']
        lines=[f'{self.hostname}  |  {self.distribution}  |  {self.kernel}',self.model,'']
        uptime=read('/proc/uptime').split()
        if uptime:
            minutes=int(float(uptime[0]))//60
            lines.append(f'UPTIME  {minutes//1440}d {minutes//60%24}h {minutes%60}m')
        load=read('/proc/loadavg').split()
        if len(load)>=4: lines.append('LOAD  1m '+load[0]+'  5m '+load[1]+'  15m '+load[2]+'  |  Running / threads '+load[3])
        lines+=['','CPU  |  utilization per logical core']
        cores=[]
        for name,counters in cpus.items():
            usage=cpu_percent(counters,old.get('cpus',{}).get(name))
            label='TOTAL' if name=='cpu' else 'Core '+name[3:]
            entry=f'{label:>8}  {meter(usage)} {percent(usage)}'
            if name=='cpu':
                previous=old.get('cpus',{}).get(name)
                delta=[a-b for a,b in zip(counters,previous)] if previous else []
                if delta and sum(delta)>0:
                    entry+=f'  wait {100*delta[4]/sum(delta):.1f}%  steal {100*delta[7]/sum(delta):.1f}%'
            if name=='cpu': lines.append(entry)
            else: cores.append(entry)
        columns=max(1,min(4,width//36))
        for start in range(0,len(cores),columns):
            lines.append('  '.join(entry.ljust(34) for entry in cores[start:start+columns]).rstrip())
        if not cpus: lines.append('CPU statistics unavailable')
        frequencies=[]
        for line in read('/proc/cpuinfo').splitlines():
            if line.startswith('cpu MHz'):
                try: frequencies.append(float(line.split(':',1)[1]))
                except ValueError: pass
        if frequencies:
            lines.append(f'CPU clock avg {sum(frequencies)/len(frequencies):.0f} MHz  |  Range {min(frequencies):.0f}–{max(frequencies):.0f} MHz')
        lines+=['', 'MEMORY / SWAP']
        total=memory.get('MemTotal',0)
        if total:
            available=memory.get('MemAvailable',memory.get('MemFree',0))
            used=total-available
            lines.append(f'RAM   {meter(100*used/total)} {100*used/total:.1f}%  {size(used)} / {size(total)}')
            lines.append(f'Available {size(available)}  |  Cached {size(memory.get("Cached",0))}  |  Buffers {size(memory.get("Buffers",0))}')
            lines.append(f'Dirty {size(memory.get("Dirty",0))}  |  Slab {size(memory.get("Slab",0))}')
        else: lines.append('Memory statistics unavailable')
        swap=memory.get('SwapTotal',0); swap_used=swap-memory.get('SwapFree',0)
        lines.append(f'SWAP  {100*swap_used/swap:.1f}%  {size(swap_used)} / {size(swap)}' if swap else 'SWAP  Not configured')
        def speed(current,previous):
            value=rate(current,previous,seconds)
            return size(value)+'/s' if value is not None else 'sampling…'
        if sample['vm']:
            lines.append('Swap I/O  in '+speed(sample['vm'].get('pswpin',0),old.get('vm',{}).get('pswpin'))+
                         '  out '+speed(sample['vm'].get('pswpout',0),old.get('vm',{}).get('pswpout')))
        lines+=['','DISK I/O  |  whole devices, read / write']
        for name,values in sample['disks'].items():
            previous=old.get('disks',{}).get(name)
            before=previous or (None,)*4
            iops=rate(values[2],before[2],seconds)
            busy=rate(values[3],before[3],seconds)
            lines.append(name+'  R '+speed(values[0],before[0])+'  W '+speed(values[1],before[1])+
                         ('  '+f'{iops:.0f} IOPS  busy {min(100,busy/10):.1f}%' if iops is not None and busy is not None else ''))
        if not sample['disks']: lines.append('No physical disk counters available')
        lines+=['','FILESYSTEMS  |  used / total, free']
        mounts=['/']
        for line in read('/proc/mounts').splitlines():
            parts=line.split()
            if len(parts)>2 and parts[0].startswith('/dev/') and parts[1]!='/' and parts[2] not in ('squashfs','iso9660'):
                mounts.append(parts[1].replace('\\040',' ').replace('\\134','\\'))
        for path in dict.fromkeys(mounts):
            try:
                disk=shutil.disk_usage(path)
                lines.append(f'{path}  {100*disk.used/disk.total:.1f}%  {size(disk.used)} / {size(disk.total)}  free {size(disk.free)}')
            except OSError: continue
        lines+=['','NETWORK  |  receive / transmit']
        for name,values in sample['networks'].items():
            before=old.get('networks',{}).get(name,(None,)*4)
            state=read('/sys/class/net/'+name+'/operstate') or 'unknown'
            lines.append(name+' ['+state+']  RX '+speed(values[0],before[0])+'  TX '+speed(values[1],before[1]))
            lines.append('  Totals RX '+size(values[0])+'  TX '+size(values[1])+f'  errors {values[2]}  dropped {values[3]}')
        if not sample['networks']: lines.append('No network interfaces available')
        for line in read('/proc/net/route').splitlines()[1:]:
            fields=line.split()
            if len(fields)>3 and fields[1]=='00000000' and int(fields[3],16)&2:
                gateway=socket.inet_ntoa(struct.pack('<I',int(fields[2],16)))
                lines.append('Default gateway '+gateway+' via '+fields[0])
        lines+=['','SENSORS / TASKS']
        for hwmon in sorted(Path('/sys/class/hwmon').glob('hwmon*')):
            name=read(hwmon/'name') or hwmon.name
            for sensor in sorted(hwmon.glob('temp*_input')):
                value=read(sensor)
                try: temperature=int(value)/1000
                except ValueError: continue
                label=read(sensor.with_name(sensor.name.replace('_input','_label'))) or sensor.stem
                lines.append(f'{name} / {label}: {temperature:.1f} °C')
            for fan in sorted(hwmon.glob('fan*_input')):
                value=read(fan)
                if value: lines.append(f'{name} / {fan.stem}: {value} RPM')
        lines.append(f'Logical CPUs {max(0,len(cpus)-1)}  |  Runnable {tasks.get("procs_running","?")}  |  Blocked {tasks.get("procs_blocked","?")}')
        context_rate=rate(tasks.get('ctxt',0),old.get('tasks',{}).get('ctxt'),seconds)
        forks=rate(tasks.get('processes',0),old.get('tasks',{}).get('processes'),seconds)
        if context_rate is not None and forks is not None:
            lines.append(f'Context switches {context_rate:.0f}/s  |  New processes {forks:.1f}/s')
        pressures=[]
        for resource in ('cpu','memory','io'):
            values=[]
            for line in read('/proc/pressure/'+resource).splitlines():
                parts=line.split()
                average=next((part[6:] for part in parts[1:] if part.startswith('avg10=')),None)
                if average is not None: values.append(parts[0]+' '+average+'%')
            if values: pressures.append(resource.upper()+': '+', '.join(values))
        if pressures: lines+=['','PRESSURE  |  stalled task time, 10-second average']+pressures
        for supply in sorted(Path('/sys/class/power_supply').glob('*')):
            if read(supply/'type')=='Battery':
                lines.append('BATTERY  '+read(supply/'capacity')+'%  '+read(supply/'status'))
        self.last=sample; self.sample_time=now
        self.cached=[part for line in lines for part in (textwrap.wrap(line,max(10,width-1),replace_whitespace=False) or [''])]
        return self.cached
