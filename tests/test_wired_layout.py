"""Synthetic wired traces and font metrics; no hardware requests or key injection."""
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from akko_monitor import app,identity
from akko_monitor.detection import Detector
from test_app_detection import FakeReceiver,FakeTelemetry,FakeBluetooth
from test_detection import RF

WIRED=r'\\?\hid#vid_320f&pid_506a&mi_00#synthetic'

class WiredTests(unittest.TestCase):
    def test_wired_identity_and_stuck_k_are_separate_from_radio(self):
        self.assertEqual(identity.source_for(WIRED),'有线 USB')
        self.assertFalse(identity.source_for(r'\\?\hid#vid_046d&pid_c52b#synthetic'))
        events=[];detector=Detector(events.append,mono_anchor=0,wall_anchor=0)
        detector.set_usb(True,0);detector.probe(False,True,1)
        self.assertFalse(detector.key(2,WIRED,37,0,75))
        for index in range(1,61):detector.key(2+index*.05,WIRED,37,0,75)
        stuck=[e for e in events if e['category']=='suspected_stuck_key'][-1]
        self.assertEqual(stuck['key_name'],'K')
        self.assertEqual(stuck['transport'],'有线 USB')
        self.assertEqual(json.loads(stuck['evidence_json'])['wireless_episode_at_detection'],'')
        self.assertNotIn('input_activity_at',detector.wireless.evidence)
        detector.set_usb(False,6)  # Receiver removal does not release wired keys.
        detector.key(30,WIRED,30,0,65)  # Another key does not prove K was released.
        self.assertTrue(any(s.name=='K' for s in detector.keys.values()))
        detector.key(40,WIRED,37,1,75)
        resolved=[e for e in events if e['key_name']=='K'][-1]
        self.assertEqual(resolved['phase'],'resolved')
        self.assertEqual(resolved['duration_seconds'],38)
        detector.key(41,WIRED,52,0,190)
        for index in range(1,61):detector.key(41+index*.05,WIRED,52,0,190)
        self.assertTrue(any(e['key_name']=='Period key' and e['transport']=='有线 USB' for e in events))

    def test_wired_ui_log_marker_and_explicit_manual_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(app,'BASE',Path(temp)),patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[]):
                root=tk.Tk();root.withdraw();monitor=app.App(root)
                try:
                    monitor.toggle_log();now=time.perf_counter()
                    monitor.receiver.events.put(('key',now-5,WIRED,37,0,75))
                    for i in range(1,61):monitor.receiver.events.put(('key',now-5+i*.05,WIRED,37,0,75))
                    monitor.pump()
                    self.assertEqual(monitor.active_source,'有线 USB')
                    self.assertFalse(monitor.telemetry.enabled)
                    with patch.object(monitor,'scan') as scan:
                        monitor.sample();monitor.sample();scan.assert_not_called()
                    self.assertEqual(monitor.battery_sample('有线 USB')[1],'wired_battery_protocol_unverified')
                    with patch.object(monitor.telemetry,'refresh_power_once') as query:
                        monitor.refresh_battery_once();query.assert_called_once()
                    self.assertEqual(monitor.active_source,'有线 USB')
                    self.assertTrue(monitor.mark_incident('window_button'))
                    marker=json.loads((Path(temp)/'manual-markers.jsonl').read_text(encoding='utf-8').splitlines()[-1])
                    self.assertEqual(marker['last_input_source'],'有线 USB')
                    monitor.save_auto_state(time.perf_counter(),force=True)
                    state=json.loads((monitor.folder/'automatic-state.json').read_text(encoding='utf-8'))
                    self.assertTrue(any(e['key_name']=='K' and e['transport']=='有线 USB' for e in state['events']))
                finally:monitor.close()

class LayoutTests(unittest.TestCase):
    def test_table_rows_fit_scaled_fonts_and_have_both_scrollbars(self):
        for scale in (1.0,1.5,2.0):
            with self.subTest(scale=scale),tempfile.TemporaryDirectory() as temp:
                with patch.object(app,'BASE',Path(temp)),patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[]):
                    root=tk.Tk();root.withdraw();root.tk.call('tk','scaling',scale)
                    monitor=app.App(root)
                    try:
                        height=int(ttk.Style(root).lookup('Treeview','rowheight'))
                        self.assertGreaterEqual(height,monitor.table_font.metrics('linespace')+8)
                        for tree in (monitor.auto_tree,monitor.tree,monitor.report_tree,monitor.timing_tree):
                            bars=[w for w in tree.master.winfo_children() if isinstance(w,ttk.Scrollbar)]
                            self.assertEqual({str(w.cget('orient')) for w in bars},{'vertical','horizontal'})
                    finally:monitor.close()
