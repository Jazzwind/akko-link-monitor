import ctypes
import time
import unittest
import struct
import uuid
import os
from akko_monitor.battery import parse_power
from akko_monitor.usb_info import parse_configuration, interval_ms
from akko_monitor.etw_reports import UcxDecoder, ReportStats, verify_schemas, EventHeader, Record, Logfile
from akko_monitor.metrics import Metrics
from akko_monitor.raw_input import Receiver, Header, Keyboard
from akko_monitor.devices import inventory

class MonitorTests(unittest.TestCase):
    def test_repeat_and_release(self):
        m=Metrics(); m.key(1,30,0); m.key(1.5,30,0); m.key(2,30,1)
        self.assertEqual((m.downs,m.ups,m.repeats,len(m.pressed)),(1,1,1,0))

    def test_extended_keys_are_distinct(self):
        m=Metrics(); m.key(1,28,0); m.key(2,28,2); m.key(3,28,3)
        self.assertEqual(len(m.pressed),1)
        self.assertEqual(m.orphans,0)

    def test_disconnect_resets_holds_and_interval(self):
        m=Metrics(); m.key(1,30,0)
        self.assertEqual(m.reset_pressed(),1)
        m.key(100,31,0)
        self.assertEqual(list(m.intervals),[])
        m.key(101,30,1)
        self.assertEqual(m.orphans,1)

    def test_native_structures(self):
        self.assertEqual(ctypes.sizeof(Header),24 if ctypes.sizeof(ctypes.c_void_p)==8 else 16)
        self.assertEqual(ctypes.sizeof(Keyboard),16)

    def test_start_stop_three_times(self):
        for _ in range(3):
            r=Receiver(); r.start(); self.assertTrue(r.hwnd)
            r.stop(); self.assertFalse(r.thread.is_alive())

    @unittest.skipUnless(os.environ.get('AKKO_HARDWARE_TESTS')=='1','可选实机测试')
    def test_inventory_has_akko(self):
        rows=inventory('320F:506B')
        self.assertTrue(rows)
        self.assertTrue(all(r['vid_pid']=='320F:506B' for r in rows))

    def test_power_reply_and_unknown_charging(self):
        reply=bytes.fromhex('04 20 00 1a 06 00 00 01 2c 01')+bytes(54)
        r=parse_power(reply)
        self.assertEqual(r['percent'],44)
        self.assertEqual(r['charging'],'unverified')
        self.assertEqual(r['power_state_raw'],1)
        # Real replies echo the request checksum; they do not checksum reply data.
        self.assertNotEqual(sum(reply[3:]),int.from_bytes(reply[1:3],'little'))
        for offset,value in ((0,0),(3,0),(7,255),(8,101)):
            bad=bytearray(reply);bad[offset]=value
            with self.assertRaises(ValueError):parse_power(bytes(bad))

    def test_usb_real_descriptor(self):
        data=bytes.fromhex('09023b00020100a032090400000103010100092101010001224b000705810340000109040100010301020009210101000122d70007058203400001')
        rows=parse_configuration(data,1)
        self.assertEqual([(r['endpoint'],r['interval_ms'],r['nominal_hz']) for r in rows],[('0x81',1.,1000.),('0x82',1.,1000.)])
        self.assertEqual(interval_ms(2,4),1.)
        self.assertEqual(interval_ms(2,1),.125)
        with self.assertRaises(ValueError):parse_configuration(data[:-1],1)

    def test_raw_event_intervals_include_repeats(self):
        m=Metrics();m.key(1,30,0);m.key(1.5,30,0);m.key(2,30,1)
        self.assertEqual(m.event_summary()['events_total'],3)
        self.assertEqual(list(m.event_intervals),[500,500])

    def test_etw_filter_and_error_counts(self):
        decoder=UcxDecoder('\\\\?\\usb#root_hub',6,10_000_000)
        decoder.consume(4,0,0,struct.pack('<QQ',1,2)+'\\\\?\\usb#root_hub\0'.encode('utf-16-le'))
        decoder.consume(5,0,0,struct.pack('<QQQII6I',1,2,3,1,1,6,0,0,0,0,0))
        decoder.consume(6,0,0,struct.pack('<QQQBBBBHB',3,4,5,7,5,0x81,3,64,1))
        self.assertTrue(decoder.mapped)
        def complete(device=3,status=0,size=8):
            b=bytearray(172);struct.pack_into('<QQQQQ',b,0,1,device,5,6,7)
            struct.pack_into('<I',b,44,status);struct.pack_into('<II',b,72,1,size)
            return bytes(b)
        decoder.consume(27,0,10_000_000,complete())
        decoder.consume(27,1,10_010_000,complete())
        decoder.consume(27,0,10_020_000,complete(device=99))
        decoder.consume(27,0,10_030_000,complete(status=0xC0000001))
        decoder.consume(27,0,10_040_000,complete(size=0))
        decoder.consume(27,9,10_050_000,complete())
        stat=decoder.summary()['0x81']
        self.assertEqual(stat['reports_total'],2)
        self.assertEqual(stat['transfer_errors'],1)
        self.assertEqual(stat['last_interval_ms'],1.)

    def test_etw_timestamp_precision(self):
        s=ReportStats(10_000_000);s.add(10**17,8);s.add(10**17+1,8)
        self.assertEqual(s.summary()['min_ms'],.0001)

    def test_etw_os_schema_and_struct_sizes(self):
        self.assertEqual([ctypes.sizeof(t) for t in (EventHeader,Record,Logfile)],[80,112,448])
        verify_schemas()

if __name__=='__main__': unittest.main()
