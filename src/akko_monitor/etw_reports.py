"""Real-time UCX interrupt-IN completion timing, headers only (no keystroke data).

Requires elevation to start an ETW session, but installs no driver. 64-bit Windows.
Filters by the receiver's root hub + port before retaining endpoint statistics.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import struct
import threading
import time
import uuid
from collections import deque
from .devices import GUID
from .usb_info import query_usb

adv=C.WinDLL('advapi32',use_last_error=True)
PROVIDER=GUID.from_buffer_copy(uuid.UUID('36da592d-e43a-4e28-af6f-4bc57c5a11e8').bytes_le)

class Descriptor(C.Structure):
    _fields_=[('id',W.USHORT),('version',C.c_ubyte),('channel',C.c_ubyte),('level',C.c_ubyte),('opcode',C.c_ubyte),('task',W.USHORT),('keyword',C.c_uint64)]

class EventHeader(C.Structure):
    _fields_=[('size',W.USHORT),('type',W.USHORT),('flags',W.USHORT),('property',W.USHORT),('thread',W.DWORD),('process',W.DWORD),('timestamp',C.c_int64),('provider',GUID),('descriptor',Descriptor),('processor_time',C.c_uint64),('activity',GUID)]

class Record(C.Structure):
    _fields_=[('header',EventHeader),('buffer_context',W.DWORD),('extended_count',W.USHORT),('data_length',W.USHORT),('extended',C.c_void_p),('data',C.c_void_p),('context',C.c_void_p)]

CALLBACK=C.WINFUNCTYPE(None,C.POINTER(Record))

class Logfile(C.Structure):
    _fields_=[('filename',W.LPWSTR),('logger',W.LPWSTR),('current_time',C.c_int64),('buffers_read',W.ULONG),('mode',W.ULONG),('current_event',C.c_byte*88),('logfile_header',C.c_byte*280),('buffer_callback',C.c_void_p),('buffer_size',W.ULONG),('filled',W.ULONG),('events_lost',W.ULONG),('callback',CALLBACK),('is_kernel',W.ULONG),('context',C.c_void_p)]

adv.StartTraceW.argtypes=[C.POINTER(C.c_uint64),W.LPCWSTR,C.c_void_p]
adv.EnableTraceEx2.argtypes=[C.c_uint64,C.POINTER(GUID),W.ULONG,C.c_ubyte,C.c_uint64,C.c_uint64,W.ULONG,C.c_void_p]
adv.ControlTraceW.argtypes=[C.c_uint64,W.LPCWSTR,C.c_void_p,W.ULONG]
adv.OpenTraceW.argtypes=[C.POINTER(Logfile)]
adv.OpenTraceW.restype=C.c_uint64
adv.ProcessTrace.argtypes=[C.POINTER(C.c_uint64),W.ULONG,C.c_void_p,C.c_void_p]
adv.CloseTrace.argtypes=[C.c_uint64]

def normalized(path):
    return path.rstrip('\x00').lower().replace('\\??\\','\\\\?\\')

class ReportStats:
    def __init__(self,frequency=1):
        self.frequency=frequency
        self.count=0; self.errors=0; self.last=None; self.last_size=0
        self.intervals=deque(maxlen=10000)

    def add(self,ticks,size):
        if self.last is not None and ticks>=self.last:
            self.intervals.append((ticks-self.last)*1000/self.frequency)
        self.last=ticks; self.last_size=size; self.count+=1

    def summary(self):
        values=sorted(self.intervals)
        return {'reports_total':self.count,'transfer_errors':self.errors,'last_size':self.last_size,'interval_samples':len(values),'last_interval_ms':self.intervals[-1] if values else None,'min_ms':values[0] if values else None,'p50_ms':values[(len(values)-1)//2] if values else None,'p95_ms':values[int((len(values)-1)*.95)] if values else None,'max_ms':values[-1] if values else None}

class UcxDecoder:
    """Validated UCX v0/v1 header layouts; unknown versions are rejected."""
    def __init__(self,hub_path,port,frequency):
        self.hub_path=normalized(hub_path); self.port=port; self.frequency=frequency
        self.root=None; self.target=None; self.pipes={}; self.stats={}
        self.lock=threading.Lock(); self.decode_errors=0; self.mapped=False

    def consume(self,eid,version,timestamp,payload):
        if version not in (0,1):return
        if eid in (4,10,12) and version==0 and len(payload)>=18:
            # Root hub rundown/create/prepare/release: controller, UsbDevice, path.
            path=payload[16:].decode('utf-16-le',errors='replace').split('\0',1)[0]
            if normalized(path)==self.hub_path:
                self.root=struct.unpack_from('<Q',payload,8)[0]
        elif eid in (5,14) and version==0 and len(payload)>=56:
            _,hub,device,speed,depth=struct.unpack_from('<QQQII',payload)
            portpath=struct.unpack_from('<6I',payload,32)
            if hub==self.root and depth==1 and portpath[0]==self.port:
                self.target=device; self.mapped=True
        elif eid in (6,16) and version==0 and len(payload)>=31:
            device,endpoint,pipe=struct.unpack_from('<QQQ',payload)
            if device==self.target:
                length,kind,address,attributes,maxpacket,interval=struct.unpack_from('<BBBBHB',payload,24)
                if kind==5 and attributes&3==3 and address&0x80:
                    self.pipes[pipe]=f'0x{address:02X}'
        elif eid==15 and version==0 and len(payload)>=24:
            device=struct.unpack_from('<Q',payload,16)[0]
            if device==self.target:
                self.target=None;self.mapped=False;self.pipes.clear()
        elif eid==17 and version==0 and len(payload)>=24:
            pipe=struct.unpack_from('<Q',payload,16)[0]
            self.pipes.pop(pipe,None)
        elif eid==27 and len(payload)>=172:
            controller,device,pipe,irp,urb=struct.unpack_from('<QQQQQ',payload)
            if device!=self.target or pipe not in self.pipes:return
            endpoint=self.pipes[pipe]
            urbstatus=struct.unpack_from('<I',payload,44)[0]
            flags,size=struct.unpack_from('<II',payload,72)
            ntstatus=struct.unpack_from('<I',payload,168)[0]
            with self.lock:
                stat=self.stats.setdefault(endpoint,ReportStats(self.frequency))
                if urbstatus or ntstatus:
                    stat.errors+=1;return
                if flags&1 and size>0:
                    stat.add(timestamp,size)

    def summary(self):
        with self.lock:
            return {ep:s.summary() for ep,s in self.stats.items()}

def properties(name):
    buf=C.create_string_buffer(120+2048)
    # WNODE_HEADER: full allocation size, client clock QPC, traced GUID.
    struct.pack_into('<I',buf,0,C.sizeof(buf))
    struct.pack_into('<I',buf,40,1)
    struct.pack_into('<I',buf,44,0x20000)
    struct.pack_into('<IIIIII',buf,48,64,4,32,0,0x100,1)
    struct.pack_into('<I',buf,116,120)
    encoded=(name+'\0').encode('utf-16-le'); C.memmove(C.addressof(buf)+120,encoded,len(encoded))
    return buf

def verify_schemas():
    """Do not silently parse kernel events using an incompatible OS schema."""
    tdh=C.WinDLL('tdh')
    fn=tdh.TdhGetManifestEventInformation
    fn.argtypes=[C.POINTER(GUID),C.POINTER(Descriptor),C.c_void_p,C.POINTER(W.ULONG)]
    expected={4:['fid_UcxController','fid_UsbDevice','fid_DeviceInterfacePath'],5:['fid_UcxController','fid_HubDevice','fid_UsbDevice','DeviceSpeed','PortPathDepth','PortPath'],6:['fid_UsbDevice','fid_Endpoint','fid_PipeHandle','fid_UCX_Endpoint_Descriptor'],27:['fid_UcxController','fid_UsbDevice','fid_PipeHandle','fid_IRP_Ptr','fid_URB_Ptr','fid_UCX_URB_BULK_OR_INTERRUPT_TRANSFER','fid_IRP_NtStatus']}
    for eid,names in expected.items():
        desc=Descriptor();desc.id=eid;size=W.ULONG()
        if fn(C.byref(PROVIDER),C.byref(desc),None,C.byref(size))!=122:raise RuntimeError('无法读取 UCX 事件定义')
        buf=C.create_string_buffer(size.value)
        if fn(C.byref(PROVIDER),C.byref(desc),buf,C.byref(size)):raise RuntimeError('UCX 定义读取失败')
        top=struct.unpack_from('<I',buf.raw,104)[0]
        actual=[C.wstring_at(C.addressof(buf)+struct.unpack_from('<I',buf.raw,112+i*24+4)[0]) for i in range(top)]
        if actual!=names:raise RuntimeError(f'UCX 事件 {eid} 定义不兼容，停止解析')

class Trace:
    def __init__(self,decoder):
        self.decoder=decoder; self.name='AkkoReports_'+str(os.getpid())+'_'+uuid.uuid4().hex[:8]
        self.handle=C.c_uint64(); self.consumer=None; self.started=False; self.callback_errors=0
        self.props=properties(self.name)

    def start(self):
        if C.sizeof(C.c_void_p)!=8:raise RuntimeError('USB 报告采集目前需要 64 位 Python')
        verify_schemas()
        status=adv.StartTraceW(C.byref(self.handle),self.name,self.props)
        if status:raise C.WinError(status)
        self.started=True
        try:
            @CALLBACK
            def callback(ptr):
                try:
                    record=ptr.contents
                    eid=record.header.descriptor.id
                    if eid in (4,5,6,10,12,14,15,16,17,27):
                        # HeadersBusTrace includes URB structure, never input payload.
                        payload=C.string_at(record.data,record.data_length)
                        self.decoder.consume(eid,record.header.descriptor.version,record.header.timestamp,payload)
                except Exception:self.callback_errors+=1
            self.callback=callback
            self.logfile=Logfile();self.logfile.logger=self.name
            self.logfile.mode=0x10001100 # REAL_TIME 0x100 | EVENT_RECORD 0x10000000 | RAW_TIMESTAMP 0x1000
            self.logfile.callback=callback
            self.consumer=adv.OpenTraceW(C.byref(self.logfile))
            if self.consumer==0xffffffffffffffff:raise C.WinError(C.get_last_error())
            self.thread=threading.Thread(target=self.process,daemon=True);self.thread.start()
            # ONLY HeadersBusTrace + Rundown: no PartialData/FullDataBusTrace.
            status=adv.EnableTraceEx2(self.handle,C.byref(PROVIDER),1,4,0x8041,0,0,None)
            if status:raise C.WinError(status)
        except Exception:
            self.stop();raise

    def process(self):
        handle=C.c_uint64(self.consumer)
        self.process_status=adv.ProcessTrace(C.byref(handle),1,None,None)

    def lost(self):
        if not self.started:return 0
        p=properties(self.name)
        status=adv.ControlTraceW(self.handle,self.name,p,0)
        return struct.unpack_from('<I',p.raw,88)[0] if status==0 else None

    def stop(self):
        if self.started:
            adv.ControlTraceW(self.handle,self.name,self.props,1)
            self.started=False
        if self.consumer is not None and self.consumer!=0xffffffffffffffff:
            adv.CloseTrace(self.consumer);self.consumer=None
        if hasattr(self,'thread'):self.thread.join(3)

def atomic_json(path,row):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(row,ensure_ascii=False),encoding='utf8')
    os.replace(temp,path)

def run_helper(folder,duration=0):
    folder=Path(folder).resolve(); statusfile=folder/'reports-status.json'
    trace=None;start=time.monotonic()
    try:
        usb=query_usb(); devices=usb['devices']
        if len(devices)!=1:raise RuntimeError('没有唯一的 AKKO 接收器 USB 拓扑')
        device=devices[0]
        if 'root_hub' not in device['hub_path'].lower():raise RuntimeError('当前 USB 报告后端需要接收器直连根集线器；请改插主机 USB 口')
        frequency=C.c_int64();C.windll.kernel32.QueryPerformanceFrequency(C.byref(frequency))
        decoder=UcxDecoder(device['hub_path'],device['port'],frequency.value)
        trace=Trace(decoder);trace.start()
        while True:
            row={'status':'running','updated':time.time(),'mapped':decoder.mapped,'endpoints':decoder.summary(),'etw_events_lost':trace.lost(),'callback_errors':trace.callback_errors,'source':'UCX successful interrupt-IN completion timestamps; headers only'}
            atomic_json(statusfile,row)
            if (folder/'stop').exists():break
            heartbeat=folder/'heartbeat'
            if not heartbeat.exists() or time.time()-heartbeat.stat().st_mtime>15:break
            if duration and time.monotonic()-start>=duration:break
            time.sleep(.5)
        row['status']='stopped';row['updated']=time.time();atomic_json(statusfile,row)
    except Exception as exc:
        atomic_json(statusfile,{'status':'error','error':str(exc),'updated':time.time()})
    finally:
        if trace:trace.stop()

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--folder',required=True);p.add_argument('--duration',type=float,default=0)
    a=p.parse_args();run_helper(a.folder,a.duration)
