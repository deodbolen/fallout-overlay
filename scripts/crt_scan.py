"""Soft phosphor-style scan group, without global flashing."""
import math
import cairo

PERIOD=12.0
GROUP_HEIGHT=48
LINE_SPACING=6
LINE_WEIGHTS=(.4,.7,1,.7,.4)


def draw_scan(context,width,height,elapsed):
    phase=(elapsed%PERIOD)/PERIOD
    center=phase*(height+GROUP_HEIGHT)-GROUP_HEIGHT/2
    strength=.045*(1+.05*math.sin(elapsed*math.tau/1.7))
    # Extremely faint phosphor persistence behind the moving lines.
    trail=cairo.LinearGradient(0,center-22,0,center+22)
    trail.add_color_stop_rgba(0,.45,1,.35,0)
    trail.add_color_stop_rgba(.55,.45,1,.35,.006)
    trail.add_color_stop_rgba(1,.45,1,.35,0)
    context.set_source(trail); context.rectangle(0,center-22,width,44); context.fill()
    for index,weight in enumerate(LINE_WEIGHTS):
        y=center+(index-2)*LINE_SPACING
        glow=cairo.LinearGradient(0,y-2.5,0,y+2.5)
        glow.add_color_stop_rgba(0,.45,1,.35,0)
        glow.add_color_stop_rgba(.5,.45,1,.35,strength*weight*.3)
        glow.add_color_stop_rgba(1,.45,1,.35,0)
        context.set_source(glow); context.rectangle(0,y-2.5,width,5); context.fill()
        context.set_source_rgba(.45,1,.35,strength*weight)
        context.rectangle(0,y-.45,width,.9); context.fill()
