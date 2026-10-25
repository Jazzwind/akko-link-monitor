"""Read USB hub connection/configuration descriptors. No configuration writes."""
import ctypes as C
from ctypes import wintypes as W
import json
import struct
import uuid
from .devices import GUID, Interface, setup, kernel

kernel.DeviceIoControl.argtypes=[W.HANDLE,W.DWORD,C.c_void_p,W.DWORD,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p]

def hub_paths():
    guid=GUID.from_buffer_copy(uuid.UUID('f18a0e88-c30c-11d0-8815-00a0c906bed8').bytes_le)
    info=setup.SetupDiGetClassDevsW(C.byref(guid),None,None,0x12)
    if info==C.c_void_p(-1).value: raise C.WinError(C.get_last_error())
    try:
        i=0
        while True:
            iface=Interface(); iface.cbSize=C.sizeof(iface)
            if not setup.SetupDiEnumDeviceInterfaces(info,None,C.byref(guid),i,C.byref(iface)):
                if C.get_last_error()!=259: raise C.WinError(C.get_last_error())
                break
            i+=1; n=W.DWORD()
            setup.SetupDiGetDeviceInterfaceDetailW(info,C.byref(iface),None,0,C.byref(n),None)
            buf=C.create_string_buffer(n.value)
            C.cast(buf,C.POINTER(W.DWORD))[0]=8 if C.sizeof(C.c_void_p)==8 else 6
            if setup.SetupDiGetDeviceInterfaceDetailW(info,C.byref(iface),buf,n,None,None):
                yield C.wstring_at(C.addressof(buf)+4)
    finally: setup.SetupDiDestroyDeviceInfoList(info)

def ioctl(handle,code,request,size=4096):
    buf=C.create_string_buffer(max(size,len(request)))
    C.memmove(buf,request,len(request)); n=W.DWORD()
    if not kernel.DeviceIoControl(handle,code,buf,len(request),buf,C.sizeof(buf),C.byref(n),None):
        raise C.WinError(C.get_last_error())
    return buf.raw[:n.value]

def interval_ms(speed,interval):
    if interval==0: return None
    if speed in (0,1): return float(interval)  # Low/Full-speed interrupt endpoints: frames.
    if speed in (2,3,4) and 1<=interval<=16: return .125*(2**(interval-1))
    return None

def parse_configuration(data,speed):
    result=[]; pos=0; interface=None; alt=None
    if len(data)<9 or data[1]!=2: raise ValueError('无效 USB 配置描述符')
    total=int.from_bytes(data[2:4],'little')
    if total>len(data): raise ValueError('USB 配置描述符不完整')
    while pos+2<=total:
        length,kind=data[pos:pos+2]
        if length<2 or pos+length>total: raise ValueError('USB 描述符长度越界')
        part=data[pos:pos+length]
        if kind==4 and length>=9: interface,alt=part[2],part[3]
        elif kind==5 and length>=7 and part[3]&3==3:
            ms=interval_ms(speed,part[6])
            result.append({'interface':interface,'alternate_setting':alt,'endpoint':f'0x{part[2]:02X}','direction':'IN' if part[2]&0x80 else 'OUT','bInterval':part[6],'interval_ms':ms,'nominal_hz':round(1000/ms,3) if ms else None,'max_packet_bytes':int.from_bytes(part[4:6],'little')&0x7ff})
        pos+=length
    return result

def query_usb(vid=0x320F,pid=0x506B):
    matches=[]; errors=[]
    for path in hub_paths():
        handle=kernel.CreateFileW(path,0x40000000,3,None,3,0,None)
        if handle==C.c_void_p(-1).value:
            errors.append({'stage':'open_hub','winerror':C.get_last_error()}); continue
        try:
            try: node=ioctl(handle,0x220408,bytes(76),76)
            except OSError as exc:
                errors.append({'stage':'hub_information','error':str(exc)});continue
            ports=node[6] if len(node)>6 else 0
            for port in range(1,ports+1):
                try: conn=ioctl(handle,0x220448,struct.pack('<I',port)+bytes(35+32*11-4),35+32*11)
                except OSError: continue
                if len(conn)<35: continue
                found_vid,found_pid=struct.unpack_from('<HH',conn,12)
                if (found_vid,found_pid)!=(vid,pid):continue
                speed=conn[23]
                info={'vid_pid':f'{vid:04X}:{pid:04X}','hub_path':path,'port':port,'speed':{0:'Low',1:'Full',2:'High',3:'Super',4:'SuperPlus'}.get(speed,str(speed)),'device_address':int.from_bytes(conn[25:27],'little'),'source':'USB configuration endpoint descriptors','endpoints':[]}
                try:
                    request=struct.pack('<IBBHHH',port,0x80,6,0x0200,0,4096)
                    config=ioctl(handle,0x220410,request+bytes(4096),4108)[12:]
                    info['configuration_hex']=config.hex()
                    info['endpoints']=parse_configuration(config,speed)
                except (OSError,ValueError) as exc: info['error']=str(exc)
                matches.append(info)
        finally: kernel.CloseHandle(handle)
    return {'devices':matches,'errors':errors,'status':'ok' if matches and all(m['endpoints'] for m in matches) else 'unavailable'}

if __name__=='__main__':
    print(json.dumps(query_usb(),ensure_ascii=True,indent=2))
