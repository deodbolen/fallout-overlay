"""Keep unknown Alt/Option escape sequences out of navigator actions."""
import curses


def read_key(screen):
    key=screen.get_wch()
    if key!='\x1b': return key
    delay=screen.getdelay()
    screen.timeout(30)
    try:
        try: following=screen.get_wch()
        except curses.error: return key  # A standalone Escape still cancels.
        # Some terminals encode Alt+arrow as Escape followed by an arrow's
        # ordinary Escape sequence. Drain it as one unassigned combination.
        while following=='\x1b':
            try: following=screen.get_wch()
            except curses.error: return -1
        if following in ('[','O'):
            for _ in range(32):
                try: part=screen.get_wch()
                except curses.error: break
                if isinstance(part,int) or (isinstance(part,str) and '@'<=part<='~'):
                    break
        return -1
    finally:
        screen.timeout(delay)
