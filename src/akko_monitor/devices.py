"""Read-only Windows HID inventory; never sends vendor commands."""
import ctypes as C
from ctypes import wintypes as W
import json
import re

setup = C.WinDLL('setupapi', use_last_error=True)
hid = C.WinDLL('hid', use_last_error=True)
kernel = C.WinDLL('kernel32', use_last_error=True)

class GUID(C.Structure):
    _fields_ = [('a', W.DWORD), ('b', W.WORD), ('c', W.WORD), ('d', C.c_ubyte * 8)]

class Interface(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('guid', GUID), ('flags', W.DWORD), ('reserved', C.c_size_t)]

class DevInfo(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('guid', GUID), ('devinst', W.DWORD), ('reserved', C.c_size_t)]

class Attributes(C.Structure):
    _fields_ = [('Size', W.ULONG), ('VendorID', W.USHORT), ('ProductID', W.USHORT), ('VersionNumber', W.USHORT)]

class Caps(C.Structure):
    _fields_ = [('Usage', W.USHORT), ('UsagePage', W.USHORT), ('InputReportByteLength', W.USHORT), ('OutputReportByteLength', W.USHORT), ('FeatureReportByteLength', W.USHORT), ('Reserved', W.USHORT * 17), ('rest', W.USHORT * 10)]

setup.SetupDiGetClassDevsW.argtypes = [C.POINTER(GUID), W.LPCWSTR, W.HWND, W.DWORD]
setup.SetupDiGetClassDevsW.restype = W.HANDLE
setup.SetupDiEnumDeviceInterfaces.argtypes = [W.HANDLE, C.c_void_p, C.POINTER(GUID), W.DWORD, C.POINTER(Interface)]
setup.SetupDiGetDeviceInterfaceDetailW.argtypes = [W.HANDLE, C.POINTER(Interface), C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.POINTER(DevInfo)]
setup.SetupDiGetDeviceInstanceIdW.argtypes = [W.HANDLE, C.POINTER(DevInfo), W.LPWSTR, W.DWORD, C.POINTER(W.DWORD)]
setup.SetupDiDestroyDeviceInfoList.argtypes = [W.HANDLE]
kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
kernel.CreateFileW.restype = W.HANDLE
kernel.CloseHandle.argtypes = [W.HANDLE]
hid.HidD_GetAttributes.argtypes = [W.HANDLE, C.POINTER(Attributes)]
hid.HidD_GetProductString.argtypes = [W.HANDLE, C.c_void_p, W.ULONG]
hid.HidD_GetManufacturerString.argtypes = [W.HANDLE, C.c_void_p, W.ULONG]
hid.HidD_GetPreparsedData.argtypes = [W.HANDLE, C.POINTER(C.c_void_p)]
hid.HidD_FreePreparsedData.argtypes = [C.c_void_p]
hid.HidP_GetCaps.argtypes = [C.c_void_p, C.POINTER(Caps)]

def inventory(vid_pid=None):
    guid = GUID()
    hid.HidD_GetHidGuid(C.byref(guid))
    info = setup.SetupDiGetClassDevsW(C.byref(guid), None, None, 0x12)
    if info == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    result = []
    try:
        index = 0
        while True:
            iface = Interface(); iface.cbSize = C.sizeof(iface)
            if not setup.SetupDiEnumDeviceInterfaces(info, None, C.byref(guid), index, C.byref(iface)):
                if C.get_last_error() != 259:
                    raise C.WinError(C.get_last_error())
                break
            index += 1
            size = W.DWORD()
            setup.SetupDiGetDeviceInterfaceDetailW(info, C.byref(iface), None, 0, C.byref(size), None)
            buf = C.create_string_buffer(size.value)
            C.cast(buf, C.POINTER(W.DWORD))[0] = 8 if C.sizeof(C.c_void_p) == 8 else 6
            dev = DevInfo(); dev.cbSize = C.sizeof(dev)
            if not setup.SetupDiGetDeviceInterfaceDetailW(info, C.byref(iface), buf, size, None, C.byref(dev)):
                continue
            path = C.wstring_at(C.addressof(buf) + 4)
            instance = C.create_unicode_buffer(1024)
            setup.SetupDiGetDeviceInstanceIdW(info, C.byref(dev), instance, 1024, None)
            row = {'path': path, 'instance': instance.value}
            m = re.search(r'vid_([0-9a-f]{4})&pid_([0-9a-f]{4})', path, re.I)
            row['vid_pid'] = ':'.join(m.groups()).upper() if m else ''
            if vid_pid and row['vid_pid'] != vid_pid:
                continue
            row['transport'] = 'Bluetooth' if 'bth' in path.lower() or '00001812' in path.lower() else 'USB/HID'
            handle = kernel.CreateFileW(path, 0, 3, None, 3, 0, None)
            if handle != C.c_void_p(-1).value:
                try:
                    for name, fn in [('product', hid.HidD_GetProductString), ('manufacturer', hid.HidD_GetManufacturerString)]:
                        s = C.create_unicode_buffer(256)
                        if fn(handle, s, C.sizeof(s)): row[name] = s.value
                    pp = C.c_void_p()
                    if hid.HidD_GetPreparsedData(handle, C.byref(pp)):
                        try:
                            caps = Caps()
                            if hid.HidP_GetCaps(pp, C.byref(caps)) >= 0:
                                row.update(usage_page=caps.UsagePage, usage=caps.Usage, input_bytes=caps.InputReportByteLength, output_bytes=caps.OutputReportByteLength, feature_bytes=caps.FeatureReportByteLength)
                        finally: hid.HidD_FreePreparsedData(pp)
                finally: kernel.CloseHandle(handle)
            else:
                row['open_error'] = C.get_last_error()
            result.append(row)
    finally: setup.SetupDiDestroyDeviceInfoList(info)
    return result

if __name__ == '__main__':
    print(json.dumps(inventory(), ensure_ascii=False, indent=2))
