"""Verify idle monitoring does not open HID handles or poll USB descriptors."""
import ctypes as C
import unittest
from unittest.mock import patch
from akko_monitor import devices
from akko_monitor.telemetry import Telemetry

class PassiveIOTests(unittest.TestCase):
    def test_default_inventory_uses_os_metadata_without_hid_open_or_strings(self):
        path=r'\\?\hid#vid_320f&pid_506a&mi_00#synthetic'
        wide=C.create_unicode_buffer(path)
        def detail(handle,interface,buffer,size,needed,dev):
            if buffer is None:needed._obj.value=C.sizeof(wide)+4
            else:C.memmove(C.addressof(buffer)+4,wide,C.sizeof(wide))
            return 1
        def instance(handle,dev,buffer,*args):
            buffer.value=r'USB\VID_320F&PID_506A\synthetic';return 1
        with patch.object(devices.setup,'SetupDiGetClassDevsW',return_value=1),patch.object(devices.setup,'SetupDiEnumDeviceInterfaces',side_effect=[1,0]),patch.object(devices.C,'get_last_error',return_value=259),patch.object(devices.setup,'SetupDiGetDeviceInterfaceDetailW',side_effect=detail),patch.object(devices.setup,'SetupDiGetDeviceInstanceIdW',side_effect=instance),patch.object(devices.setup,'SetupDiDestroyDeviceInfoList'),patch.object(devices.kernel,'CreateFileW',side_effect=AssertionError('HID open forbidden')) as opened,patch.object(devices.hid,'HidD_GetProductString',side_effect=AssertionError('USB string request forbidden')) as strings:
            rows=devices.inventory()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['vid_pid'],'320F:506A')
        opened.assert_not_called();strings.assert_not_called()

    def test_background_refresh_does_not_read_usb_or_power(self):
        telemetry=Telemetry();telemetry.refresh();waits=[]
        def wait(seconds):
            waits.append(seconds)
            if len(waits)==2:telemetry.exit.set()
        with patch('akko_monitor.telemetry.query_usb',side_effect=AssertionError('USB poll forbidden')) as usb,patch('akko_monitor.telemetry.read_power',side_effect=AssertionError('power poll forbidden')) as power,patch('akko_monitor.telemetry.read_cached_battery',return_value={}),patch.object(telemetry.wake,'wait',side_effect=wait):
            telemetry.run()
        usb.assert_not_called();power.assert_not_called()

    def test_explicit_usb_read_runs_once_and_does_not_enable_power_queries(self):
        telemetry=Telemetry();telemetry.refresh_usb_once();waits=[]
        def wait(seconds):
            waits.append(seconds)
            if len(waits)==2:telemetry.exit.set()
        with patch('akko_monitor.telemetry.query_usb',return_value={}) as usb,patch('akko_monitor.telemetry.read_power') as power,patch('akko_monitor.telemetry.read_cached_battery',return_value={}),patch.object(telemetry.wake,'wait',side_effect=wait):
            telemetry.run()
        usb.assert_called_once();power.assert_not_called()
        self.assertIsNone(telemetry.last_rf_input)
