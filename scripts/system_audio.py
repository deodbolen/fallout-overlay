"""Control the desktop's default output through PulseAudio or PipeWire-Pulse."""
import os
import re
import subprocess


def pactl(*arguments):
    try:
        result=subprocess.run(['pactl',*arguments],capture_output=True,text=True,
                              timeout=3,env=dict(os.environ,LC_ALL='C'))
    except FileNotFoundError:
        raise ValueError('System volume requires pulseaudio-utils. Run the installer.') from None
    except subprocess.TimeoutExpired:
        raise ValueError('The desktop audio server did not respond.') from None
    if result.returncode:
        raise ValueError('System audio unavailable: '+result.stderr.strip())
    return result.stdout


def status():
    levels=re.findall(r'(\d+)%',pactl('get-sink-volume','@DEFAULT_SINK@'))
    if not levels: raise ValueError('Could not read system output volume.')
    return max(map(int,levels)),pactl('get-sink-mute','@DEFAULT_SINK@').strip().endswith('yes')


def set_volume(value):
    value=int(value)
    if not 0<=value<=100: raise ValueError('Enter a volume from 0 to 100.')
    pactl('set-sink-volume','@DEFAULT_SINK@',str(value)+'%')


def toggle_mute():
    pactl('set-sink-mute','@DEFAULT_SINK@','toggle')
