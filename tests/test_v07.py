import json
from pathlib import Path
import queue
import tempfile
import time
import tkinter as tk
import unittest
import os
import subprocess
from unittest.mock import patch
from akko_monitor import app
from akko_monitor.gestures import Gestures
from akko_monitor.log_migration import merge_logs,manifest
from akko_monitor import paths
from akko_monitor.startup import ensure_launcher
from test_app_detection import FakeReceiver,FakeTelemetry,FakeBluetooth
from test_tray_startup import FakeTray

class GestureTests(unittest.TestCase):
    def test_single_double_and_long_second_click_do_not_overlap(self):
        events=[];g=Gestures(events.append)
        g.down(10,0);g.up(10.1,.1);self.assertEqual(events,[])
        g.down(11,1,True);g.up(11.1,1.1)
        self.assertEqual([e[0] for e in events],['tray_mark'])
        events.clear();g.down(12,2,True);g.tick(3);g.tick(3.1);g.up(13.5,3.5)
        self.assertEqual([e[0] for e in events],['tray_hold_ready','tray_hold'])
        self.assertEqual(events[-1][-1],1.5)
        g.up(14,4);self.assertEqual(len(events),2)
    def test_drag_cancel_does_not_start_outage(self):
        events=[];g=Gestures(events.append)
        g.down(10,0);g.tick(1);g.cancel();g.up(12,2)
        self.assertEqual([e[0] for e in events],['tray_hold_ready','tray_hold_cancelled'])

class MergeTests(unittest.TestCase):
    def test_custom_test_data_never_migrates_production_project_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            project=Path(temp)/'source';data=Path(temp)/'fixture'
            (project/'logs/session').mkdir(parents=True);(project/'logs/session/sample.csv').write_text('keep')
            with patch.object(paths,'PROJECT',project),patch.object(paths,'DATA',data),patch.dict(os.environ,{'AKKO_MONITOR_DATA_DIR':str(data)}):paths.prepare()
            self.assertTrue((project/'logs/session/sample.csv').exists())
            self.assertFalse((data/'logs/session').exists())
    def test_import_virtualized_records_into_real_user_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            local=Path(temp);data=local/'AkkoLinkMonitor';data.mkdir()
            old=local/'Packages/FakePackage/LocalCache/Local/AkkoLinkMonitor'
            (old/'logs/session').mkdir(parents=True);(old/'logs/session/sample.csv').write_text('original')
            (old/'settings.json').write_text('{"hold_seconds": 4}')
            (old/'manual-markers.jsonl').write_text('{"marker_id":"test-one"}\n')
            with patch.object(paths,'DATA',data),patch.object(paths,'DEFAULT_DATA',data),patch.dict(os.environ,{'LOCALAPPDATA':str(local)}):
                # This fixture deliberately tests a default-root import; the
                # entire legacy tree is synthetic, even in an isolated runner.
                os.environ.pop('AKKO_MONITOR_DATA_DIR',None)
                paths.import_legacy_data();paths.import_legacy_data()
            self.assertEqual((data/'logs/session/sample.csv').read_text(),'original')
            self.assertEqual(json.loads((data/'settings.json').read_text())['hold_seconds'],4)
            self.assertEqual(len((data/'manual-markers.jsonl').read_text().splitlines()),1)
            self.assertTrue((old/'logs').exists())

    def test_merge_preserves_all_files_and_handles_collisions(self):
        with tempfile.TemporaryDirectory() as temp:
            old=Path(temp)/'old/logs';new=Path(temp)/'new/logs'
            for root,session,value in ((old,'one','old'),(new,'one','new'),(old,'two','same'),(new,'two','same')):
                path=root/session/'sample.csv';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
            result=merge_logs(old,new)
            self.assertTrue(old.exists());self.assertEqual(len(result),2)
            self.assertEqual((new/'one/sample.csv').read_text(),'new')
            self.assertEqual((new/'one-legacy-1/sample.csv').read_text(),'old')
            self.assertEqual((new/'two/sample.csv').read_text(),'same')
            merge_logs(old,new)
            self.assertEqual(len(list(new.iterdir())),3)
    def test_copy_failure_keeps_source(self):
        with tempfile.TemporaryDirectory() as temp:
            old=Path(temp)/'old/logs';new=Path(temp)/'new/logs'
            (old/'one').mkdir(parents=True);(old/'one/sample.csv').write_text('source')
            with patch('akko_monitor.log_migration.shutil.copytree',side_effect=OSError('test failure')):
                with self.assertRaises(OSError):merge_logs(old,new)
            self.assertTrue((old/'one/sample.csv').exists())
    def test_same_or_nested_roots_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'logs';root.mkdir()
            with self.assertRaises(ValueError):merge_logs(root,root)
            with self.assertRaises(ValueError):merge_logs(root,root/'logs')

class AppTests(unittest.TestCase):
    def test_named_launcher_metadata(self):
        exe=ensure_launcher()
        path=str(exe).replace("'","''")
        script="$v=(Get-Item -LiteralPath '"+path+"').VersionInfo; [Console]::Write($v.FileDescription+'|'+$v.ProductName)"
        result=subprocess.check_output(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.decode(),'AKKO Link Monitor|AKKO Link Monitor')
    def test_folder_routes_usb_toggle_and_long_outage(self):
        with tempfile.TemporaryDirectory(prefix='AKKO dirs ') as temp:
            with patch.object(app,'BASE',Path(temp)),patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[]):
                root=tk.Tk();root.withdraw();monitor=app.App(root);tray=FakeTray();monitor.attach_tray(tray)
                try:
                    with patch.object(app.subprocess,'Popen') as launch:
                        monitor.tray_events.put(('tray',103));monitor.tray_events.put(('tray',104));monitor.pump_tray()
                        self.assertEqual(Path(launch.call_args_list[0].args[0][1]),Path(temp)/'logs')
                        self.assertEqual(Path(launch.call_args_list[1].args[0][1]),Path(temp))
                        self.assertEqual(Path(launch.call_args.args[0][0]).name,'explorer.exe')
                    with patch.object(monitor,'start_reports') as start:
                        monitor.tray_events.put(('tray',106));monitor.pump_tray();start.assert_called_once()
                    with patch.object(monitor,'open_logs',side_effect=OSError('test folder failure')):
                        monitor.tray_events.put(('tray',103));monitor.tray_events.put(('tray',101));monitor.pump_tray()
                        self.assertIn('test folder failure',monitor.last_marker_text)
                    before=time.perf_counter()-3
                    monitor.tray_events.put(('tray_hold',time.time()-3,before,time.time()-1.5,before+1.5,1.5));monitor.pump_tray()
                    self.assertIsNotNone(monitor.manual_outage)
                    monitor.mark_feedback=None;monitor.refresh_tray();self.assertEqual(tray.states[-1][0],'断')
                    monitor.tray_events.put(('tray_hold',time.time()-1,time.perf_counter()-1,time.time(),time.perf_counter(),1));monitor.pump_tray()
                    self.assertIsNone(monitor.manual_outage)
                    rows=[json.loads(s) for s in (Path(temp)/'manual-markers.jsonl').read_text(encoding='utf8').splitlines()]
                    self.assertEqual([r['phase'] for r in rows],['started','ended'])
                    self.assertEqual(rows[0]['outage_id'],rows[1]['outage_id'])
                    self.assertGreaterEqual(rows[1]['duration_seconds'],3)
                    self.assertEqual(rows[0]['operation']['hold_seconds'],1.5)
                    self.assertNotIn(105,[r[0] for r in tray.menu])
                    monitor.tray_command(107);self.assertIsNotNone(monitor.manual_outage)
                finally:monitor.close()
                rows=[json.loads(s) for s in (Path(temp)/'manual-markers.jsonl').read_text(encoding='utf8').splitlines()]
                self.assertEqual(rows[-1]['phase'],'observation_ended')
