"""Native numeric notification icon. No Tk calls from this message thread."""
import ctypes as C
from ctypes import wintypes as W
import queue
import threading
import uuid
import time
from .gestures import Gestures
from .raw_input import WindowClass,PROC
from .devices import GUID

u=C.WinDLL('user32',use_last_error=True);g=C.WinDLL('gdi32',use_last_error=True)
s=C.WinDLL('shell32',use_last_error=True);k=C.WinDLL('kernel32',use_last_error=True)
class Notify(C.Structure):
    _fields_=[('size',W.DWORD),('hwnd',W.HWND),('id',W.UINT),('flags',W.UINT),
      ('callback',W.UINT),('icon',W.HICON),('tip',W.WCHAR*128),('state',W.DWORD),
      ('state_mask',W.DWORD),('info',W.WCHAR*256),('version',W.UINT),('title',W.WCHAR*64),
      ('info_flags',W.DWORD),('guid',GUID),('balloon',W.HICON)]
class IconInfo(C.Structure):
    _fields_=[('is_icon',W.BOOL),('x',W.DWORD),('y',W.DWORD),('mask',W.HBITMAP),('color',W.HBITMAP)]
class IconIdentifier(C.Structure):
    _fields_=[('size',W.DWORD),('hwnd',W.HWND),('id',W.UINT),('guid',GUID)]

def signatures():
    for name,args,rest in [
      ('CreateWindowExW',[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p],W.HWND),
      ('DefWindowProcW',[W.HWND,W.UINT,W.WPARAM,W.LPARAM],C.c_ssize_t),
      ('RegisterClassW',[C.POINTER(WindowClass)],W.ATOM),
      ('RegisterWindowMessageW',[W.LPCWSTR],W.UINT),
      ('PostMessageW',[W.HWND,W.UINT,W.WPARAM,W.LPARAM],W.BOOL),
      ('DestroyWindow',[W.HWND],W.BOOL),('DestroyIcon',[W.HICON],W.BOOL),
      ('CreateIconIndirect',[C.POINTER(IconInfo)],W.HICON),('GetDC',[W.HWND],W.HDC),
      ('ReleaseDC',[W.HWND,W.HDC],C.c_int),('FillRect',[W.HDC,C.POINTER(W.RECT),W.HBRUSH],C.c_int),
      ('DrawTextW',[W.HDC,W.LPCWSTR,C.c_int,C.POINTER(W.RECT),W.UINT],C.c_int),
      ('CreatePopupMenu',[],W.HMENU),('AppendMenuW',[W.HMENU,W.UINT,C.c_size_t,W.LPCWSTR],W.BOOL),
      ('DestroyMenu',[W.HMENU],W.BOOL),('SetForegroundWindow',[W.HWND],W.BOOL),
      ('GetCursorPos',[C.POINTER(W.POINT)],W.BOOL),
      ('TrackPopupMenu',[W.HMENU,W.UINT,C.c_int,C.c_int,C.c_int,W.HWND,C.c_void_p],W.UINT),
      ('GetMessageW',[C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT],W.BOOL),
      ('TranslateMessage',[C.POINTER(W.MSG)],W.BOOL),('DispatchMessageW',[C.POINTER(W.MSG)],C.c_ssize_t),
      ('UnregisterClassW',[W.LPCWSTR,W.HINSTANCE],W.BOOL)]:
        fn=getattr(u,name);fn.argtypes=args;fn.restype=rest
    for name,args,rest in [
      ('CreateCompatibleDC',[W.HDC],W.HDC),('CreateCompatibleBitmap',[W.HDC,C.c_int,C.c_int],W.HBITMAP),
      ('CreateBitmap',[C.c_int,C.c_int,W.UINT,W.UINT,C.c_void_p],W.HBITMAP),
      ('SelectObject',[W.HDC,W.HGDIOBJ],W.HGDIOBJ),('DeleteObject',[W.HGDIOBJ],W.BOOL),
      ('DeleteDC',[W.HDC],W.BOOL),('CreateSolidBrush',[W.DWORD],W.HBRUSH),
      ('SetTextColor',[W.HDC,W.DWORD],W.DWORD),('SetBkMode',[W.HDC,C.c_int],C.c_int),
      ('CreateFontW',[C.c_int]*5+[W.DWORD]*8+[W.LPCWSTR],W.HFONT)]:
        fn=getattr(g,name);fn.argtypes=args;fn.restype=rest
    s.Shell_NotifyIconW.argtypes=[W.DWORD,C.POINTER(Notify)];s.Shell_NotifyIconW.restype=W.BOOL
    k.GetModuleHandleW.argtypes=[W.LPCWSTR];k.GetModuleHandleW.restype=W.HMODULE
    u.GetAsyncKeyState.argtypes=[C.c_int];u.GetAsyncKeyState.restype=C.c_short
    u.SetTimer.argtypes=[W.HWND,C.c_size_t,W.UINT,C.c_void_p];u.SetTimer.restype=C.c_size_t
    u.KillTimer.argtypes=[W.HWND,C.c_size_t]
    s.Shell_NotifyIconGetRect.argtypes=[C.POINTER(IconIdentifier),C.POINTER(W.RECT)];s.Shell_NotifyIconGetRect.restype=C.c_long
signatures()

def color(rgb):return (rgb&0xff)<<16 | rgb&0xff00 | (rgb>>16)&0xff

def make_icon(text,background=0x273142,foreground=0xffffff):
    screen=u.GetDC(None);dc=g.CreateCompatibleDC(screen)
    bitmap=g.CreateCompatibleBitmap(screen,32,32);mask=g.CreateBitmap(32,32,1,1,C.create_string_buffer(128))
    brush=g.CreateSolidBrush(color(background));font=None
    old=g.SelectObject(dc,bitmap)
    try:
        rect=W.RECT(0,0,32,32);u.FillRect(dc,C.byref(rect),brush)
        font=g.CreateFontW(-20 if len(text)<3 else -16,0,0,0,700,0,0,0,1,0,0,4,0,'Segoe UI')
        oldfont=g.SelectObject(dc,font);g.SetBkMode(dc,1);g.SetTextColor(dc,color(foreground))
        u.DrawTextW(dc,text,-1,C.byref(rect),0x25)
        g.SelectObject(dc,oldfont)
        info=IconInfo(True,0,0,mask,bitmap);icon=u.CreateIconIndirect(C.byref(info))
        if not icon:raise C.WinError(C.get_last_error())
        return icon
    finally:
        g.SelectObject(dc,old)
        if font:g.DeleteObject(font)
        g.DeleteObject(brush);g.DeleteObject(mask);g.DeleteObject(bitmap);g.DeleteDC(dc);u.ReleaseDC(None,screen)

def decode_action(message):
    code=message&0xffff
    return 'mark' if code==0x203 else 'menu' if code in (0x205,0x7b) else None

class Tray:
    def __init__(self,events,window_class='AkkoLinkMonitor.Tray'):
        self.events=events;self.commands=queue.Queue();self.hwnd=None;self.icon=None
        self.menu=[];self.ready=threading.Event();self.error=None;self.last=None;self.stopped=False
        self.window_class=window_class
        self.gestures=Gestures(self.events.put);self.mouse_was_down=False;self.press_origin=None
        self.guid=GUID.from_buffer_copy(uuid.uuid5(uuid.NAMESPACE_URL,'https://github.com/Jazzwind/akko-link-monitor/'+window_class).bytes_le)
        self.thread=threading.Thread(target=self.run,name='AkkoTray',daemon=True)
    def start(self):
        self.thread.start()
        if not self.ready.wait(5) or self.error:raise RuntimeError(self.error or '托盘启动超时')
    def update(self,text,tip,background=0x273142,foreground=0xffffff):
        state=(text,tip,background,foreground)
        if self.last==state:return
        self.last=state;self.commands.put(state)
        if self.hwnd:u.PostMessageW(self.hwnd,0x8002,0,0)
    def set_menu(self,rows):
        self.menu=rows
    def notify(self,operation):
        n=Notify();n.size=C.sizeof(n);n.hwnd=self.hwnd;n.id=1
        n.flags=0xa7;n.callback=0x8001;n.icon=self.icon;n.guid=self.guid;n.tip=(self.last[1] if self.last else 'AKKO Link Monitor')[:127]
        if not s.Shell_NotifyIconW(operation,C.byref(n)) and operation!=2:raise C.WinError(C.get_last_error())
        if operation==0:n.version=4;s.Shell_NotifyIconW(4,C.byref(n))
    def popup(self):
        menus=[]
        def build(rows):
            menu=u.CreatePopupMenu();menus.append(menu)
            for row in rows:
                if row is None:
                    u.AppendMenuW(menu,0x800,0,None);continue
                identity,label,checked,enabled,children=row
                flags=(8 if checked else 0)|(3 if not enabled else 0)
                if children:u.AppendMenuW(menu,flags|0x10,build(children),label)
                else:u.AppendMenuW(menu,flags,identity,label)
            return menu
        # Freeze one snapshot while menu is open; background refresh never
        # replaces a live menu and closes its submenus.
        menu=build(self.menu);point=W.POINT();u.GetCursorPos(C.byref(point));u.SetForegroundWindow(self.hwnd)
        try:
            command=u.TrackPopupMenu(menu,0x182,point.x,point.y,0,self.hwnd,None)
            if command:self.events.put(('tray',command))
        finally:u.DestroyMenu(menu);u.PostMessageW(self.hwnd,0,0,0)
    def poll_hold(self):
        down=bool(u.GetAsyncKeyState(1)&0x8000)
        point=W.POINT();u.GetCursorPos(C.byref(point))
        identifier=IconIdentifier(C.sizeof(IconIdentifier),self.hwnd,1,self.guid);rect=W.RECT()
        located=s.Shell_NotifyIconGetRect(C.byref(identifier),C.byref(rect))==0
        inside=located and rect.left<=point.x<rect.right and rect.top<=point.y<rect.bottom
        if down and not self.mouse_was_down and inside:
            self.press_origin=(point.x,point.y)
            self.gestures.down(time.time(),time.perf_counter())
        elif not down and self.mouse_was_down:
            self.gestures.up(time.time(),time.perf_counter());self.press_origin=None
        elif down and self.press_origin:
            # Shell may relocate the icon rectangle after feedback/overflow
            # updates. Cancel an actual drag, not that layout change.
            if max(abs(point.x-self.press_origin[0]),abs(point.y-self.press_origin[1]))>8:
                self.gestures.cancel();self.press_origin=None
        if down:self.gestures.tick(time.perf_counter())
        self.mouse_was_down=down
    def run(self):
        name=self.window_class;instance=k.GetModuleHandleW(None)
        taskbar=u.RegisterWindowMessageW('TaskbarCreated');show=u.RegisterWindowMessageW('AkkoLinkMonitor.Show')
        @PROC
        def proc(hwnd,msg,wp,lp):
            try:
                if msg==0x8001:
                    code=lp&0xffff
                    action=decode_action(lp)
                    if code in (0x201,0x203):
                        point=W.POINT();u.GetCursorPos(C.byref(point));self.press_origin=(point.x,point.y)
                        self.gestures.down(time.time(),time.perf_counter(),code==0x203);self.mouse_was_down=True
                    elif code==0x202:
                        self.gestures.up(time.time(),time.perf_counter());self.mouse_was_down=False;self.press_origin=None
                    elif action=='menu':
                        ready=threading.Event();self.events.put(('tray_menu_refresh',ready))
                        ready.wait(1);self.popup()
                elif msg==0x8002:
                    state=None
                    while not self.commands.empty():state=self.commands.get_nowait()
                    if state:
                        new=make_icon(state[0],state[2],state[3]);old=self.icon;self.icon=new
                        try:self.notify(1)
                        except OSError:self.notify(0)
                        if old:u.DestroyIcon(old)
                elif msg==taskbar:self.notify(0)
                elif msg==show:self.events.put(('tray',100))
                elif msg==0x113:self.poll_hold()
                elif msg==0x10:
                    u.KillTimer(hwnd,1)
                    try:self.notify(2)
                    finally:u.DestroyWindow(hwnd)
                    return 0
                elif msg==2:u.PostQuitMessage(0);return 0
            except Exception as exc:self.events.put(('tray_error',str(exc)))
            return u.DefWindowProcW(hwnd,msg,wp,lp)
        self.proc=proc;wc=WindowClass();wc.style=8;wc.proc=proc;wc.instance=instance;wc.name=name;registered=False
        try:
            if not u.RegisterClassW(C.byref(wc)):raise C.WinError(C.get_last_error())
            registered=True
            self.hwnd=u.CreateWindowExW(0,name,'AKKO Link Monitor Tray',0,0,0,0,0,None,None,instance,None)
            if not self.hwnd:raise C.WinError(C.get_last_error())
            self.icon=make_icon('?');self.notify(0);u.SetTimer(self.hwnd,1,50,None);self.ready.set()
            msg=W.MSG()
            while u.GetMessageW(C.byref(msg),None,0,0)>0:u.TranslateMessage(C.byref(msg));u.DispatchMessageW(C.byref(msg))
        except Exception as exc:self.error=str(exc);self.ready.set()
        finally:
            if self.icon:u.DestroyIcon(self.icon)
            if registered:u.UnregisterClassW(name,instance)
            self.hwnd=None;self.stopped=True
    def stop(self):
        if self.hwnd:u.PostMessageW(self.hwnd,0x10,0,0)
        if self.thread.is_alive():self.thread.join(4)
