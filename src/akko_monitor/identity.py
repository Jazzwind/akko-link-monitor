"""Model filter and local Bluetooth identity, without a public hardware address."""
import ctypes as C
from ctypes import wintypes as W
import re
import uuid
from .paths import DATA, save_json

BT_ADDRESS = ''
cfg=C.WinDLL('cfgmgr32',use_last_error=True)

class PropertyKey(C.Structure):
    _fields_=[('guid',C.c_ubyte*16),('pid',W.DWORD)]

cfg.CM_Get_Device_ID_List_SizeW.argtypes=[C.POINTER(W.ULONG),W.LPCWSTR,W.ULONG]
cfg.CM_Get_Device_ID_ListW.argtypes=[W.LPCWSTR,W.LPWSTR,W.ULONG,W.ULONG]
cfg.CM_Locate_DevNodeW.argtypes=[C.POINTER(W.DWORD),W.LPWSTR,W.ULONG]
cfg.CM_Get_DevNode_PropertyW.argtypes=[W.DWORD,C.POINTER(PropertyKey),C.POINTER(W.ULONG),C.c_void_p,C.POINTER(W.ULONG),W.ULONG]

def nodes():
    for _ in range(3):
        size=W.ULONG()
        if cfg.CM_Get_Device_ID_List_SizeW(C.byref(size),None,0):break
        buf=C.create_unicode_buffer(size.value)
        if not cfg.CM_Get_Device_ID_ListW(None,buf,size,0):return [s for s in buf[:].split('\0') if s]
    raise OSError('无法枚举 Windows 设备实例')

def read_property(instance,guid,pid):
    dev=W.DWORD()
    if cfg.CM_Locate_DevNodeW(C.byref(dev),C.create_unicode_buffer(instance),0):raise LookupError('设备节点不可用')
    key=PropertyKey((C.c_ubyte*16).from_buffer_copy(uuid.UUID(guid).bytes_le),pid)
    kind=W.ULONG();length=W.ULONG(4096);buf=C.create_string_buffer(4096)
    code=cfg.CM_Get_DevNode_PropertyW(dev,C.byref(key),C.byref(kind),buf,C.byref(length),0)
    if code:raise LookupError(f'设备属性不可用 0x{code:X}')
    return buf.raw[:length.value],kind.value

def discover():
    result=[]
    for instance in nodes():
        match=re.match(r'BTHLE\\DEV_([0-9A-F]{12})\\',instance,re.I)
        if not match:continue
        try:
            raw,kind=read_property(instance,'a45c254e-df1c-4efd-8020-67d146a850e0',14)
            name=raw.decode('utf-16-le').rstrip('\0') if kind==18 else ''
        except (LookupError,UnicodeError):continue
        if re.fullmatch(r'AKKO3098BT-?1',name.replace(' ','').upper()):
            result.append({'address':match[1].upper(),'name':name,'instance':instance})
    return result

def configure(address):
    global BT_ADDRESS
    if address and not re.fullmatch(r'[0-9A-Fa-f]{12}',address):raise ValueError('无效蓝牙地址')
    BT_ADDRESS=address.upper()

def bind(candidate):
    configure(candidate['address'])
    save_json(DATA/'device.json',{'address':BT_ADDRESS,'name':candidate['name']})

def initialize():
    import json
    try:
        saved=json.loads((DATA/'device.json').read_text(encoding='utf8'))
        configure(saved.get('address',''))
        if BT_ADDRESS:return []
    except (OSError,ValueError,AttributeError):configure('')
    candidates=discover()
    if len(candidates)==1:bind(candidates[0])
    return candidates

def source_for(path):
    path=path.lower()
    if 'vid_320f&pid_506b' in path:return '2.4G'
    if (BT_ADDRESS and '00001812-0000-1000-8000-00805f9b34fb' in path
            and '_'+BT_ADDRESS.lower()+'&col' in path):return 'BT1'
    return ''

def source_label(path):return source_for(path) or 'unknown'
