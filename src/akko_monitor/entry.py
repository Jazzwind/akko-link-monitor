"""Command-line entry, stable single-instance IPC, and hidden launch policy."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import os
import hashlib
import sys
import tkinter as tk
from tkinter import messagebox
from . import identity
from .paths import DATA,prepare
from .startup import Registration,show_on_launch

def main(argv=None):
    p=argparse.ArgumentParser(description='AKKO Link Monitor')
    p.add_argument('--startup',action='store_true');p.add_argument('--record',action='store_true')
    p.add_argument('--no-record',action='store_true');p.add_argument('--reports',action='store_true')
    p.add_argument('--smoke-test',type=float,default=0)
    p.add_argument('--install-startup',action='store_true');p.add_argument('--uninstall-startup',action='store_true')
    p.add_argument('--etw-helper',action='store_true');p.add_argument('--folder')
    a=p.parse_args(argv)
    if a.etw_helper:
        if not a.folder:p.error('--etw-helper requires --folder')
        from .etw_reports import run_helper
        run_helper(a.folder);return 0
    if a.install_startup or a.uninstall_startup:
        Registration().set_registered(a.install_startup);return 0
    kernel=C.WinDLL('kernel32',use_last_error=True);user=C.WinDLL('user32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR];kernel.CreateMutexW.restype=W.HANDLE
    kernel.CloseHandle.argtypes=[W.HANDLE]
    user.FindWindowW.argtypes=[W.LPCWSTR,W.LPCWSTR];user.FindWindowW.restype=W.HWND
    user.RegisterWindowMessageW.argtypes=[W.LPCWSTR];user.RegisterWindowMessageW.restype=W.UINT
    user.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
    suffix='.'+hashlib.sha256(str(DATA).encode()).hexdigest()[:12] if os.environ.get('AKKO_MONITOR_DATA_DIR') else ''
    tray_class='AkkoLinkMonitor.Tray'+suffix
    C.set_last_error(0);mutex=kernel.CreateMutexW(None,False,'Local\\Akko3098NLinkMonitorGUI'+suffix)
    duplicate=C.get_last_error()==183
    if not mutex:raise C.WinError(C.get_last_error())
    if duplicate:
        if not a.startup:
            hwnd=user.FindWindowW(tray_class,None)
            if hwnd:user.PostMessageW(hwnd,user.RegisterWindowMessageW('AkkoLinkMonitor.Show'),0,0)
        kernel.CloseHandle(mutex);return 0
    root=None;app=None;tray=None
    try:
        prepare()
        try:identity.initialize()
        except (OSError,ValueError):identity.configure('')
        try:settings=json.loads((DATA/'settings.json').read_text(encoding='utf8'))
        except (OSError,ValueError):settings={}
        if not isinstance(settings,dict):settings={}
        visible=show_on_launch(settings.get('launch_mode','ManualWindowStartupTray'),a.startup)
        user.SetProcessDPIAware()
        root=tk.Tk();root.withdraw()  # Before construction or first event-loop turn.
        from .app import App
        from .tray import Tray
        app=App(root,a.smoke_test,not a.no_record)
        if app.closing:return 1
        tray=Tray(app.tray_events,tray_class)
        try:tray.start();app.attach_tray(tray)
        except Exception as exc:
            # A failed tray must never strand a hidden, unreachable process.
            visible=True;messagebox.showerror('托盘启动失败',str(exc),parent=root)
        if visible:root.deiconify()
        if a.reports and not a.startup:root.after(1000,app.start_reports)
        root.mainloop();return 0
    finally:
        if app and not app.closing:app.close()
        elif tray:tray.stop()
        kernel.CloseHandle(mutex)
