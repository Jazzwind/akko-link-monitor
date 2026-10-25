"""Real Windows visibility/IPC/tray checks; no hardware or OS key injection."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

root=Path(__file__).resolve().parents[1]
(root/'verification').mkdir(exist_ok=True)
u=C.WinDLL('user32',use_last_error=True)
u.FindWindowW.argtypes=[W.LPCWSTR,W.LPCWSTR];u.FindWindowW.restype=W.HWND
u.IsWindowVisible.argtypes=[W.HWND];u.IsWindowVisible.restype=W.BOOL
u.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
u.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
u.RegisterWindowMessageW.argtypes=[W.LPCWSTR];u.RegisterWindowMessageW.restype=W.UINT
HOOK=C.WINFUNCTYPE(None,W.HANDLE,W.DWORD,W.HWND,C.c_long,C.c_long,W.DWORD,W.DWORD)
u.SetWinEventHook.argtypes=[W.DWORD,W.DWORD,W.HMODULE,HOOK,W.DWORD,W.DWORD,W.DWORD];u.SetWinEventHook.restype=W.HANDLE
u.UnhookWinEvent.argtypes=[W.HANDLE]
shown=[];target=[None]
@HOOK
def event(hook,event,hwnd,obj,child,thread,stamp):
    if not hwnd or obj!=0:return
    pid=W.DWORD();u.GetWindowThreadProcessId(hwnd,C.byref(pid))
    if pid.value!=target[0]:return
    name=C.create_unicode_buffer(256);u.GetClassNameW(hwnd,name,256)
    if name.value=='TkTopLevel':shown.append((pid.value,stamp))
hook=u.SetWinEventHook(0x8002,0x8002,None,event,0,0,0)
if not hook:raise C.WinError(C.get_last_error())

def pump(seconds):
    end=time.monotonic()+seconds;msg=W.MSG()
    while time.monotonic()<end:
        while u.PeekMessageW(C.byref(msg),None,0,0,1):u.TranslateMessage(C.byref(msg));u.DispatchMessageW(C.byref(msg))
        time.sleep(.01)

def own_window(pid):
    found=[]
    callback_type=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    @callback_type
    def visit(hwnd,lp):
        owner=W.DWORD();u.GetWindowThreadProcessId(hwnd,C.byref(owner))
        if owner.value==pid:
            name=C.create_unicode_buffer(256);u.GetClassNameW(hwnd,name,256)
            if name.value=='TkTopLevel':found.append(hwnd);return False
        return True
    u.EnumWindows.argtypes=[callback_type,W.LPARAM];u.EnumWindows(visit,0)
    return found[0] if found else None

results=[]
try:
    cases=[('ManualWindowStartupTray',True,False),('AlwaysTray',False,False),
                                  ('AlwaysTray',True,False),('AlwaysWindow',True,True),
                                  ('AlwaysWindow',False,True),('ManualWindowStartupTray',False,True)]
    if '--quick' in sys.argv:cases=cases[:1]
    for mode,startup,expected in cases:
        with tempfile.TemporaryDirectory(prefix='桌面测试 ',dir=root/'verification') as folder:
            data=Path(folder);(data/'settings.json').write_text(json.dumps({'launch_mode':mode}),encoding='utf8')
            env=dict(os.environ,AKKO_MONITOR_DATA_DIR=str(data),PYTHONPATH=str(root/'src'))
            args=[sys.executable,str(root/'tests/desktop_fixture.py'),'--smoke-test','8']+(['--startup'] if startup else [])
            shown.clear();process=subprocess.Popen(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
            target[0]=process.pid
            try:
                cls='AkkoLinkMonitor.Tray.'+hashlib.sha256(str(data).encode()).hexdigest()[:12]
                for _ in range(150):
                    pump(.02);tray=u.FindWindowW(cls,None)
                    if tray:break
                if not tray:raise AssertionError('Tray not created: '+str(process.poll()))
                pump(.2);hwnd=own_window(process.pid)
                assert hwnd,'Fixture main window not found'
                assert bool(u.IsWindowVisible(hwnd))==expected,(mode,startup,'visibility')
                assert expected or not shown,(mode,startup,'initial show event')
                if mode=='ManualWindowStartupTray' and startup:
                    # Repeated startup must not show a hidden existing instance.
                    second=subprocess.run(args,env=env,timeout=6,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                    assert second.returncode==0
                    pump(.1);assert not u.IsWindowVisible(hwnd)
                    # Manual duplicate uses stable IPC, independent of version title.
                    second=subprocess.run([a for a in args if a!='--startup'],env=env,timeout=6,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                    assert second.returncode==0
                    pump(.2);assert u.IsWindowVisible(hwnd)
                    u.PostMessageW(hwnd,0x112,0xf020,0);pump(.2);assert not u.IsWindowVisible(hwnd)
                    u.PostMessageW(tray,u.RegisterWindowMessageW('AkkoLinkMonitor.Show'),0,0);pump(.2)
                    assert u.IsWindowVisible(hwnd)
                    # X hides; double-click callback marks without showing window.
                    u.PostMessageW(hwnd,0x10,0,0);pump(.15);assert not u.IsWindowVisible(hwnd)
                    u.PostMessageW(tray,0x8001,0,0x203);u.PostMessageW(tray,0x8001,0,0x202);pump(.2)
                    assert len((data/'manual-markers.jsonl').read_text(encoding='utf8').splitlines())==1
                    assert not u.IsWindowVisible(hwnd)
                    # Replay Explorer's restart message without restarting Explorer.
                    u.PostMessageW(tray,u.RegisterWindowMessageW('TaskbarCreated'),0,0);pump(.2)
                    assert process.poll() is None
                u.PostMessageW(tray,0x8001,0,0x203);u.PostMessageW(tray,0x8001,0,0x202);pump(.15)
                # Exit through the application's tray command queue, not forced kill.
                # Duration timer calls the same clean shutdown as tray Exit.
                while process.poll() is None:pump(.05)
                stdout,stderr=process.communicate(timeout=2)
                assert process.returncode==0,stderr.decode(errors='replace')
                assert not u.FindWindowW(cls,None)
                results.append({'mode':mode,'startup':startup,'expected_visible':expected,'passed':True})
            finally:
                if process.poll() is None:process.terminate();process.wait(3)
finally:u.UnhookWinEvent(hook)
out=root/'verification/desktop-results.json';out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(results,ensure_ascii=False))
