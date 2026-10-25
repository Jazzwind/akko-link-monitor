"""Low-rate hardware requests off the UI thread."""
import queue
import threading
import time
from .battery import read_power
from .usb_info import query_usb
from .bluetooth_battery import read_cached_battery

class Telemetry:
    def __init__(self):
        self.events=queue.Queue();self.wake=threading.Event();self.exit=threading.Event()
        self.thread=threading.Thread(target=self.run,name='AkkoTelemetry',daemon=True)
        self.battery_enabled=threading.Event();self.battery_enabled.set()

    def start(self):self.thread.start()

    def run(self):
        while not self.exit.is_set():
            retry=False
            for kind,fn in [('usb',query_usb),('bt_battery',read_cached_battery),('battery',read_power)]:
                if self.exit.is_set():break
                if kind=='battery' and not self.battery_enabled.is_set():continue
                requested=time.perf_counter()
                try:
                    data=fn()
                    if kind=='battery':data.update(probe_started_monotonic=requested,probe_completed_monotonic=time.perf_counter())
                    self.events.put((kind,data,None))
                except Exception as exc:
                    retry=kind=='battery' and isinstance(exc,TimeoutError)
                    self.events.put((kind,{'error_kind':type(exc).__name__,'probe_started_monotonic':requested,'probe_completed_monotonic':time.perf_counter()},str(exc)))
            self.wake.wait(5 if retry else 30);self.wake.clear()

    def refresh(self):self.wake.set()

    def set_battery_enabled(self,enabled):
        if enabled:self.battery_enabled.set()
        else:self.battery_enabled.clear()
        self.wake.set()

    def stop(self):
        self.exit.set();self.wake.set();self.thread.join(4)
