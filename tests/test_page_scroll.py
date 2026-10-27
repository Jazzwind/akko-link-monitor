"""Synthetic UI scrolling, without hardware access or OS input injection."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

from akko_monitor import app
from akko_monitor.scroll_page import FlowFrame
from test_app_detection import FakeReceiver,FakeTelemetry,FakeBluetooth


class PageScrollTests(unittest.TestCase):
    def test_small_window_reaches_bottom_and_routes_nested_wheel(self):
        for scale in (1.0,1.5,2.0):
            with self.subTest(scale=scale),tempfile.TemporaryDirectory() as temp:
                with patch.object(app,'BASE',Path(temp)),patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[]):
                    root=tk.Tk();root.withdraw();root.tk.call('tk','scaling',scale)
                    monitor=app.App(root)
                    try:
                        for callback in root.tk.call('after','info'):
                            if str(root.tk.call('after','info',callback)[0]).endswith(('pump','sample')):root.after_cancel(callback)
                        root.attributes('-alpha',0);root.geometry('800x480');root.deiconify()
                        root.update();page=monitor.page;page.resize();root.update()
                        self.assertGreater(page.content.winfo_height(),page.viewport.winfo_height())
                        self.assertLess(page.viewport.yview()[1],1)
                        event=SimpleNamespace(widget=monitor.auto_tree,delta=-120,state=0,num=0)
                        self.assertEqual(page.wheel(event),'break')  # Empty table bubbles.
                        self.assertGreater(page.viewport.yview()[0],0)
                        page.viewport.yview_moveto(0)
                        for i in range(80):monitor.auto_tree.insert('','end',values=(str(i),'K','','',''))
                        root.update_idletasks()
                        offset=0;widget=monitor.auto_tree
                        while widget is not page.content:
                            offset+=widget.winfo_y();widget=widget.master
                        page.viewport.yview_moveto(offset/page.content.winfo_height())
                        root.update();monitor.auto_tree.yview_moveto(0);root.update()
                        before=page.viewport.yview()
                        self.assertIsNone(page.wheel(event),(monitor.auto_tree.yview(),monitor.auto_tree.winfo_ismapped(),monitor.auto_tree.winfo_height(),len(monitor.auto_tree.get_children())))
                        self.assertEqual(page.viewport.yview(),before)
                        monitor.auto_tree.event_generate('<MouseWheel>',delta=-120)
                        root.update_idletasks()
                        self.assertGreater(monitor.auto_tree.yview()[0],0)
                        self.assertEqual(page.viewport.yview(),before)
                        monitor.auto_tree.yview_moveto(1)
                        self.assertEqual(page.wheel(event),'break')  # Table bottom bubbles.
                        self.assertGreater(page.viewport.yview()[0],0)
                        page.viewport.yview_moveto(1);root.update_idletasks()
                        self.assertAlmostEqual(page.viewport.yview()[1],1,places=2)
                        self.assertLessEqual(monitor.events.winfo_y()+monitor.events.winfo_height(),page.content.winfo_height())
                        monitor.events.configure(state='normal')
                        monitor.events.insert('end','synthetic log line\n'*100)
                        monitor.events.configure(state='disabled');monitor.events.yview_moveto(0)
                        root.update()
                        before=page.viewport.yview()
                        text_event=SimpleNamespace(widget=monitor.events,delta=-120,state=0,num=0)
                        self.assertIsNone(page.wheel(text_event))
                        monitor.events.event_generate('<MouseWheel>',delta=-120);root.update()
                        self.assertGreater(monitor.events.yview()[0],0)
                        self.assertEqual(page.viewport.yview(),before)
                        self.assertEqual(page.viewport.xview(),(0,1))
                        self.assertLess(monitor.auto_tree.xview()[1],1)
                        self.assertIn(page.wheel_tag,monitor.log_button.bindtags())
                        # Wheel is bound locally, never via bind_all/global hooks.
                        self.assertNotIn(page.wheel_tag,root.bindtags())
                    finally:monitor.close()

    def test_resize_reflows_all_actions_and_keeps_page_within_viewport(self):
        for scale in (1.0,1.5,2.0):
            with self.subTest(scale=scale),tempfile.TemporaryDirectory() as temp:
                with patch.object(app,'BASE',Path(temp)),patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[]):
                    root=tk.Tk();root.withdraw();root.tk.call('tk','scaling',scale)
                    monitor=app.App(root)
                    try:
                        for callback in root.tk.call('after','info'):
                            if str(root.tk.call('after','info',callback)[0]).endswith(('pump','sample')):root.after_cancel(callback)
                        root.attributes('-alpha',0);root.deiconify()
                        def descendants(widget):
                            for child in widget.winfo_children():
                                yield child;yield from descendants(child)
                        flows=[w for w in descendants(monitor.page.content) if isinstance(w,FlowFrame)]
                        narrow_rows=None
                        for width in (720,1100,1600,720):
                            root.geometry(f'{width}x520');root.update()
                            self.assertEqual(monitor.page.content.winfo_width(),monitor.page.viewport.winfo_width())
                            self.assertEqual(monitor.page.viewport.xview(),(0,1))
                            for flow in flows:
                                for control in flow.items:
                                    self.assertGreaterEqual(control.winfo_x(),0)
                                    self.assertLessEqual(control.winfo_x()+control.winfo_width(),flow.winfo_width(),str(control))
                            rows=sum(len({item.winfo_y() for item in flow.items}) for flow in flows)
                            if width==720:narrow_rows=rows
                            if width==1600:
                                self.assertLessEqual(rows,narrow_rows)
                                if scale>1:self.assertLess(rows,narrow_rows)
                        for notebook in [w for w in descendants(monitor.page.content) if w.winfo_class()=='TNotebook']:
                            for tab in notebook.tabs():notebook.select(tab);root.update()
                        wrapped=[w for w in descendants(monitor.page.content) if w.winfo_class()=='TLabel' and w.cget('wraplength')]
                        self.assertTrue(wrapped)
                        for label in wrapped:
                            self.assertLessEqual(int(label.cget('wraplength')),label.winfo_width())
                    finally:monitor.close()
