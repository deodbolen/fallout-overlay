"""Recognize navigator shortcuts even when terminal escape sequences split."""
SHORTCUTS={b'\x1b[1;5A':'previous',b'\x1b[1;5B':'next',b'\x1b[5A':'previous',b'\x1b[5B':'next',b'\x1d':'detach'}
SHORTCUTS.update({b'\x1b[1;6A':'previous',b'\x1b[1;6B':'next',
                  b'\x1b[1;6D':'section_previous',b'\x1b[1;6C':'section_next'})
SHORTCUTS.update({b'\x0f':'previous',b'\x10':'next'})
SHORTCUTS.update({b'\x1bOP':'previous',b'\x1bOQ':'next',
                  b'\x1b[11~':'previous',b'\x1b[12~':'next',
                  b'\x1b[[A':'previous',b'\x1b[[B':'next'})

class InputRouter:
    def __init__(self): self.pending=b''
    def feed(self,data):
        data=self.pending+data; self.pending=b''; forward=bytearray()
        while data:
            match=next((sequence for sequence in SHORTCUTS if data.startswith(sequence)),None)
            if match: return bytes(forward),SHORTCUTS[match],data[len(match):]
            if any(sequence.startswith(data) for sequence in SHORTCUTS):
                self.pending=data; break
            forward.append(data[0]); data=data[1:]
        return bytes(forward),None,b''
    def flush(self):
        data=self.pending; self.pending=b''; return data
