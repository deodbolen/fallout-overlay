"""Recognize navigator shortcuts even when terminal escape sequences split."""
SHORTCUTS={b'\x1b[1;5A':'previous',b'\x1b[1;5B':'next',b'\x1b[5A':'previous',b'\x1b[5B':'next',b'\x1d':'detach'}
SHORTCUTS.update({b'\x1b[1;6A':'previous',b'\x1b[1;6B':'next',
                  b'\x1b[1;6D':'section_previous',b'\x1b[1;6C':'section_next'})
SHORTCUTS.update({b'\x0f':'previous',b'\x10':'next'})
SHORTCUTS.update({b'\x1bOP':'previous',b'\x1bOQ':'next',
                  b'\x1b[11~':'previous',b'\x1b[12~':'next',
                  b'\x1b[[A':'previous',b'\x1b[[B':'next'})
SHORTCUTS.update({b'\x1b[5;2~':'scroll_up',b'\x1b[6;2~':'scroll_down',
                  b'\x1bOR':'scroll_up',b'\x1bOS':'scroll_down',
                  b'\x1b[13~':'scroll_up',b'\x1b[14~':'scroll_down'})
SHORTCUTS.update({b'\x1b[15~':'copy_view',b'\x1b[[E':'copy_view'})

class InputRouter:
    def __init__(self): self.pending=b''; self.pasting=False
    def feed(self,data):
        data=self.pending+data; self.pending=b''; forward=bytearray()
        while data:
            if self.pasting:
                marker=b'\x1b[201~'
                end=data.find(marker)
                if end>=0:
                    forward.extend(data[:end+len(marker)]);data=data[end+len(marker):]
                    self.pasting=False
                    continue
                keep=max((n for n in range(1,min(len(data),len(marker)-1)+1) if marker.startswith(data[-n:])),default=0)
                if keep:
                    forward.extend(data[:-keep]);self.pending=data[-keep:]
                else:forward.extend(data)
                break
            if data.startswith(b'\x1b[200~'):
                forward.extend(b'\x1b[200~');data=data[6:];self.pasting=True
                continue
            match=next((sequence for sequence in SHORTCUTS if data.startswith(sequence)),None)
            if match: return bytes(forward),SHORTCUTS[match],data[len(match):]
            if any(sequence.startswith(data) for sequence in (*SHORTCUTS,b'\x1b[200~')):
                self.pending=data; break
            forward.append(data[0]); data=data[1:]
        return bytes(forward),None,b''
    def flush(self):
        data=self.pending; self.pending=b''; return data
