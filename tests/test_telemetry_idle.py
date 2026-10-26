"""Synthetic clocks and requests only: never opens a real HID interface."""
import unittest
from unittest.mock import patch

from akko_monitor.telemetry import Telemetry, RF_IDLE_SECONDS


class IdleTelemetryTests(unittest.TestCase):
    def test_explicit_manual_query_runs_once_while_idle_or_disabled_without_retry(self):
        for error in (False,True):
            with self.subTest(timeout=error):
                telemetry=Telemetry();telemetry.refresh_power_once();waits=[]
                def wait(seconds):
                    waits.append(seconds)
                    if len(waits)==2:telemetry.exit.set()
                with patch('akko_monitor.telemetry.query_usb',return_value={}),patch('akko_monitor.telemetry.read_cached_battery',return_value={}),patch('akko_monitor.telemetry.read_power',side_effect=TimeoutError('synthetic timeout') if error else lambda:{}) as query,patch.object(telemetry.wake,'wait',side_effect=wait):
                    telemetry.run()
                self.assertEqual(query.call_count,1)
                self.assertEqual(waits,[30,30])
                self.assertFalse(telemetry.battery_allowed())
                self.assertIsNone(telemetry.last_rf_input)
                events=[]
                while not telemetry.events.empty():events.append(telemetry.events.get())
                self.assertTrue(next(data for kind,data,exc in events if kind=='battery')['manual_query'])

    def test_separate_explicit_clicks_each_request_one_query(self):
        telemetry=Telemetry();telemetry.refresh_power_once();waits=[]
        def wait(seconds):
            waits.append(seconds)
            if len(waits)==1:telemetry.refresh_power_once()
            else:telemetry.exit.set()
        with patch('akko_monitor.telemetry.query_usb',return_value={}),patch('akko_monitor.telemetry.read_cached_battery',return_value={}),patch('akko_monitor.telemetry.read_power',side_effect=lambda:{}) as query,patch.object(telemetry.wake,'wait',side_effect=wait):
            telemetry.run()
        self.assertEqual(query.call_count,2)
        self.assertFalse(telemetry.battery_allowed())

    def test_startup_refresh_and_old_input_cannot_query_idle_keyboard(self):
        clock=[100.0]
        with patch('akko_monitor.telemetry.time.perf_counter',side_effect=lambda:clock[0]):
            telemetry=Telemetry()
            telemetry.set_battery_enabled(True)
            self.assertFalse(telemetry.battery_allowed())
            telemetry.note_rf_input(100)
            self.assertTrue(telemetry.battery_allowed())
            clock[0]+=RF_IDLE_SECONDS
            telemetry.refresh()
            self.assertFalse(telemetry.battery_allowed())
            telemetry.note_rf_input(99)
            self.assertFalse(telemetry.battery_allowed())
            telemetry.note_rf_input(clock[0])
            self.assertTrue(telemetry.battery_allowed())
            telemetry.set_battery_enabled(False)
            telemetry.refresh()
            self.assertFalse(telemetry.battery_allowed())

    def test_timeout_retry_and_background_refresh_do_not_bypass_idle_deadline(self):
        clock=[100.0];waits=[]
        with patch('akko_monitor.telemetry.time.perf_counter',side_effect=lambda:clock[0]):
            telemetry=Telemetry();telemetry.note_rf_input(100);telemetry.set_battery_enabled(True)
            def wait(seconds):
                waits.append(seconds)
                if len(waits)==1:
                    clock[0]+=RF_IDLE_SECONDS
                    telemetry.refresh()
                else:telemetry.exit.set()
            with patch('akko_monitor.telemetry.query_usb',return_value={}),patch('akko_monitor.telemetry.read_cached_battery',return_value={}),patch('akko_monitor.telemetry.read_power',side_effect=TimeoutError('synthetic timeout')) as query,patch.object(telemetry.wake,'wait',side_effect=wait):
                telemetry.run()
            self.assertEqual(query.call_count,1)
            self.assertEqual(waits,[5,30])

    def test_active_queries_keep_normal_rate_and_replies_do_not_extend_activity(self):
        clock=[100.0];waits=[]
        with patch('akko_monitor.telemetry.time.perf_counter',side_effect=lambda:clock[0]):
            telemetry=Telemetry();telemetry.note_rf_input(100);telemetry.set_battery_enabled(True)
            def wait(seconds):
                waits.append(seconds)
                clock[0]+=30
                if len(waits)==1:telemetry.note_rf_input(clock[0])
                elif len(waits)==3:telemetry.exit.set()
            with patch('akko_monitor.telemetry.query_usb',return_value={}),patch('akko_monitor.telemetry.read_cached_battery',return_value={}),patch('akko_monitor.telemetry.read_power',side_effect=lambda:{}) as query,patch.object(telemetry.wake,'wait',side_effect=wait):
                telemetry.run()
            self.assertEqual(query.call_count,2)
            self.assertEqual(waits,[30,30,30])
