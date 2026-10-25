"""Read only Windows' cached battery property for this verified BT1 device.

No GATT operations or connection attempts. The observed PnP byte property was
validated against an uncached standard 180F/2A19 read on this keyboard.
The cache's device-side measurement time is unknown.
"""
import ctypes as C
from ctypes import wintypes as W
import time
import uuid
from . import identity

def parse_cached_percent(raw, property_type):
    if property_type != 3 or len(raw)!=1 or raw[0]>100:
        raise ValueError('蓝牙电量缓存不是有效的 0–100 百分比字节')
    return raw[0]

def read_cached_battery():
    if not identity.BT_ADDRESS:raise LookupError('尚未绑定 AKKO BT1，请从主窗口选择蓝牙设备')
    prefix='BTHLE\\DEV_'+identity.BT_ADDRESS+'\\'
    for instance in identity.nodes():
        if not instance.upper().startswith(prefix):continue
        try:raw,kind=identity.read_property(instance,'104ea319-6ee2-4701-bd47-8ddbf425bbe5',2)
        except LookupError:continue
        percent=parse_cached_percent(raw,kind)
        return {'percent':percent,'status':'windows_cached','queried_at':time.time(),
                'source':'Windows PnP battery cache, validated against BLE 180F/2A19',
                'cache_freshness':'device_measurement_time_unknown','transport':'BT1',
                'instance':instance}
    raise LookupError('Windows 暂无这把 AKKO BT1 的电量缓存')
