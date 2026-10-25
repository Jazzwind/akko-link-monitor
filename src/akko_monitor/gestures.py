"""Tray-only gesture state. No keyboard hooks or ordinary mouse history."""
class Gestures:
    def __init__(self,emit,threshold=1.0):
        self.emit=emit;self.threshold=threshold;self.started=None;self.wall=None;self.double=False;self.ready=False
    def down(self,wall,mono,double=False):
        if self.started is None:self.started=mono;self.wall=wall;self.ready=False
        self.double=self.double or double
    def tick(self,mono):
        if self.started is not None and not self.ready and mono-self.started>=self.threshold:
            self.ready=True;self.emit(('tray_hold_ready',self.wall,self.started))
    def up(self,wall,mono):
        if self.started is None:return
        duration=max(0,mono-self.started)
        if duration>=self.threshold:self.emit(('tray_hold',self.wall,self.started,wall,mono,duration))
        elif self.double:self.emit(('tray_mark',self.wall,self.started))
        self.started=None;self.double=False;self.ready=False
    def cancel(self):
        if self.ready:self.emit(('tray_hold_cancelled',))
        self.started=None;self.double=False;self.ready=False
