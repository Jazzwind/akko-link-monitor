"""UI/log integration with synthetic in-process events; never injects OS keys."""
import csv
import json
from pathlib import Path
import queue
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from akko_monitor import app

class FakeReceiver:
    def __init__(self):self.events=queue.Queue();self.dropped=0
    def start(self):pass
    def stop(self):pass

class FakeTelemetry:
    def __init__(self):self.events=queue.Queue();self.enabled=True
    def start(self):pass
    def stop(self):pass
    def refresh(self):pass
    def note_rf_input(self,observed_at):pass
    def refresh_power_once(self):pass
    def set_battery_enabled(self,value):self.enabled=value

class FakeBluetooth:
    def __init__(self,events):pass
    def start(self):pass
    def stop(self):pass

class AppDetectionTests(unittest.TestCase):
    def test_manual_refresh_idle_display_and_bt_cache_routing(self):
        from test_tray_startup import FakeTray
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(app,'BASE',Path(temp)),patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[]):
                root=tk.Tk();root.withdraw();monitor=app.App(root);tray=FakeTray();monitor.attach_tray(tray)
                try:
                    monitor.probes_enabled.set(False);monitor.toggle_probes()
                    with patch.object(monitor.telemetry,'refresh_power_once') as query:
                        monitor.tray_command(101);query.assert_called_once()
                    self.assertFalse(monitor.rf_probes_active)
                    self.assertIsNone(monitor.last_rf_activity)
                    result={'manual_query':True,'percent':42,'queried_at':time.time(),'power_state_raw':1,'status':'device_reported'}
                    monitor.telemetry.events.put(('battery',result,None));monitor.pump()
                    self.assertEqual(monitor.battery_sample('')[:2],[42,'manual_receiver_read'])
                    self.assertEqual(monitor.active_source,'')
                    self.assertFalse(monitor.rf_probes_active)
                    result['queried_at']-=31
                    self.assertEqual(monitor.battery_sample('')[0],'')
                    monitor.telemetry.events.put(('battery',{'manual_query':True,'error_kind':'TimeoutError'},'synthetic timeout'));monitor.pump()
                    self.assertFalse(monitor.detector.snapshots(time.perf_counter()))
                    self.assertEqual(monitor.battery_sample('')[1],'manual_query_failed')
                    self.assertEqual(tray.states[-1][0],'!')
                    self.assertIn('synthetic timeout',tray.states[-1][1])
                    self.assertEqual(monitor.last_marker_text,'尚未手动标记')
                    monitor.mark_feedback=(*monitor.mark_feedback[:3],time.perf_counter()-1)
                    monitor.refresh_tray();monitor.refresh_tray()
                    self.assertEqual(tray.states[-1][0],'42')
                    self.assertIn('最后已知',tray.states[-1][1])
                    self.assertIn('手动刷新失败',tray.states[-1][1])
                    monitor.active_source='BT1'
                    with patch.object(monitor.telemetry,'refresh_power_once') as query,patch.object(monitor.telemetry,'refresh') as cache:
                        monitor.tray_command(101);query.assert_not_called();cache.assert_called_once()
                finally:monitor.close()

    def test_idle_pauses_queries_without_false_recovery_and_ignores_repeats(self):
        from test_detection import RF,BT
        from test_tray_startup import FakeTray
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(app,'BASE',Path(temp)),patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[]):
                root=tk.Tk();root.withdraw();monitor=app.App(root);tray=FakeTray();monitor.attach_tray(tray)
                try:
                    self.assertEqual(tray.states[-1][0],'?')
                    now=time.perf_counter()
                    monitor.receiver.events.put(('key',now,RF,30,0,65));monitor.pump()
                    self.assertTrue(monitor.rf_probes_active)
                    monitor.detector.set_usb(True,now)
                    monitor.detector.probe(False,True,now+1,now)
                    monitor.last_rf_activity=now-app.RF_IDLE_SECONDS
                    monitor.update_probe_policy(now)
                    self.assertFalse(monitor.telemetry.enabled)
                    self.assertIsNone(monitor.detector.wireless)
                    episodes=monitor.detector.snapshots(now)
                    self.assertTrue(any(e['reason']=='power_queries_paused_idle_state_unknown' and e['phase']!='resolved' for e in episodes))
                    monitor.battery={'percent':50,'status':'device_reported','queried_at':time.time()}
                    self.assertEqual(monitor.battery_sample('2.4G')[:3],['','queries_paused_idle',50])
                    monitor.refresh_tray()
                    self.assertEqual(tray.states[-1][0],'50')
                    self.assertIn('最后已知',tray.states[-1][1])
                    self.assertIn('闲置暂停',tray.states[-1][1])
                    self.assertIn('距读取',tray.states[-1][1])
                    self.assertEqual(tray.states[-1][3],0x9ba5b3)
                    monitor.telemetry.events.put(('battery',{'percent':99},None))
                    monitor.receiver.events.put(('key',time.perf_counter(),RF,30,0,65));monitor.pump()
                    self.assertFalse(monitor.rf_probes_active)
                    self.assertEqual(monitor.battery['percent'],50)
                    monitor.receiver.events.put(('key',time.perf_counter(),RF,30,1,65));monitor.pump()
                    self.assertTrue(monitor.telemetry.enabled)
                    monitor.probes_enabled.set(False);monitor.toggle_probes()
                    monitor.receiver.events.put(('key',time.perf_counter(),RF,30,0,65));monitor.pump()
                    self.assertFalse(monitor.telemetry.enabled)
                    monitor.probes_enabled.set(True);monitor.toggle_probes()
                    self.assertTrue(monitor.telemetry.enabled)
                    monitor.receiver.events.put(('key',time.perf_counter(),BT,31,0,83));monitor.pump()
                    self.assertFalse(monitor.telemetry.enabled)
                finally:monitor.close()

    def test_dual_mode_csv_modifier_context_and_probe_gating(self):
        from test_detection import RF,BT
        verify=Path(__file__).resolve().parent/'verification';verify.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=verify) as temp:
            with patch.object(app,'BASE',Path(temp)),patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[]):
                root=tk.Tk();root.withdraw();monitor=app.App(root)
                try:
                    monitor.toggle_log();now=time.perf_counter()
                    self.assertFalse(monitor.telemetry.enabled)
                    monitor.telemetry.events.put(('bluetooth',{'connected':True},None))
                    monitor.telemetry.events.put(('bt_battery',{'percent':15,'status':'windows_cached','queried_at':time.time(),'cache_freshness':'device_measurement_time_unknown','source':'synthetic Windows cache'},None))
                    monitor.receiver.events.put(('key',now-7,BT,56,0,0x12))
                    monitor.receiver.events.put(('key',now-6,BT,15,0,9))
                    for i in range(1,49):monitor.receiver.events.put(('key',now-6+i*.05,BT,15,0,9))
                    monitor.receiver.events.put(('key',now-.1,BT,15,1,9))
                    monitor.pump()
                    self.assertEqual(monitor.active_source,'BT1')
                    self.assertFalse(monitor.telemetry.enabled)
                    monitor.sample()
                    monitor.save_auto_state(time.perf_counter(),True)
                    state=json.loads((monitor.folder/'automatic-state.json').read_text(encoding='utf8'))
                    self.assertTrue(state['bluetooth_connected'])
                    self.assertTrue(any(e['key_name']=='Left Alt' and e['repeat_count']==0 for e in state['events']))
                    tab=next(e for e in state['events'] if e['key_name']=='Tab')
                    self.assertEqual(tab['transport'],'BT1')
                    self.assertEqual(json.loads(tab['evidence_json'])['modifiers_at_detection'],['Left Alt'])
                    with (monitor.folder/'samples.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
                    self.assertTrue(any(r['transport']=='BT1' and r['battery_status']=='windows_cached' and r['battery_percent']=='15' and r['battery_transport']=='BT1' for r in rows))
                    with (monitor.folder/'bluetooth-battery.csv').open(encoding='utf-8-sig') as f:power_rows=list(csv.DictReader(f))
                    self.assertEqual(power_rows[0]['percent'],'15')
                    # New RF input resumes only its query/detection; old BT hold
                    # is retained as unconfirmed, not fabricated as released.
                    monitor.receiver.events.put(('key',time.perf_counter(),RF,30,0,65));monitor.pump()
                    self.assertEqual(monitor.active_source,'2.4G')
                    self.assertTrue(monitor.telemetry.enabled)
                    self.assertTrue(any(s.name=='Left Alt' for s in monitor.detector.keys.values()))
                    monitor.battery={'percent':44,'status':'device_reported','queried_at':time.time()}
                    self.assertEqual(monitor.battery_sample('2.4G')[0],44)
                    self.assertEqual(monitor.battery_sample('BT1')[0],15)
                    monitor.telemetry.events.put(('bluetooth',{'connected':False},None));monitor.pump()
                    self.assertEqual(monitor.battery_sample('BT1')[0],'')
                    self.assertEqual(monitor.battery_sample('BT1')[2],15)
                    self.assertTrue(any(r['category']=='bluetooth_disconnect' for r in monitor.detector.snapshots(time.perf_counter())))
                finally:monitor.close()

    def test_ui_csv_state_and_resume_logging(self):
        verify=Path(__file__).resolve().parent/'verification';verify.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=verify) as temp:
            with patch.object(app,'BASE',Path(temp)),patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[{'vid_pid':app.TARGET,'path':'hid#vid_320f&pid_506b#test'}]):
                root=tk.Tk();root.withdraw()
                monitor=app.App(root)
                try:
                    monitor.toggle_log()
                    first=monitor.folder
                    now=time.perf_counter()
                    monitor.detector.probes_enabled=True
                    monitor.detector.set_usb(True,now-10)
                    monitor.detector.probe(False,True,now-4,now-5.5)
                    monitor.receiver.events.put(('key',now-3,'synthetic-AKKO',48,0,66))
                    for i in range(1,49):monitor.receiver.events.put(('key',now-3+i*.05,'synthetic-AKKO',48,0,66))
                    monitor.receiver.events.put(('key',now-.1,'synthetic-AKKO',48,1,66))
                    monitor.pump()
                    monitor.detector.probe(True,False,time.perf_counter())
                    monitor.last_auto_render=0;monitor.render()
                    monitor.save_auto_state(time.perf_counter(),force=True)
                    state=json.loads((first/'automatic-state.json').read_text(encoding='utf8'))
                    self.assertEqual(len(state['events']),2)
                    self.assertTrue(all(e['phase']=='resolved' for e in state['events']))
                    self.assertTrue(any(e['key_name']=='B' for e in state['events']))
                    self.assertEqual(len(monitor.auto_tree.get_children()),2)
                    with (first/'automatic-events.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
                    self.assertTrue(any(e['phase']=='detected' and e['key_name']=='B' for e in rows))
                    self.assertTrue(any(e['phase']=='resolved' and e['reason']=='key_release_received' for e in rows))
                    self.assertTrue(any(e['reason']=='power_query_response_received' for e in rows))
                    self.assertTrue(all(set(e)==set(app.AUTO_FIELDS) for e in rows))
                    # Resuming logging preserves state IDs as explicit snapshots.
                    monitor.toggle_log();monitor.toggle_log()
                    second=monitor.folder
                    with (second/'automatic-events.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
                    self.assertTrue(any(e['phase']=='log_start_snapshot' for e in rows))
                    monitor.probes_enabled.set(False);monitor.toggle_probes()
                    monitor.hold_threshold.set('3.5');monitor.update_threshold()
                    saved=json.loads((Path(temp)/'settings.json').read_text(encoding='utf8'))
                    self.assertEqual(saved,{'hold_seconds':3.5,'modifier_seconds':5,'power_queries_enabled':False,'launch_mode':'ManualWindowStartupTray'})
                    self.assertEqual(len(monitor.detector.keys),0)
                finally:monitor.close()

if __name__=='__main__':unittest.main()
