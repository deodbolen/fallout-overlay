"""Bounded, nonblocking Fallout sound playback; never receives typed text."""
from pathlib import Path
import random
import time
import gi
import sound_settings
gi.require_version('Gst','1.0')
from gi.repository import Gst
Gst.init(None)
ROOT=Path(__file__).resolve().parent.parent/'fallout-sounds'
FILES={'fan':'fansound/ui_hacking_fanhum_lp.wav','type':'Menu-sounds/ui_hacking_charscroll_lp.wav','load':'load/ui_loadscreen_initial.wav','good':'password/ui_hacking_passgood.wav','bad':'password/ui_hacking_passbad.wav','focus':'Menu-sounds/ui_menu_focus.wav','ok':'Menu-sounds/ui_menu_ok.wav','cancel':'Menu-sounds/ui_menu_cancel.wav','select':'pip-boy-sounds/ui_pipboy_select.wav','scroll':'pip-boy-sounds/ui_pipboy_scroll.wav'}
class Sounds:
    def __init__(self): self.players={}; self.last={}; self.levels=sound_settings.levels()
    def play(self,event,loop=False):
        now=time.monotonic()
        if now-self.last.get(event,0)<(.085 if event=='type' else .06): return
        self.last[event]=now
        self.stop(event)
        paths=sorted((ROOT/'static-sounds').glob('ui_static_*.wav')) if event=='static' else [ROOT/FILES[event]] if event in FILES else []
        if not paths: return
        path=random.choice(paths)
        if not path.is_file(): return
        player=Gst.ElementFactory.make('playbin',None)
        if player is None: return
        player.set_property('uri',path.as_uri()); player.set_property('volume',self.volume(event))
        bus=player.get_bus(); bus.add_signal_watch()
        def message(bus,message):
            if message.type==Gst.MessageType.EOS and loop:
                player.seek_simple(Gst.Format.TIME,Gst.SeekFlags.FLUSH,0)
                player.set_state(Gst.State.PLAYING)
            elif message.type in (Gst.MessageType.EOS,Gst.MessageType.ERROR): self.stop(event)
        handler=bus.connect('message',message)
        self.players[event]=(player,bus,handler); player.set_state(Gst.State.PLAYING)
    def volume(self,event):
        return self.levels['fan_volume' if event=='fan' else 'effects_volume']/100
    def refresh(self):
        self.levels=sound_settings.levels()
        for event,(player,bus,handler) in self.players.items():
            player.set_property('volume',self.volume(event))
        return True
    def stop(self,event):
        record=self.players.pop(event,None)
        if record:
            player,bus,handler=record; bus.disconnect(handler); bus.remove_signal_watch(); player.set_state(Gst.State.NULL)
    def close(self):
        for event in list(self.players): self.stop(event)
