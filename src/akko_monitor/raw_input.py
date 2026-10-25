"""Event-driven, device-attributed keyboard receiver. No text conversion."""
import ctypes as C
from ctypes import wintypes as W
import queue
import threading
import time
from .identity import source_for

user = C.WinDLL('user32', use_last_error=True)
kernel = C.WinDLL('kernel32', use_last_error=True)
LRESULT = C.c_ssize_t
PROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)

class WindowClass(C.Structure):
    _fields_ = [('style', W.UINT), ('proc', PROC), ('clsExtra', C.c_int), ('wndExtra', C.c_int), ('instance', W.HINSTANCE), ('icon', W.HICON), ('cursor', W.HANDLE), ('brush', W.HBRUSH), ('menu', W.LPCWSTR), ('name', W.LPCWSTR)]

class Registration(C.Structure):
    _fields_ = [('page', W.USHORT), ('usage', W.USHORT), ('flags', W.DWORD), ('target', W.HWND)]

class Header(C.Structure):
    _fields_ = [('kind', W.DWORD), ('size', W.DWORD), ('device', W.HANDLE), ('wparam', W.WPARAM)]

class Keyboard(C.Structure):
    _fields_ = [('scan', W.USHORT), ('flags', W.USHORT), ('reserved', W.USHORT), ('vkey', W.USHORT), ('message', W.UINT), ('extra', W.ULONG)]

user.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
user.DefWindowProcW.restype = LRESULT
user.RegisterClassW.argtypes = [C.POINTER(WindowClass)]
user.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
user.CreateWindowExW.restype = W.HWND
user.RegisterRawInputDevices.argtypes = [C.POINTER(Registration), W.UINT, W.UINT]
user.GetRawInputData.argtypes = [W.HANDLE, W.UINT, C.c_void_p, C.POINTER(W.UINT), W.UINT]
user.GetRawInputDeviceInfoW.argtypes = [W.HANDLE, W.UINT, C.c_void_p, C.POINTER(W.UINT)]
user.GetMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
user.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
user.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
user.DispatchMessageW.restype = LRESULT
user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
user.DestroyWindow.argtypes = [W.HWND]
user.UnregisterClassW.argtypes = [W.LPCWSTR, W.HINSTANCE]
kernel.GetModuleHandleW.argtypes = [W.LPCWSTR]
kernel.GetModuleHandleW.restype = W.HMODULE

class Receiver:
    def __init__(self):
        self.events = queue.Queue(maxsize=20000)
        self.names = {}
        self.hwnd = None
        self.dropped = 0
        self.ready = threading.Event()
        self.error = None

    def emit(self, row):
        try: self.events.put_nowait(row)
        except queue.Full: self.dropped += 1

    def name(self, handle):
        if handle not in self.names:
            n = W.UINT()
            user.GetRawInputDeviceInfoW(handle, 0x20000007, None, C.byref(n))
            buf = C.create_unicode_buffer(n.value + 1)
            if user.GetRawInputDeviceInfoW(handle, 0x20000007, buf, C.byref(n)) == 0xFFFFFFFF:
                return ''
            self.names[handle] = buf.value.lower()
        return self.names[handle]

    def start(self):
        self.thread = threading.Thread(target=self.run, name='RawInput', daemon=True)
        self.thread.start()
        if not self.ready.wait(5): raise RuntimeError('Raw Input 启动超时')
        if self.error: raise RuntimeError(self.error)

    def run(self):
        @PROC
        def proc(hwnd, msg, wp, lp):
            try:
                if msg == 0xFF:
                    n = W.UINT()
                    user.GetRawInputData(lp, 0x10000003, None, C.byref(n), C.sizeof(Header))
                    if n.value >= C.sizeof(Header) + C.sizeof(Keyboard):
                        buf = C.create_string_buffer(n.value)
                        got = user.GetRawInputData(lp, 0x10000003, buf, C.byref(n), C.sizeof(Header))
                        if got != 0xFFFFFFFF:
                            h = Header.from_buffer(buf)
                            if h.kind == 1:
                                k = Keyboard.from_buffer(buf, C.sizeof(Header))
                                path = self.name(h.device)
                                # Filter BEFORE queueing: never collect Logitech/other keyboard input.
                                if source_for(path) and k.vkey != 255:
                                    self.emit(('key', time.perf_counter(), path, k.scan, k.flags, k.vkey))
                elif msg == 0xFE:
                    path = self.name(lp)
                    if source_for(path):
                        self.emit(('device', time.perf_counter(), path, 'arrival' if wp == 1 else 'removal'))
                    if wp == 2: self.names.pop(lp, None)
                elif msg == 0x10:
                    user.DestroyWindow(hwnd)
                    return 0
                elif msg == 2:
                    user.PostQuitMessage(0)
                    return 0
            except Exception as exc:
                self.emit(('error', str(exc)))
            return user.DefWindowProcW(hwnd, msg, wp, lp)
        self.proc = proc
        instance = kernel.GetModuleHandleW(None)
        name = 'AkkoLinkMonitor_' + str(id(self))
        wc = WindowClass(); wc.proc = proc; wc.instance = instance; wc.name = name
        registered = False
        try:
            if not user.RegisterClassW(C.byref(wc)): raise C.WinError(C.get_last_error())
            registered = True
            self.hwnd = user.CreateWindowExW(0, name, name, 0, 0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd: raise C.WinError(C.get_last_error())
            rid = Registration(1, 6, 0x2100, self.hwnd)
            if not user.RegisterRawInputDevices(C.byref(rid), 1, C.sizeof(rid)): raise C.WinError(C.get_last_error())
            self.ready.set()
            msg = W.MSG()
            while True:
                status = user.GetMessageW(C.byref(msg), None, 0, 0)
                if status == -1: raise C.WinError(C.get_last_error())
                if status == 0: break
                user.TranslateMessage(C.byref(msg)); user.DispatchMessageW(C.byref(msg))
        except Exception as exc:
            self.error = str(exc)
            self.emit(('error', str(exc)))
            self.ready.set()
        finally:
            self.hwnd = None
            if registered: user.UnregisterClassW(name, instance)

    def stop(self):
        if self.hwnd: user.PostMessageW(self.hwnd, 0x10, 0, 0)
        if hasattr(self, 'thread'): self.thread.join(3)
