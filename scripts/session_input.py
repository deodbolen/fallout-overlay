"""Recognize navigator shortcuts even when terminal escape sequences split."""
SHORTCUTS={b'\x1b[1;5A':'previous',b'\x1b[1;5B':'next',b'\x1b[5A':'previous',b'\x1b[5B':'next',b'\x1d':'detach'}

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
