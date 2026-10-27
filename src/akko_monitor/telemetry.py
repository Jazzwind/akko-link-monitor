"""Low-rate hardware requests off the UI thread."""
import queue
import threading
import time
from .battery import read_power
from .usb_info import query_usb
from .bluetooth_battery import read_cached_battery

RF_IDLE_SECONDS = 15

class Telemetry:
    def __init__(self):
        self.events=queue.Queue();self.wake=threading.Event();self.exit=threading.Event()
        self.thread=threading.Thread(target=self.run,name='AkkoTelemetry',daemon=True)
        self.battery_enabled=threading.Event()
        self.last_rf_input=None
        self.manual_power_requests=queue.Queue()
        self.usb_requests=queue.Queue()

    def battery_allowed(self,now=None):
        now=time.perf_counter() if now is None else now
        return (self.battery_enabled.is_set() and self.last_rf_input is not None
                and 0 <= now-self.last_rf_input < RF_IDLE_SECONDS)

    def note_rf_input(self,observed_at):
        # Only physical state changes count. Query replies and repeated keydown
        # events must never extend the keyboard's activity window.
        was_allowed=self.battery_allowed()
        if self.last_rf_input is None or observed_at>self.last_rf_input:
            self.last_rf_input=observed_at
        if not was_allowed and self.battery_allowed():self.wake.set()

    def start(self):self.thread.start()

    def run(self):
        while not self.exit.is_set():
            self.wake.clear()
            retry=False
            for kind,fn in [('usb',query_usb),('bt_battery',read_cached_battery),('battery',read_power)]:
                if self.exit.is_set():break
                if kind=='usb':
                    try:self.usb_requests.get_nowait()
                    except queue.Empty:continue
                manual=False
                if kind=='battery':
                    try:self.manual_power_requests.get_nowait();manual=True
                    except queue.Empty:pass
                # Check here too: the UI may be blocked or a retry/refresh may
                # wake this thread after the idle deadline has passed.
                if kind=='battery' and not manual and not self.battery_allowed():continue
                requested=time.perf_counter()
                try:
                    data=fn()
                    if kind=='battery':data.update(probe_started_monotonic=requested,probe_completed_monotonic=time.perf_counter(),manual_query=manual)
                    self.events.put((kind,data,None))
                except Exception as exc:
                    retry=kind=='battery' and not manual and isinstance(exc,TimeoutError)
                    self.events.put((kind,{'error_kind':type(exc).__name__,'probe_started_monotonic':requested,'probe_completed_monotonic':time.perf_counter(),'manual_query':manual},str(exc)))
            self.wake.wait(0 if not self.manual_power_requests.empty() or not self.usb_requests.empty() else 5 if retry else 30)

    def refresh(self):self.wake.set()

    def refresh_power_once(self):
        # Explicit action, independent of automatic policy. Never updates the
        # input deadline, enables recurring polls, or retries a failed request.
        self.manual_power_requests.put(True);self.wake.set()

    def set_battery_enabled(self,enabled):
        changed=enabled!=self.battery_enabled.is_set()
        if enabled:self.battery_enabled.set()
        else:self.battery_enabled.clear()
        if changed:self.wake.set()

    def refresh_usb_once(self):
        # Descriptor requests are hardware I/O, not passive cache reads.
        self.usb_requests.put(True);self.wake.set()

    def stop(self):
        self.exit.set();self.wake.set();self.thread.join(4)
