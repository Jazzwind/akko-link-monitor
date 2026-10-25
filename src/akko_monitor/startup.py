"""Current-user Startup shortcut; never modify Windows StartupApproved."""
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import winreg
from .paths import PROJECT

MODES={'AlwaysWindow':'不隐藏','ManualWindowStartupTray':'仅开机自启动时隐藏','AlwaysTray':'每次启动时隐藏'}

def show_on_launch(mode,startup):
    return mode=='AlwaysWindow' or (mode=='ManualWindowStartupTray' and not startup)

def parse_approval(value):
    if value is None:return 'not_recorded'
    if not isinstance(value,bytes) or len(value)!=12:return 'unknown'
    code=int.from_bytes(value[:4],'little')
    return 'enabled' if code in (2,6) else 'disabled' if code in (3,7) else 'unknown'

@dataclass
class State:
    registered: bool
    approval: str
    @property
    def label(self):
        if not self.registered:return '开机自启动（未注册）'
        return {'disabled':'开机自启动（任务管理器已禁用）','unknown':'开机自启动（系统状态未知）',
                'unreadable':'开机自启动（状态读取失败）'}.get(self.approval,'开机自启动')

class Registration:
    def __init__(self,folder=None,key=None):
        self.shortcut=Path(folder or Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup')/'AkkoLinkMonitor.lnk'
        self.key=key or r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder'

    def read(self):
        if not self.shortcut.exists():return State(False,'not_recorded')
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.key,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as k:
                value,_=winreg.QueryValueEx(k,self.shortcut.name)
            return State(True,parse_approval(value))
        except FileNotFoundError:return State(True,'not_recorded')
        except OSError:return State(True,'unreadable')

    def set_registered(self,enabled):
        if not enabled:
            self.shortcut.unlink(missing_ok=True);return
        launcher=ensure_launcher()
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
            '-File',str(PROJECT/'scripts/manage-startup.ps1'),'-Destination',str(self.shortcut),
            '-Launcher',str(launcher)],
            check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)

def ensure_launcher():
    launcher=PROJECT/'bin/AkkoLinkMonitor.exe'
    source=PROJECT/'scripts/AkkoLinkMonitor.cs'
    if not launcher.exists() or launcher.stat().st_mtime<source.stat().st_mtime:
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
            '-File',str(PROJECT/'scripts/build-launcher.ps1')],check=True,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    return launcher
