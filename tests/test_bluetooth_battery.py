import unittest
import os
from akko_monitor import identity
from akko_monitor.bluetooth_battery import parse_cached_percent,read_cached_battery
from akko_monitor.identity import BT_ADDRESS

class BluetoothBatteryTests(unittest.TestCase):
    def test_valid_percent_boundaries_and_zero(self):
        for value in (0,15,100):self.assertEqual(parse_cached_percent(bytes([value]),3),value)

    def test_unknown_value_wrong_type_and_wrong_length_are_not_percent(self):
        for raw,kind in [(b'\x65',3),(b'\xff',3),(b'\x0f',7),(b'',3),(b'\x0f\x00',3)]:
            with self.assertRaises(ValueError):parse_cached_percent(raw,kind)

    @unittest.skipUnless(os.environ.get('AKKO_HARDWARE_TESTS')=='1','可选实机测试')
    def test_this_pc_passive_cache_matches_verified_identity(self):
        previous=identity.BT_ADDRESS
        candidates=identity.discover()
        if len(candidates)!=1:self.skipTest('没有唯一的 AKKO BT1')
        identity.configure(candidates[0]['address'])
        try:data=read_cached_battery()
        finally:identity.configure(previous)
        self.assertIn('DEV_'+candidates[0]['address'],data['instance'].upper())
        self.assertEqual(data['status'],'windows_cached')
        self.assertEqual(data['cache_freshness'],'device_measurement_time_unknown')
        self.assertTrue(0<=data['percent']<=100)

if __name__=='__main__':unittest.main()
