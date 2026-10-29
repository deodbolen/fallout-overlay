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
        alt_prefix=following=='\x1b'
        while following=='\x1b':
            try: following=screen.get_wch()
            except curses.error: return -1
        if following in ('[','O'):
            sequence=following
            for _ in range(32):
                try: part=screen.get_wch()
                except curses.error: break
                if isinstance(part,str): sequence+=part
                if isinstance(part,int) or (isinstance(part,str) and '@'<=part<='~'):
                    break
            if not alt_prefix:
                recognized={'[1;2A':'select_up','[1;2B':'select_down',
                            '[1;5D':('section','ctrl',-1),'[1;5C':('section','ctrl',1),
                            '[1;6D':('section','ctrlshift',-1),'[1;6C':('section','ctrlshift',1),
                            '[1;9D':('section','super',-1),'[1;9C':('section','super',1)}
                if sequence in recognized: return recognized[sequence]
        return -1
    finally:
        screen.timeout(delay)
