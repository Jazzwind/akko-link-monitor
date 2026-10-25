import csv
import ctypes as C
import json
import os
from pathlib import Path
import queue
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from akko_monitor import app,identity,paths
from akko_monitor.markers import MarkerStore
from akko_monitor.startup import Registration,parse_approval,show_on_launch,MODES
from akko_monitor.tray import Tray,Notify,decode_action,make_icon,u
from test_app_detection import FakeReceiver,FakeTelemetry,FakeBluetooth
from test_detection import BT,RF

class FakeTray:
    def __init__(self):self.states=[];self.menu=[];self.stopped=False
    def update(self,*state):self.states.append(state)
    def set_menu(self,rows):self.menu=rows
    def stop(self):self.stopped=True

class TrayTests(unittest.TestCase):
    def test_only_double_click_marks(self):
        self.assertEqual(decode_action(0x203),'mark')
        for msg in (0x201,0x202,0x400,0x401):self.assertIsNone(decode_action(msg))
        self.assertEqual(decode_action(0x205),'menu')

    def test_native_icon_and_lifecycle(self):
        self.assertEqual(C.sizeof(Notify),976)
        for text in ('15','100','✓','!','?'):
            icon=make_icon(text);self.assertTrue(icon);u.DestroyIcon(icon)
        for _ in range(3):
            tray=Tray(queue.Queue(),'AkkoLinkMonitor.TestTray');tray.start();self.assertTrue(tray.hwnd)
            tray.update('15','AKKO Test');time.sleep(.05);tray.stop()
            self.assertFalse(tray.thread.is_alive());self.assertIsNone(tray.hwnd)

    def test_marker_feedback_save_failure_pause_and_double_click(self):
        with tempfile.TemporaryDirectory(prefix='AKKO 中文 空格 ') as temp:
            with patch.object(app,'BASE',Path(temp)),patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[]):
                root=tk.Tk();root.withdraw();monitor=app.App(root);tray=FakeTray();monitor.attach_tray(tray)
                try:
                    monitor.active_source='BT1';monitor.bt_status=True;monitor.bt_observed=time.perf_counter()
                    monitor.bt_battery={'percent':15,'queried_at':time.time(),'status':'windows_cached'}
                    monitor.detector.key(time.perf_counter(),BT,56,0,0x12)
                    for _ in range(2):monitor.tray_events.put(('tray_mark',time.time(),time.perf_counter()))
                    monitor.pump_tray()
                    rows=[json.loads(s) for s in (Path(temp)/'manual-markers.jsonl').read_text(encoding='utf8').splitlines()]
                    self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['marker_id'],rows[1]['marker_id'])
                    self.assertEqual(rows[0]['held_modifiers'],{'BT1':['Left Alt'],'2.4G':[]})
                    self.assertFalse(rows[0]['continuous_log_enabled']);self.assertEqual(tray.states[-1][0],'✓')
                    monitor.mark_feedback=(*monitor.mark_feedback[:3],time.perf_counter()-1)
                    monitor.refresh_tray();self.assertEqual(tray.states[-1][0],'15')
                    with patch.object(monitor.markers,'append',side_effect=PermissionError('test denied')):
                        self.assertFalse(monitor.mark_incident('window_button'))
                        self.assertEqual(tray.states[-1][0],'!')
                    self.assertEqual(len((Path(temp)/'manual-markers.jsonl').read_text(encoding='utf8').splitlines()),2)
                    monitor.toggle_log();self.assertTrue(monitor.mark_incident('window_button'))
                    with (monitor.folder/'events.csv').open(encoding='utf-8-sig') as f:events=list(csv.DictReader(f))
                    saved=json.loads((Path(temp)/'manual-markers.jsonl').read_text(encoding='utf8').splitlines()[-1])
                    self.assertIn(saved['marker_id'],next(e['description'] for e in events if e['kind']=='incident'))
                    monitor.hide_window();self.assertFalse(monitor.closing)
                    self.assertEqual(root.state(),'withdrawn')
                    monitor.tray_events.put(('tray',130));monitor.pump_tray()
                    self.assertTrue(monitor.closing)
                finally:monitor.close()
                self.assertTrue(tray.stopped)

class StartupTests(unittest.TestCase):
    def test_three_launch_modes(self):
        self.assertEqual([(show_on_launch(m,False),show_on_launch(m,True)) for m in MODES],[(True,True),(True,False),(False,False)])
    def test_approval_unknown_is_not_enabled(self):
        self.assertEqual(parse_approval(None),'not_recorded')
        self.assertEqual(parse_approval((3).to_bytes(4,'little')+bytes(8)),'disabled')
        self.assertEqual(parse_approval(bytes(12)),'unknown')
        self.assertEqual(parse_approval(b'bad'),'unknown')
    def test_shortcut_isolation_and_task_manager_disable_survives(self):
        import winreg,uuid
        key='Software\\AkkoLinkMonitorTest\\'+uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix='AKKO 中文 空格 ') as temp:
            r=Registration(temp,key)
            try:
                self.assertFalse(r.read().registered)
                r.set_registered(True);r.set_registered(True)
                self.assertEqual(len(list(Path(temp).glob('*.lnk'))),1)
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER,key) as k:
                    winreg.SetValueEx(k,r.shortcut.name,0,winreg.REG_BINARY,(3).to_bytes(4,'little')+bytes(8))
                self.assertEqual(r.read().approval,'disabled')
                r.set_registered(False);r.set_registered(True)
                self.assertEqual(r.read().approval,'disabled')
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k,r.shortcut.name,0,winreg.REG_BINARY,bytes(12))
                self.assertEqual(r.read().approval,'unknown')
                r.set_registered(False);self.assertFalse(r.read().registered)
            finally:
                try:winreg.DeleteKey(winreg.HKEY_CURRENT_USER,key)
                except FileNotFoundError:pass
    def test_migration_preserves_original_and_private_location(self):
        with tempfile.TemporaryDirectory() as temp:
            project=Path(temp)/'source';data=Path(temp)/'other user 中文'/'data';project.mkdir()
            original={'hold_seconds':3,'modifier_seconds':8,'power_queries_enabled':False,'unrelated':'not copied'}
            (project/'settings.json').write_text(json.dumps(original),encoding='utf8');(project/'logs').mkdir()
            with patch.object(paths,'PROJECT',project),patch.object(paths,'DATA',data),patch.object(paths,'DEFAULT_DATA',data):paths.prepare()
            self.assertEqual(json.loads((data/'settings.json').read_text(encoding='utf8'))['hold_seconds'],3)
            self.assertTrue((project/'logs').exists())
            self.assertEqual(json.loads((project/'settings.json').read_text(encoding='utf8')),original)
