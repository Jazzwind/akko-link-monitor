"""Only the power query verified against the installed official executable."""
import ctypes as C
from ctypes import wintypes as W
import time
from .devices import inventory, kernel

class Overlapped(C.Structure):
    _fields_=[('Internal',C.c_size_t),('InternalHigh',C.c_size_t),('Offset',W.DWORD),('OffsetHigh',W.DWORD),('event',W.HANDLE)]

kernel.CreateEventW.argtypes=[C.c_void_p,W.BOOL,W.BOOL,W.LPCWSTR]
kernel.CreateEventW.restype=W.HANDLE
kernel.ReadFile.argtypes=[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.POINTER(Overlapped)]
kernel.WriteFile.argtypes=kernel.ReadFile.argtypes
kernel.GetOverlappedResult.argtypes=[W.HANDLE,C.POINTER(Overlapped),C.POINTER(W.DWORD),W.BOOL]
kernel.CancelIoEx.argtypes=[W.HANDLE,C.POINTER(Overlapped)]
kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD]

class Pending:
    def __init__(self,handle,data,write=False):
        self.handle=handle
        self.buffer=C.create_string_buffer(data,len(data)) if write else C.create_string_buffer(data)
        self.ov=Overlapped(); self.ov.event=kernel.CreateEventW(None,True,False,None)
        if not self.ov.event: raise C.WinError(C.get_last_error())
        n=W.DWORD(); fn=kernel.WriteFile if write else kernel.ReadFile
        ok=fn(handle,self.buffer,C.sizeof(self.buffer),C.byref(n),C.byref(self.ov))
        error=C.get_last_error(); self.pending=not ok and error==997
        if not ok and not self.pending:
            kernel.CloseHandle(self.ov.event); self.ov.event=None
            raise C.WinError(error)

    def finish(self,timeout=1500):
        if kernel.WaitForSingleObject(self.ov.event,timeout)!=0:
            self.cancel(); raise TimeoutError('AKKO 私有接口查询超时')
        n=W.DWORD()
        if not kernel.GetOverlappedResult(self.handle,C.byref(self.ov),C.byref(n),False):
            raise C.WinError(C.get_last_error())
        self.pending=False
        return self.buffer.raw[:n.value]

    def cancel(self):
        if self.pending:
            kernel.CancelIoEx(self.handle,C.byref(self.ov)); n=W.DWORD()
            kernel.GetOverlappedResult(self.handle,C.byref(self.ov),C.byref(n),True)
            self.pending=False

    def close(self):
        self.cancel()
        if self.ov.event: kernel.CloseHandle(self.ov.event); self.ov.event=None

def vendor_path():
    rows=inventory('320F:506B',descriptors=True)
    matches=[r for r in rows if r.get('usage_page')==0xFF1C and r.get('usage')==0x92 and r.get('input_bytes')==64 and r.get('output_bytes')==64]
    if len(matches)!=1:
        raise RuntimeError('未找到唯一的 AKKO FF1C:0092 私有接口（可能受访问权限限制）')
    return matches[0]['path']

def exchange_power(timeout=1500):
    # CHidMessage::HidReadDevicePowerInfo at VA 0x44C870 in installed EXE.
    # All 271 bytes match vendor COFF object except link-time relocation addresses.
    # Sole permitted output: report 04, sum16 0020, command 1A, length 06, zero payload.
    request=bytes.fromhex('04 20 00 1A 06')+bytes(59)
    path=vendor_path(); handles=[]; pending=[]
    try:
        for access in (0x80000000,0x40000000):
            handle=kernel.CreateFileW(path,access,3,None,3,0x40000000,None)
            if handle==C.c_void_p(-1).value: raise C.WinError(C.get_last_error())
            handles.append(handle)
        read=Pending(handles[0],64); pending.append(read)
        write=Pending(handles[1],request,True); pending.append(write)
        write.finish(timeout); deadline=time.monotonic()+timeout/1000
        while True:
            reply=read.finish(max(1,int((deadline-time.monotonic())*1000)))
            if len(reply)==64 and reply[0]==4 and reply[3]==0x1A: return request,reply
            if time.monotonic()>=deadline: raise TimeoutError('未收到匹配的电量查询回复')
            read.close(); pending.remove(read)
            read=Pending(handles[0],64); pending.append(read)
    finally:
        for operation in pending: operation.close()
        for handle in handles: kernel.CloseHandle(handle)

if __name__=='__main__':
    request,reply=exchange_power()
    print('request',request.hex(' ')); print('reply  ',reply.hex(' '))
    print('checksum',int.from_bytes(reply[1:3],'little'),sum(reply[3:]))
    print('status',reply[7],'power payload',list(reply[8:14]))
