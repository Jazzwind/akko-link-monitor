"""3098N firmware-reported battery via the verified official power query."""
import time
from .hid_transport import exchange_power

def parse_power(reply):
    if len(reply)!=64 or reply[0]!=4 or reply[3:7]!=bytes.fromhex('1A 06 00 00'):
        raise ValueError('不是已验证的 3098N 电量回复')
    if reply[7]!=1:
        raise ValueError(f'设备返回非成功状态 0x{reply[7]:02X}')
    if reply[8]>100:raise ValueError('电量字段超出百分比范围')
    # Byte 9 was 1 while unplugged: do NOT label this byte as charging.
    # Bytes 1:3 echo request checksum, not a checksum of the response payload.
    return {'percent':reply[8],'power_state_raw':reply[9],'payload_hex':reply[8:14].hex(' '),'reply_hex':reply.hex(' '),'status':'device_reported','charging':'unverified','wireless_freshness':'unverified','source':'3098N official command 0x1A, payload[0]','queried_at':time.time()}

def read_power():
    _,reply=exchange_power()
    return parse_power(reply)
