"""Aggregate only; scan codes live in memory until release or reset."""
from collections import deque

class Metrics:
    def __init__(self):
        self.downs = self.ups = self.repeats = self.orphans = 0
        self.pressed = {}
        self.intervals = deque(maxlen=10000)
        self.last_down = None
        self.last_event = None
        self.test_downs = 0
        self.long_holds = 0
        self.events_total = 0
        self.event_intervals = deque(maxlen=10000)

    def key(self, now, scan, flags):
        if self.last_event is not None:
            self.event_intervals.append((now-self.last_event)*1000)
        self.events_total += 1
        self.last_event = now
        identity = (scan, flags & 6)
        if flags & 1:
            self.ups += 1
            if identity not in self.pressed: self.orphans += 1
            else:
                if now - self.pressed[identity] > 5: self.long_holds += 1
                del self.pressed[identity]
        elif identity in self.pressed:
            self.repeats += 1
        else:
            self.downs += 1
            self.test_downs += 1
            self.pressed[identity] = now
            if self.last_down is not None: self.intervals.append((now - self.last_down) * 1000)
            self.last_down = now

    def reset_pressed(self):
        n = len(self.pressed)
        self.pressed.clear()
        self.last_down = None
        self.last_event = None
        return n

    def event_summary(self):
        values=sorted(self.event_intervals)
        return {'events_total':self.events_total,'last_ms':self.event_intervals[-1] if values else None,'min_ms':values[0] if values else None,'p50_ms':values[(len(values)-1)//2] if values else None,'p95_ms':values[int((len(values)-1)*.95)] if values else None,'max_ms':values[-1] if values else None}

    def p95(self):
        if not self.intervals: return None
        values = sorted(self.intervals)
        return values[min(len(values)-1, int((len(values)-1)*.95))]
