"""Short green static burst and scan sweep for Pip-Boy section changes."""
import curses
import random
import time


def animate(screen,redraw):
    rng=random.Random()
    for frame in range(6):
        redraw()
        height,width=screen.getmaxyx()
        if height<5 or width<3: break
        fade=1-frame/6
        # Sparse phosphor interference fades as the new section locks into place.
        count=int((height-3)*(width-1)*.045*fade*fade)
        for _ in range(count):
            y=rng.randrange(2,height-2); x=rng.randrange(width-1)
            try: screen.addstr(y,x,rng.choice('···─░'),curses.A_DIM)
            except curses.error: pass
        scan=2+int((height-5)*frame/5)
        try:
            screen.addnstr(scan,0,'─'*(width-1),width-1,curses.A_DIM)
            for _ in range(3):
                x=rng.randrange(max(1,width-8))
                screen.addnstr(scan,x,'━'*rng.randint(2,7),width-x-1,curses.A_BOLD)
        except curses.error: pass
        screen.refresh()
        time.sleep(.025)
    redraw() # Restore the clean screen without consuming queued navigation keys.
