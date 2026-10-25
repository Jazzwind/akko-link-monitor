"""Passive Windows BLE connection-status observer, separate from input silence."""
import json
from pathlib import Path
import subprocess
import threading
import time
from . import identity

class BluetoothMonitor:
    def __init__(self, events):
        self.events=events
        self.exit=threading.Event()
        self.process=None
        self.thread=threading.Thread(target=self.run,name='AkkoBluetooth',daemon=True)

    def start(self):self.thread.start()

    def run(self):
        try:
            if not identity.BT_ADDRESS:
                self.events.put(('bluetooth',{'connected':None},'尚未绑定 AKKO BT1'))
                return
            self.process=subprocess.Popen([
                'powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                '-File',str(Path(__file__).with_name('bluetooth_status.ps1')),'-Address',identity.BT_ADDRESS,'-ParentPid',str(__import__('os').getpid())],
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
                errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
            for line in self.process.stdout:
                if self.exit.is_set():break
                try:data=json.loads(line)
                except ValueError:continue
                data['observed_monotonic']=time.perf_counter()
                # Forward heartbeats too: UI can detect a stale observer.
                self.events.put(('bluetooth',data,data.get('error')))
            if not self.exit.is_set():
                self.events.put(('bluetooth',{'connected':None},'Bluetooth status observer stopped'))
        except Exception as exc:
            self.events.put(('bluetooth',{'connected':None},str(exc)))

    def stop(self):
        self.exit.set()
        if self.process and self.process.poll() is None:self.process.terminate()
        if self.thread.is_alive():self.thread.join(3)
