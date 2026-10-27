"""Mode refresh and native tray regression tests, with synthetic input only."""
import ctypes as C
from ctypes import wintypes as W
from pathlib import Path
import queue
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from akko_monitor import app,tray as native
from test_app_detection import FakeReceiver,FakeTelemetry,FakeBluetooth
from test_tray_startup import FakeTray
from test_detection import BT,RF
from test_wired_layout import WIRED


class ModeTrayTests(unittest.TestCase):
    def test_source_transitions_wake_cache_reader_and_manual_preview_is_not_input(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(app,'BASE',Path(temp)),patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[]):
                root=tk.Tk();root.withdraw();monitor=app.App(root);tray=FakeTray();monitor.attach_tray(tray)
                try:
                    monitor.receiver.events.put(('key',time.perf_counter(),WIRED,30,0,65));monitor.pump()
                    monitor.last_sources['有线 USB']=time.perf_counter()-10
                    monitor.bt_status=False
                    monitor.telemetry.events.put(('bluetooth',{'connected':True},None))
                    with patch.object(monitor.telemetry,'refresh') as cache:
                        monitor.pump();cache.assert_called()
                    self.assertEqual(monitor.active_source,'有线 USB')
                    self.assertEqual(monitor.battery_display_source(),'BT1')
                    monitor.telemetry.events.put(('bluetooth',{'connected':False},None));monitor.pump()
                    self.assertEqual(monitor.battery_preview_source,'')
                    monitor.bt_status=True;monitor.bt_observed=time.perf_counter()
                    monitor.bt_battery={'percent':72,'queried_at':time.time(),'status':'windows_cached'}
                    with patch.object(monitor.telemetry,'refresh') as refresh:
                        monitor.receiver.events.put(('key',time.perf_counter(),BT,31,0,83));monitor.pump()
                        refresh.assert_called()
                    self.assertEqual(monitor.active_source,'BT1')
                    self.assertEqual(tray.states[-1][0],'72')
                    with patch.object(monitor.telemetry,'refresh') as refresh:
                        monitor.receiver.events.put(('key',time.perf_counter(),RF,32,0,68));monitor.pump()
                        refresh.assert_called()
                    self.assertTrue(monitor.rf_probes_active)
                    monitor.receiver.events.put(('key',time.perf_counter(),WIRED,33,0,70));monitor.pump()
                    monitor.bt_status=False
                    with patch.object(monitor.telemetry,'refresh_power_once') as query:
                        monitor.refresh_battery_once();query.assert_called_once()
                    self.assertEqual(monitor.active_source,'有线 USB')
                    self.assertEqual(monitor.battery_display_source(),'2.4G')
                    self.assertFalse(monitor.rf_probes_active)
                    monitor.telemetry.events.put(('battery',{'manual_query':True,'percent':24,'queried_at':time.time(),'power_state_raw':1,'status':'device_reported'},None))
                    monitor.pump();monitor.refresh_tray()
                    self.assertEqual(tray.states[-1][0],'24')
                    self.assertIn('电量来源预览',tray.states[-1][1])
                    monitor.receiver.events.put(('key',time.perf_counter(),WIRED,34,0,71));monitor.pump()
                    self.assertEqual(monitor.battery_preview_source,'')
                    self.assertEqual(monitor.active_source,'有线 USB')
                    monitor.last_sources['有线 USB']=time.perf_counter()-10
                    monitor.bt_status=True;monitor.bt_observed=time.perf_counter()
                    with patch.object(monitor.telemetry,'refresh') as cache,patch.object(monitor.telemetry,'refresh_power_once') as query:
                        monitor.refresh_battery_once();cache.assert_called_once();query.assert_not_called()
                    self.assertEqual(monitor.battery_display_source(),'BT1')
                    self.assertEqual(monitor.active_source,'有线 USB')
                    monitor.refresh_menu()
                    self.assertEqual(tray.menu.count(None),5)
                    commands=[r[0] for r in tray.menu if r is not None]
                    self.assertLess(commands.index(107),commands.index(103))
                    monitor.tray_command(108)
                    now=time.perf_counter();wall=time.time()
                    for offset in (-5,-2):
                        monitor.tray_events.put(('tray_hold',wall+offset,now+offset,wall+offset+1.1,now+offset+1.1,1.1))
                        monitor.pump_tray()
                    self.assertIsNone(monitor.manual_outage)
                    import json
                    markers=[json.loads(line) for line in (Path(temp)/'manual-markers.jsonl').read_text(encoding='utf-8').splitlines()]
                    self.assertEqual([r['phase'] for r in markers if r.get('category')=='manual_prolonged_disconnect'],['started','ended'])
                finally:monitor.close()

    def test_menu_groups_and_native_separators_without_showing_popup(self):
        menu=[(100,'显示窗口',False,True,[]),None,(108,'标记',False,True,[]),None,(0,'选项',False,True,[(120,'隐藏',True,True,[])]),None,(130,'退出',False,True,[])]
        tray=native.Tray(queue.Queue());tray.menu=menu
        native.u.GetMenuItemCount.argtypes=[W.HMENU];native.u.GetMenuItemCount.restype=C.c_int
        native.u.GetMenuState.argtypes=[W.HMENU,W.UINT,W.UINT];native.u.GetMenuState.restype=W.UINT
        def inspect(handle,*args):
            self.assertEqual(native.u.GetMenuItemCount(handle),len(menu))
            for position in (1,3,5):self.assertTrue(native.u.GetMenuState(handle,position,0x400)&0x800)
            return 0
        with patch.object(native.u,'TrackPopupMenu',side_effect=inspect),patch.object(native.u,'SetForegroundWindow'),patch.object(native.u,'PostMessageW'):
            tray.popup()

    def test_polled_hold_survives_icon_relocation_and_cancels_actual_drag(self):
        events=queue.Queue();tray=native.Tray(events)
        state={'down':True,'point':(10,10),'rect':(0,0,30,30),'time':10.0}
        def cursor(pointer):pointer._obj.x,pointer._obj.y=state['point'];return 1
        def rect(identifier,pointer):
            pointer._obj.left,pointer._obj.top,pointer._obj.right,pointer._obj.bottom=state['rect'];return 0
        with patch.object(native.u,'GetAsyncKeyState',side_effect=lambda key:0x8000 if state['down'] else 0),patch.object(native.u,'GetCursorPos',side_effect=cursor),patch.object(native.s,'Shell_NotifyIconGetRect',side_effect=rect),patch.object(native.time,'perf_counter',side_effect=lambda:state['time']),patch.object(native.time,'time',side_effect=lambda:state['time']+1000):
            tray.poll_hold()
            state.update(time=11.1,rect=(100,100,130,130));tray.poll_hold()
            state.update(time=11.2,down=False);tray.poll_hold()
            state.update(time=12,down=True,rect=(0,0,30,30));tray.poll_hold()
            state.update(time=13.1);tray.poll_hold()
            state.update(time=13.2,down=False);tray.poll_hold()
            state.update(time=14,down=True);tray.poll_hold()
            state.update(time=15.2,point=(25,25));tray.poll_hold()
            state.update(time=15.3,down=False);tray.poll_hold()
        data=[]
        while not events.empty():data.append(events.get())
        self.assertEqual([e[0] for e in data].count('tray_hold'),2)
        self.assertFalse(any(e[0]=='tray_mark' for e in data))
