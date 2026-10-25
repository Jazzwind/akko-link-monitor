"""AKKO 3098N local link monitor. Standard-library only."""
import csv
import ctypes
import json
import os
from pathlib import Path
import queue
import threading
import time
import sys
import subprocess
import uuid
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from .devices import inventory
from .raw_input import Receiver
from .metrics import Metrics
from .telemetry import Telemetry
from .detection import Detector, AUTO_FIELDS, MODIFIERS
from .identity import source_for, source_label
from .bluetooth_monitor import BluetoothMonitor

from .paths import DATA, PROJECT
from .startup import Registration, MODES
from .markers import MarkerStore
from . import identity

BASE = DATA
TARGET = '320F:506B'

class App:
    def __init__(self, root, duration=0, record=False):
        self.root = root
        root.title('AKKO Link Monitor · v0.7')
        root.geometry('1180x900'); root.minsize(1000, 760)
        self.closing = False
        self.metrics = {}
        self.receiver = Receiver()
        self.started = time.perf_counter()
        self.history = []
        self.present = None
        self.removals = self.arrivals = 0
        self.scan_queue = queue.Queue()
        self.scan_busy = False
        self.logfiles = []
        self.writers = None
        self.test = None
        self.test_result = '尚未测试'
        self.capture = True
        self.last_sample = self.started
        self.previous = {}
        self.folder = None
        self.telemetry=Telemetry()
        self.bluetooth=BluetoothMonitor(self.telemetry.events)
        self.bt_status=None;self.bt_observed=None;self.bt_error=None
        self.bt_battery=None;self.bt_battery_error=None
        self.active_source='';self.last_sources={}
        self.battery=None; self.battery_error=None; self.usb=None
        self.report_folder=None; self.report_status={}; self.report_logged_update=0
        self.extra_files=[]; self.extra_writers={}
        self.detector=Detector(self.on_auto_event)
        try:self.settings=json.loads((BASE/'settings.json').read_text(encoding='utf8'))
        except (OSError,ValueError):self.settings={}
        if not isinstance(self.settings,dict):self.settings={}
        try:
            configured=float(self.settings.get('hold_seconds',2))
            if .5<=configured<=30:self.detector.hold_seconds=configured
        except (ValueError,TypeError):pass
        try:
            value=float(self.settings.get('modifier_seconds',5))
            if 1<=value<=120:self.detector.modifier_seconds=value
        except (ValueError,TypeError):pass
        self.initial_probes_enabled=self.settings.get('power_queries_enabled',True) is not False
        # Wait for an attributed input before querying 2.4G. A receiver plugged
        # in while the keyboard uses BT1 must not produce false RF incidents.
        self.detector.probes_enabled=False
        self.telemetry.set_battery_enabled(False)
        self.last_queue_dropped=0
        self.last_anomaly_update=0
        self.last_recovery_refresh=0
        self.auto_rows_logged=0
        self.last_auto_render=0
        self.auto_tree_values={}
        self.tray=None;self.tray_events=queue.Queue()
        self.registration=Registration()
        self.markers=MarkerStore(BASE);self.mark_feedback=None;self.last_marker_text='尚未手动标记'
        self.manual_outage=None;self.hold_preview=False
        self.settings.setdefault('launch_mode','ManualWindowStartupTray')
        self.build()
        try: self.receiver.start()
        except Exception as exc:
            messagebox.showerror('输入监控启动失败', str(exc)); self.closing=True;root.destroy(); return
        self.telemetry.start()
        self.bluetooth.start()
        self.note('监控 v0.7：长按切换长断联标记；BT1 / 2.4G 电量与输入分别记录。')
        self.scan()
        root.protocol('WM_DELETE_WINDOW', self.hide_window)
        root.bind('<Unmap>',self.on_unmap)
        root.after(50, self.pump)
        root.after(1000, self.sample)
        if record: root.after(500, self.toggle_log)
        if duration: root.after(int(duration * 1000), self.close)

    def build(self):
        style = ttk.Style(); style.theme_use('clam')
        style.configure('TFrame', background='#f4f6fa')
        style.configure('TLabel', background='#f4f6fa', font=('Microsoft YaHei UI', 10))
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 21, 'bold'))
        style.configure('Metric.TLabel', font=('Microsoft YaHei UI', 14, 'bold'), foreground='#185c87')
        frame = ttk.Frame(self.root, padding=20); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='AKKO 3098N  /  BT1 + 2.4G 连接记录', style='Title.TLabel').pack(anchor='w')
        ttk.Label(frame, text='已验证 AKKO BT-1 与 320F:506B 接收器 · 仅异常保存键名及修饰键，不保存完整输入内容').pack(anchor='w', pady=(5, 12))
        self.status = tk.StringVar(value='正在查询接收器…')
        ttk.Label(frame, textvariable=self.status, style='Metric.TLabel').pack(anchor='w')
        self.bt_label=tk.StringVar(value='BT1：正在读取 Windows 蓝牙连接状态…')
        ttk.Label(frame,textvariable=self.bt_label).pack(anchor='w')
        self.summary = tk.StringVar(value='等待来自 AKKO 的输入')
        ttk.Label(frame, textvariable=self.summary).pack(anchor='w', pady=5)
        self.auto_label=tk.StringVar(value='自动判定：等待采集（普通停顿不算掉线）')
        ttk.Label(frame,textvariable=self.auto_label,foreground='#8a3900').pack(anchor='w',pady=2)
        self.battery_label=tk.StringVar(value='电量：正在读取设备上报值…（充电状态及无线侧新鲜度待验证）')
        ttk.Label(frame,textvariable=self.battery_label,foreground='#8a5900').pack(anchor='w')
        self.usb_label=tk.StringVar(value='USB：正在读取端点描述符…')
        ttk.Label(frame,textvariable=self.usb_label).pack(anchor='w',pady=3)
        actions = ttk.Frame(frame); actions.pack(fill='x', pady=12)
        self.log_button = ttk.Button(actions, text='开始保存日志', command=self.toggle_log); self.log_button.pack(side='left')
        self.pause_button = ttk.Button(actions, text='暂停输入统计', command=self.toggle_capture); self.pause_button.pack(side='left', padx=8)
        ttk.Button(actions, text='标记刚才卡顿', command=lambda: self.mark_incident('window_button')).pack(side='left')
        ttk.Button(actions, text='打开日志目录', command=self.open_logs).pack(side='left', padx=8)
        ttk.Button(actions, text='刷新设备', command=self.scan).pack(side='left')
        ttk.Button(actions,text='选择 BT1…',command=self.choose_bluetooth).pack(side='left',padx=4)
        ttk.Button(actions,text='刷新电量 / USB',command=self.telemetry.refresh).pack(side='left',padx=8)
        report_actions=ttk.Frame(frame);report_actions.pack(fill='x',pady=(0,8))
        self.report_button=ttk.Button(report_actions,text='启用 USB 报告计时（需 UAC）',command=self.start_reports)
        self.report_button.pack(side='left')
        self.report_label=tk.StringVar(value='实际报告：未启用。只采集 USB 传输头，不采集按键内容，不安装驱动。')
        ttk.Label(report_actions,textvariable=self.report_label).pack(side='left',padx=10)
        tabs=ttk.Notebook(frame);tabs.pack(fill='x',pady=(0,5))
        keytab=ttk.Frame(tabs,padding=8);timingtab=ttk.Frame(tabs,padding=8);autotab=ttk.Frame(tabs,padding=8)
        tabs.add(autotab,text='自动异常时间线');tabs.add(keytab,text='按键统计');tabs.add(timingtab,text='报告 / 事件间隔')
        auto_options=ttk.Frame(autotab);auto_options.pack(fill='x',pady=(0,5))
        ttk.Label(auto_options,text='持续重复判定阈值（秒）：').pack(side='left')
        self.hold_threshold=tk.StringVar(value=str(self.detector.hold_seconds))
        threshold=ttk.Spinbox(auto_options,from_=0.5,to=30,increment=.5,textvariable=self.hold_threshold,width=5,command=self.update_threshold)
        threshold.pack(side='left');threshold.bind('<Return>',self.update_threshold);threshold.bind('<FocusOut>',self.update_threshold)
        ttk.Label(auto_options,text='  修饰键未松开（秒）：').pack(side='left')
        self.modifier_threshold=tk.StringVar(value=str(self.detector.modifier_seconds))
        modifier=ttk.Spinbox(auto_options,from_=1,to=120,increment=1,textvariable=self.modifier_threshold,width=5,command=self.update_modifier_threshold)
        modifier.pack(side='left');modifier.bind('<Return>',self.update_modifier_threshold);modifier.bind('<FocusOut>',self.update_modifier_threshold)
        self.probes_enabled=tk.BooleanVar(value=self.initial_probes_enabled)
        ttk.Checkbutton(auto_options,text='启用 2.4G 电量查询 / 疑似失联判定',variable=self.probes_enabled,command=self.toggle_probes).pack(side='left',padx=18)
        self.auto_tree=ttk.Treeview(autotab,columns=('kind','key','start','duration','state'),show='headings',height=4)
        for name,label,width in [('kind','自动事件',250),('key','异常键名',135),('start','观察开始 / 首次按下',190),('duration','已观察时长',110),('state','状态',260)]:
            self.auto_tree.heading(name,text=label);self.auto_tree.column(name,width=width)
        self.auto_tree.pack(fill='x')
        ttk.Label(autotab,text='默认：重复 ≥10 次且按住 ≥2 秒；Alt / Ctrl / Shift / Win 未松开 ≥5 秒即记录（无需重复，主动长按也会触发）。蓝牙状态约每秒观察，正常停顿不判掉线。',wraplength=1050).pack(anchor='w',pady=4)
        self.tree = ttk.Treeview(keytab, columns=('iface','down','up','repeat','held','orphan','idle'), show='headings', height=5)
        for name, label, width in [('iface','键盘接口',230),('down','按下次数',100),('up','松开次数',100),('repeat','自动重复',100),('held','当前按住',100),('orphan','无配对松开',110),('idle','距上次输入',130)]:
            self.tree.heading(name, text=label); self.tree.column(name, width=width)
        self.tree.pack(fill='x')
        ttk.Label(keytab, text='两个接口分别统计，不能直接相加为物理按键数；自动重复、长按、无配对松开不能单独证明掉线。').pack(anchor='w', pady=5)
        ttk.Label(timingtab,text='真实 USB 输入报告：UCX 成功的 Interrupt-IN 完成时间；EP82 为键盘 / 媒体键 / 私有回复等共享端点。').pack(anchor='w')
        self.report_tree=ttk.Treeview(timingtab,columns=('ep','n','last','p50','p95','errors'),show='headings',height=2)
        for name,label in [('ep','USB 端点'),('n','成功报告数'),('last','上次间隔 ms'),('p50','P50 ms'),('p95','P95 ms'),('errors','传输错误数')]:
            self.report_tree.heading(name,text=label);self.report_tree.column(name,width=150)
        self.report_tree.pack(fill='x',pady=4)
        ttk.Label(timingtab,text='Raw Input 键盘事件：应用收到的按下 / 松开 / 重复事件，和上面的 USB 报告分别统计。').pack(anchor='w')
        self.timing_tree=ttk.Treeview(timingtab,columns=('iface','n','last','p50','p95'),show='headings',height=2)
        for name,label in [('iface','键盘接口'),('n','事件数'),('last','上次间隔 ms'),('p50','P50 ms'),('p95','P95 ms')]:
            self.timing_tree.heading(name,text=label);self.timing_tree.column(name,width=170)
        self.timing_tree.pack(fill='x',pady=4)
        ttk.Label(frame,text='间隔包含正常停顿及系统调度，不能换算成真实无线丢包率；USB 名义 1000 Hz 不代表每秒有 1000 个有效报告。').pack(anchor='w',pady=3)
        self.canvas = tk.Canvas(frame, height=75, background='#102238', highlightthickness=0)
        self.canvas.pack(fill='x', pady=(6, 8))
        testframe = ttk.Frame(frame); testframe.pack(fill='x')
        ttk.Button(testframe, text='开始 30 秒节拍测试', command=self.start_test).pack(side='left')
        self.test_label = tk.StringVar(value='每个提示音后，轻点并松开同一个键；测试从 3 秒倒计时后开始。')
        ttk.Label(testframe, textvariable=self.test_label).pack(side='left', padx=10)
        ttk.Label(frame, text='节拍测试仅比较人工操作与已收到事件；偏差包含操作误差和系统调度，不能视为射频丢包率。').pack(anchor='w', pady=6)
        self.log_label = tk.StringVar(value='日志：未保存。点击“开始保存日志”后，每秒写入 CSV；关闭程序立即停止。')
        ttk.Label(frame, textvariable=self.log_label, wraplength=1000).pack(anchor='w', pady=5)
        self.events = tk.Text(frame, height=8, background='#ffffff', foreground='#23364c', font=('Microsoft YaHei UI',10), state='disabled')
        self.events.pack(fill='both', expand=True, pady=(5, 0))

    def note(self, text, kind='info'):
        if kind=='incident':
            held=sorted({source_label(p)+':'+s.name for (p,*_),s in self.detector.keys.items() if s.name.endswith((' Alt',' Ctrl',' Shift',' Win'))})
            text+='；最近输入来源 '+(self.active_source or '未知')+'；当前未松开的修饰键 '+(', '.join(held) or '无')
        stamp = datetime.now().astimezone().isoformat(timespec='milliseconds')
        self.events.configure(state='normal')
        self.events.insert('end', stamp[11:23] + '  ' + text + '\n')
        if int(self.events.index('end-1c').split('.')[0]) > 300: self.events.delete('1.0','2.0')
        self.events.see('end'); self.events.configure(state='disabled')
        if self.writers:
            self.writers[1].writerow([stamp, kind, text])
            self.logfiles[1].flush()

    def hide_window(self):
        if self.tray:self.root.withdraw()
        else:self.close()  # Never hide an unreachable window if tray failed.

    def show_window(self):
        self.root.deiconify();self.root.lift();self.root.focus_force()

    def on_unmap(self,event):
        if event.widget is self.root and self.tray and self.root.state()=='iconic':self.root.withdraw()

    def choose_bluetooth(self):
        try:candidates=identity.discover()
        except Exception as exc:messagebox.showerror('设备识别失败',str(exc));return
        if not candidates:
            messagebox.showinfo('尚未找到 BT1','请先在 Windows 中配对 AKKO 3098 BT-1，再重新选择。');return
        dialog=tk.Toplevel(self.root);dialog.title('选择 AKKO BT1');dialog.transient(self.root)
        ttk.Label(dialog,text='仅选择你自己的 AKKO 3098 BT-1：',padding=12).pack()
        choice=tk.StringVar(value=candidates[0]['address'])
        for c in candidates:
            ttk.Radiobutton(dialog,text=c['name']+' · '+c['address'],variable=choice,value=c['address']).pack(anchor='w',padx=12)
        def select():
            self.bluetooth.stop()
            self.detector.end_source_keys('BT1',time.perf_counter(),'bluetooth_binding_changed')
            for p,m in self.metrics.items():
                if source_label(p)=='BT1':m.reset_pressed()
            identity.bind(next(c for c in candidates if c['address']==choice.get()))
            self.receiver.names.clear();self.bt_status=None;self.bt_observed=None;self.bt_error=None
            self.bt_battery=None;self.bt_battery_error=None
            self.detector.bluetooth_connected=None
            self.bluetooth=BluetoothMonitor(self.telemetry.events);self.bluetooth.start();self.telemetry.refresh()
            self.note('已更新本机 BT1 绑定；仅监控所选设备。','device_binding');dialog.destroy()
        ttk.Button(dialog,text='使用此设备',command=select).pack(pady=12)

    def attach_tray(self,tray):
        self.tray=tray;self.refresh_menu();self.refresh_tray()

    def mark_incident(self,source,when=None,monotonic=None):
        now=time.perf_counter() if monotonic is None else monotonic
        context={'trigger':source,'last_input_source':self.active_source,
          'held_modifiers':{mode:sorted({state.name for (path,*_),state in self.detector.keys.items()
                            if source_label(path)==mode and state.name in MODIFIERS}) for mode in ('BT1','2.4G')},
          'usb_present':self.present,'bluetooth_connected':self.current_bt_status(),
          'session_id':self.folder.name if self.writers and self.folder else None,
          'continuous_log_enabled':bool(self.writers),'clicked_monotonic':now}
        try:
            row=self.markers.append(context,when)
        except OSError as exc:
            self.last_marker_text='标记保存失败：'+str(exc)
            self.mark_feedback=('!',0xd97813,self.last_marker_text,float('inf'))
            self.refresh_menu();self.refresh_tray();return False
        self.last_marker_text='已记录卡顿 '+row['event_time'][11:19]
        self.mark_feedback=('✓',0x008baf,self.last_marker_text,time.perf_counter()+2)
        # Primary mark is durable even if the continuous session mirror fails.
        try:self.note('用户标记：感到输入卡顿 / 漏键；标记编号 '+row['marker_id'],'incident')
        except OSError as exc:self.last_marker_text+='（会话日志同步失败）'
        self.refresh_menu();self.refresh_tray();return True

    def refresh_menu(self):
        if not self.tray:return
        state=self.registration.read();mode=self.settings.get('launch_mode','ManualWindowStartupTray')
        self.tray.set_menu([
          (100,'显示监控窗口',False,True,[]),(101,'刷新电量',False,True,[]),
          (102,self.last_marker_text,False,False,[]),(103,'打开日志目录',False,True,[]),
          (104,'打开本地数据目录',False,True,[]),
          (106,'停止 USB 报告计时' if self.report_folder else '启用 USB 报告计时（需 UAC）',False,True,[]),
          (107,'结束长断联标记' if self.manual_outage else '开始长断联标记',bool(self.manual_outage),True,[]),
          (110,state.label,state.registered,True,[]),
          (0,'启动时隐藏窗口',False,True,[(120+i,label,key==mode,True,[]) for i,(key,label) in enumerate(MODES.items())]),
          (130,'退出',False,True,[])])

    def refresh_tray(self):
        if not self.tray:return
        source=self.active_source
        sample=self.battery_sample(source)
        value,status=sample[:2]
        text=str(value) if value!='' else '?'
        fg=0x9ba5b3 if value=='' else 0xf07369 if int(value)<30 else 0xf1cb57 if int(value)<60 else 0x7ad6a0
        label='Windows 缓存；设备测量时间未知' if source=='BT1' else '设备上报；估算精度未校准'
        known=f'；最后已知 {sample[2]}%' if value=='' and sample[2]!='' else ''
        tip=f'AKKO 3098N · {source or "来源待确认"}：{text}%{known}\n{label}；{status}'
        if sample[3]!='':tip+=f'\n距读取 {int(sample[3])} 秒'
        background=0x273142
        if self.manual_outage:
            text='断';background=0x8b3ac6;fg=0xffffff
            elapsed=max(0,time.perf_counter()-self.manual_outage['started_monotonic'])
            tip=f'正在标记长时间断联：{elapsed:.0f} 秒\n再次长按约 1 秒后松开以结束；并非真实射频时长\n'+tip
        if self.hold_preview:
            text='…';background=0x8b3ac6;fg=0xffffff
            tip=('松开以结束长断联标记' if self.manual_outage else '松开以开始长断联标记')+'\n'+tip
        if self.mark_feedback:
            symbol,bg,message,until=self.mark_feedback
            if time.perf_counter()<until:text=symbol;background=bg;fg=0xffffff;tip=message+'\n'+tip
            else:self.mark_feedback=None
        self.tray.update(text,tip,background,fg)

    def pump_tray(self):
        while True:
            try:event=self.tray_events.get_nowait()
            except queue.Empty:break
            if event[0]=='tray_mark':self.mark_incident('tray_double_click',event[1],event[2])
            elif event[0]=='tray_hold_ready':self.hold_preview=True;self.refresh_tray()
            elif event[0]=='tray_hold_cancelled':self.hold_preview=False;self.refresh_tray()
            elif event[0]=='tray_hold':
                self.hold_preview=False
                self.toggle_manual_outage({'pressed_at':datetime.fromtimestamp(event[1]).astimezone().isoformat(timespec='milliseconds'),
                    'released_at':datetime.fromtimestamp(event[3]).astimezone().isoformat(timespec='milliseconds'),
                    'pressed_monotonic':event[2],'released_monotonic':event[4],'hold_seconds':round(event[5],3)},event[3])
            elif event[0]=='tray_menu_refresh':
                self.refresh_menu()
                if len(event)>1:event[1].set()
            elif event[0]=='tray_error':self.note('托盘错误：'+event[1],'tray_error')
            elif event[0]=='tray':
                try:self.tray_command(event[1])
                except Exception as exc:
                    self.last_marker_text='操作失败：'+str(exc)
                    self.mark_feedback=('!',0xd97813,self.last_marker_text,time.perf_counter()+5)
                    try:self.note(self.last_marker_text,'tray_command_error')
                    except OSError:pass
                    self.refresh_tray()

    def tray_command(self,command):
        if command==100:self.show_window()
        elif command==101:self.telemetry.refresh()
        elif command==103:self.open_logs()
        elif command==104:self.open_folder(BASE)
        elif command==106:self.start_reports();self.refresh_menu()
        elif command==107:self.toggle_manual_outage()
        elif command==110:self.registration.set_registered(not self.registration.read().registered);self.refresh_menu()
        elif 120<=command<=122:
            self.settings['launch_mode']=list(MODES)[command-120];self.save_settings();self.refresh_menu()
        elif command==130:self.close()

    def toggle_manual_outage(self,operation=None,when=None,closing=False):
        operation=operation or {'pressed_at':datetime.now().astimezone().isoformat(timespec='milliseconds'),
                                'hold_seconds':None,'pressed_monotonic':time.perf_counter()}
        now=time.perf_counter();current=self.manual_outage
        context={'trigger':'tray_long_press' if operation['hold_seconds'] is not None else 'tray_menu',
                 'category':'manual_prolonged_disconnect','phase':'observation_ended' if closing else 'ended' if current else 'started',
                 'outage_id':current['outage_id'] if current else uuid.uuid4().hex,
                 'started_at':current['started_at'] if current else operation['pressed_at'],
                 'started_monotonic':current['started_monotonic'] if current else operation['pressed_monotonic'],
                 'ended_at':datetime.fromtimestamp(time.time() if when is None else when).astimezone().isoformat(timespec='milliseconds') if current else None,
                 'duration_seconds':round(max(0,now-current['started_monotonic']),3) if current else 0,
                 'operation':operation,'last_input_source':self.active_source,
                 'bluetooth_connected':self.current_bt_status(),'usb_present':self.present,
                 'session_id':self.folder.name if self.writers and self.folder else None,
                 'held_modifiers':{mode:sorted({state.name for (path,*_),state in self.detector.keys.items()
                           if source_label(path)==mode and state.name in MODIFIERS}) for mode in ('BT1','2.4G')},
                 'active_automatic_event_ids':[r['event_id'] for r in self.detector.snapshots(now,True)],
                 'duration_basis':'user_marked_interval_not_verified_physical_disconnect',
                 'reason':'monitor_exit_end_not_confirmed' if closing else 'user_marked_end' if current else 'user_marked_start'}
        try:row=self.markers.append(context,when)
        except OSError as exc:
            self.last_marker_text='长断联标记保存失败：'+str(exc)
            self.mark_feedback=('!',0xd97813,self.last_marker_text,float('inf'));self.refresh_tray();return False
        self.manual_outage=None if current else context
        self.last_marker_text=('长断联观察结束（未确认恢复）' if closing else f"已结束断联标记，{context['duration_seconds']:.1f} 秒" if current else '已开始长断联标记')
        self.mark_feedback=('✓',0x008baf,self.last_marker_text,now+2)
        try:self.note(self.last_marker_text+'；编号 '+context['outage_id']+'；标记 '+row['marker_id'],'manual_prolonged_disconnect')
        except OSError:pass
        self.refresh_menu();self.refresh_tray();return True

    def scan(self):
        if self.scan_busy or self.closing: return
        self.scan_busy = True
        def worker():
            try: self.scan_queue.put(([r for r in inventory() if source_for(r.get('path',''))], None))
            except Exception as exc: self.scan_queue.put((None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def pump(self):
        if self.closing: return
        for _ in range(3000):
            try: event = self.receiver.events.get_nowait()
            except queue.Empty: break
            if event[0] == 'key' and self.capture:
                _, now, path, scan, flags, vkey = event
                source=source_label(path)
                identity=(path,scan,flags&6,vkey if scan==0 else 0)
                if not flags&1 and identity not in self.detector.keys:self.select_source(source,now)
                self.last_sources[source]=now
                self.metrics.setdefault(path, Metrics()).key(now, scan, flags)
                needs_probe=self.detector.key(now,path,scan,flags,vkey)
                if needs_probe and time.perf_counter()-self.last_recovery_refresh>=3:
                    self.last_recovery_refresh=time.perf_counter();self.telemetry.refresh()
            elif event[0] == 'device':
                _, _, path, kind = event
                if kind == 'removal':
                    self.detector.end_source_keys(source_label(path),time.perf_counter(),'input_interface_removed_release_not_observed')
                    for p,m in self.metrics.items():
                        if source_label(p)==source_label(path):m.reset_pressed()
                self.note(f'AKKO 键盘接口{ "接入" if kind == "arrival" else "移除" }：{self.interface(path)}', 'interface_'+kind)
                self.scan()
            elif event[0] == 'error': self.note('采集错误：' + event[1], 'error')
        if self.receiver.dropped!=self.last_queue_dropped:
            self.detector.capture_gap(time.perf_counter(),self.receiver.dropped)
            self.last_queue_dropped=self.receiver.dropped
            for m in self.metrics.values():m.reset_pressed()
        if self.receiver.events.empty():self.detector.tick(time.perf_counter())
        while True:
            try:kind,data,error=self.telemetry.events.get_nowait()
            except queue.Empty:break
            if kind=='bluetooth':
                self.bt_observed=time.perf_counter();self.bt_error=error
                connected=data.get('connected') if not error else None
                if connected is not None:
                    old=self.bt_status;self.bt_status=connected
                    self.detector.bluetooth_status(connected,data.get('observed_monotonic',self.bt_observed))
                    if connected and not self.active_source:self.select_source('BT1',self.bt_observed)
                    if old!=connected:self.note('BT1 Windows 连接状态：'+('已连接' if connected else '已断开（也可能主动切换模式 / 关机）'),'bluetooth_status')
            elif kind=='bt_battery':
                self.bt_battery_error=error
                if not error:
                    self.bt_battery=data
                    if self.writers:
                        self.extra_writers['bt_battery'].writerow([
                            datetime.fromtimestamp(data['queried_at']).astimezone().isoformat(),
                            data['percent'],data['status'],self.current_bt_status(),data['cache_freshness'],data['source']])
                if self.active_source=='BT1':self.render_bt_battery()
            elif kind=='usb':
                if error:self.usb_label.set('USB 描述符读取失败：'+error)
                else:
                    self.usb=data
                    endpoints=[ep for d in data['devices'] for ep in d['endpoints'] if ep['direction']=='IN']
                    if endpoints:
                        self.usb_label.set('USB 声明轮询：'+'；'.join(f"MI_{ep['interface']:02X} / {ep['endpoint']} = {ep['interval_ms']:g} ms（{ep['nominal_hz']:g} Hz）" for ep in endpoints))
                    else:self.usb_label.set('USB 轮询：未取得端点参数（可能受权限限制或接收器已移除）')
                    if self.folder and self.writers:(self.folder/'usb-descriptors.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
            elif kind=='battery':
                # Ignore an in-flight result if the user has disabled active queries.
                if not self.probes_enabled.get() or self.active_source=='BT1':continue
                self.battery_error=error
                completed=data.get('probe_completed_monotonic',time.perf_counter()) if data else time.perf_counter()
                self.detector.probe(not error, bool(error and data and data.get('error_kind')=='TimeoutError'),completed,data.get('probe_started_monotonic') if data else None)
                if error:
                    self.battery_label.set('电量：本次查询失败'+(f"；上次设备上报 {self.battery['percent']}%" if self.battery else '')+'。'+error)
                    if self.writers:self.note('电量查询失败：'+error,'battery_error')
                else:
                    self.battery=data
                    self.battery_label.set(f"设备上报电量：{data['percent']}%  ·  状态原值 {data['power_state_raw']}（含义未验证） · 无线侧缓存 / 估算精度尚未验证")
                    if self.writers:
                        self.extra_writers['battery'].writerow([datetime.fromtimestamp(data['queried_at']).astimezone().isoformat(),data['percent'],data['power_state_raw'],data['payload_hex'],data['status'],data['charging'],data['wireless_freshness']])
                        self.extra_files[1].flush()
        try:
            rows, error = self.scan_queue.get_nowait()
            self.scan_busy = False
            if error: self.note('设备查询失败（不计作掉线）：'+error, 'error')
            else:
                target = [r for r in rows if r['vid_pid'] == TARGET]
                new = bool(target)
                if self.present is not None and self.present != new:
                    if new: self.arrivals += 1
                    else:
                        self.removals += 1
                        for p,m in self.metrics.items():
                            if source_label(p)=='2.4G':m.reset_pressed()
                    self.note('接收器 USB/HID '+('重新出现' if new else '消失')+'（设备快照确认）', 'receiver_change')
                self.present = new
                self.detector.set_usb(new,time.perf_counter())
                self.inventory = rows
                self.status.set('接收器：'+('USB 在线（无线链路状态未知）' if new else 'USB 未检测到')+f'     移除 {self.removals} 次 / 重新出现 {self.arrivals} 次')
        except queue.Empty: pass
        self.render()
        self.pump_tray()
        self.root.after(50, self.pump)

    @staticmethod
    def interface(path):
        part=path.split('#')[1].split('&col')[-1] if source_for(path)=='BT1' else path.split('#')[1].replace('vid_320f&pid_506b&','').upper() if '#' in path else path
        return source_label(path)+' / '+part

    def select_source(self,source,now):
        if source not in ('BT1','2.4G') or source==self.active_source:return
        self.active_source=source
        self.detector.set_probes_enabled(self.probes_enabled.get() and source!='BT1',now)
        self.telemetry.set_battery_enabled(self.probes_enabled.get() and source!='BT1')
        if source=='BT1':self.render_bt_battery()
        else:self.battery_label.set('2.4G 电量：等待本模式查询结果…')
        self.note('最近确认输入来源：'+source+'；切换不代表另一连接已恢复，未松开状态继续保留。','input_source')

    def render(self):
        now = time.perf_counter()
        bt='状态未知' if self.bt_status is None else 'Windows 已连接' if self.bt_status else 'Windows 已断开'
        if self.bt_error:bt='状态读取失败：'+self.bt_error
        elif self.bt_observed is not None and now-self.bt_observed>5:bt='状态观察已过期，连接未知'
        self.bt_label.set('BT1：'+bt+'  ·  最近确认输入来源：'+(self.active_source or '等待输入'))
        if self.active_source=='BT1':self.render_bt_battery()
        for path, m in self.metrics.items():
            values = (self.interface(path), m.downs, m.ups, m.repeats, len(m.pressed), m.orphans, f'{now-m.last_event:.1f} s' if m.last_event else '—')
            if self.tree.exists(path): self.tree.item(path, values=values)
            else: self.tree.insert('', 'end', iid=path, values=values)
            timing=m.event_summary()
            values=(self.interface(path),timing['events_total'],self.fmt(timing['last_ms']),self.fmt(timing['p50_ms']),self.fmt(timing['p95_ms']))
            if self.timing_tree.exists(path):self.timing_tree.item(path,values=values)
            else:self.timing_tree.insert('','end',iid=path,values=values)
        latest = max((m.last_event or 0 for m in self.metrics.values()), default=0)
        self.summary.set(f'运行 {int(now-self.started)} 秒  ·  '+(f'已确认收到 AKKO 输入，距上次 {now-latest:.1f} 秒' if latest else '等待 AKKO 输入验证')+f'  ·  采集队列溢出 {self.receiver.dropped} 条')
        if now-self.last_auto_render<.25:return
        self.last_auto_render=now
        active=self.detector.snapshots(now,active_only=True)
        stuck=[r for r in active if r['category']=='suspected_stuck_key']
        if self.active_source=='BT1':link='正在观察 BT1；2.4G 查询暂停'
        elif self.detector.usb_present is False:link='USB 接收器未检测到'
        elif not self.probes_enabled.get():link='电量查询已关闭，无线状态未判定'
        elif self.detector.wireless:link='疑似无线失联 / 响应超时，等待查询回复'
        elif self.detector.last_success is not None:link=f'最近查询响应正常（{now-self.detector.last_success:.0f} 秒前）'
        else:link='等待输入来源确认，再查询 2.4G 无线响应'
        input_status='；输入统计已暂停，未判定卡键' if not self.capture else '；疑似卡键：'+', '.join(r['key_name'] for r in stuck) if stuck else '；无持续重复告警'
        self.auto_label.set('自动判定：'+link+input_status)
        self.refresh_tray()
        labels={'suspected_stuck_key':'疑似卡键 / 未松开','suspected_wireless_disconnect':'疑似无线失联','bluetooth_disconnect':'蓝牙连接断开','usb_disconnect':'USB 接收器掉线','capture_gap':'采集连续性丢失'}
        states={'active':'进行中','resolved':'已观察到恢复','observation_ended':'观察结束（未确认恢复）'}
        rows=self.detector.snapshots(now)[-200:]
        identities={r['event_id'] for r in rows}
        for identity in self.auto_tree.get_children():
            if identity not in identities:
                self.auto_tree.delete(identity);self.auto_tree_values.pop(identity,None)
        for index,r in enumerate(reversed(rows)):
            state=states.get(r['phase'],r['phase'])
            if r['reason']=='key_release_received':state='已收到松开'
            elif r['reason']=='power_query_response_received':state='已恢复查询响应'
            context=json.loads(r['evidence_json']).get('modifiers_at_detection',[])
            name=r['key_name'] or '—'
            if context:name+=' ['+', '.join(context)+']'
            values=(r['transport']+' '+labels.get(r['category'],r['category']),name,r['started_at'][5:23],f"{r['duration_seconds']:.1f} s",state)
            if self.auto_tree_values.get(r['event_id'])==values:continue
            if self.auto_tree.exists(r['event_id']):self.auto_tree.item(r['event_id'],values=values)
            else:self.auto_tree.insert('',index,iid=r['event_id'],values=values)
            self.auto_tree_values[r['event_id']]=values

    def sample(self):
        if self.closing: return
        now = time.perf_counter(); elapsed = now-self.last_sample
        stamp = datetime.now().astimezone().isoformat(timespec='milliseconds')
        total = 0
        for path, m in self.metrics.items():
            prev = self.previous.get(path, 0)
            rate = (m.downs-prev)/elapsed
            total = max(total, rate)
            self.previous[path] = m.downs
            if self.writers:
                power=self.battery_sample(source_label(path))
                self.writers[0].writerow([stamp, round(elapsed,3), path, self.present, m.downs, m.ups, m.repeats, m.orphans, len(m.pressed), round(rate,2), round(now-m.last_event,3) if m.last_event else '', self.removals, self.arrivals, self.receiver.dropped, power[0],power[1], self.capture,power[2],power[3],source_label(path),self.active_source,self.current_bt_status(),power[4]])
                timing=m.event_summary()
                self.extra_writers['timing'].writerow([stamp,path,*timing.values()])
        if self.writers and not self.metrics:
            power=self.battery_sample(self.active_source)
            self.writers[0].writerow([stamp, round(elapsed,3), '', self.present, 0,0,0,0,0,0,'',self.removals,self.arrivals,self.receiver.dropped,power[0],power[1],self.capture,power[2],power[3],'',self.active_source,self.current_bt_status(),power[4]])
        if self.writers: self.logfiles[0].flush()
        if self.writers:
            for f in self.extra_files:f.flush()
        self.read_reports()
        self.save_auto_state(now)
        self.last_sample = now
        self.history.append(total); self.history = self.history[-120:]
        self.draw_chart()
        self.scan()
        self.root.after(1000, self.sample)

    def draw_chart(self):
        c = self.canvas; c.delete('all')
        w = c.winfo_width(); h = c.winfo_height()
        c.create_text(12,12,anchor='nw',text='输入活动趋势 · 近 120 秒 · 取最活跃接口的按下次数/秒', fill='#b8cde3')
        high = max(5, max(self.history, default=0))
        points=[]
        for i,v in enumerate(self.history): points.extend((12+i*(w-24)/119,h-10-v/high*(h-40)))
        if len(points)>=4: c.create_line(*points, fill='#55c6e8',width=2)

    def toggle_capture(self):
        if self.test: return
        self.capture = not self.capture
        self.detector.set_input_enabled(self.capture,time.perf_counter())
        for m in self.metrics.values(): m.reset_pressed()
        self.pause_button.configure(text='恢复输入统计' if not self.capture else '暂停输入统计')
        self.note('输入统计'+('恢复；起止边界可能产生无配对松开' if self.capture else '暂停'), 'capture')

    def toggle_log(self):
        if self.writers:
            self.save_auto_state(time.perf_counter(),force=True)
            self.note('日志保存停止', 'session_end')
            self.writers = None
            for f in self.logfiles: f.close()
            for f in self.extra_files:f.close()
            self.extra_files=[];self.extra_writers={}
            self.logfiles=[]
            self.log_button.configure(text='开始保存日志')
            self.log_label.set('日志已保存：'+str(self.folder))
            return
        try:
            self.folder = BASE/'logs'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            self.folder.mkdir(parents=True)
            (self.folder/'devices.json').write_text(json.dumps(getattr(self,'inventory',[]),ensure_ascii=False,indent=2),encoding='utf-8')
            for name in ('samples.csv','events.csv'):
                self.logfiles.append((self.folder/name).open('w',newline='',encoding='utf-8-sig'))
            self.writers = [csv.writer(f) for f in self.logfiles]
            for key,name,header in [('timing','input-timing.csv',['timestamp','interface','events_total','last_ms','min_ms','p50_ms','p95_ms','max_ms']),('battery','battery.csv',['timestamp','percent','state_raw','payload_hex','status','charging','wireless_freshness']),('reports','usb-reports.csv',['timestamp','endpoint','reports_total','transfer_errors','last_size','interval_samples','last_interval_ms','min_ms','p50_ms','p95_ms','max_ms','etw_events_lost']),('bt_battery','bluetooth-battery.csv',['timestamp','percent','status','bluetooth_connected','freshness','source']),('automatic','automatic-events.csv',AUTO_FIELDS)]:
                f=(self.folder/name).open('w',newline='',encoding='utf-8-sig');self.extra_files.append(f)
                writer=csv.writer(f);writer.writerow(header);self.extra_writers[key]=writer
            if self.usb:(self.folder/'usb-descriptors.json').write_text(json.dumps(self.usb,ensure_ascii=False,indent=2),encoding='utf8')
            self.writers[0].writerow(['timestamp','sample_seconds','interface','usb_present','downs_total','ups_total','autorepeats_total','unpaired_releases_total','held','downs_per_second','last_input_age_seconds','usb_removals_total','usb_arrivals_total','capture_queue_dropped_total','battery_percent','battery_status','input_capture_enabled','battery_last_known_percent','battery_query_age_seconds','transport','last_observed_input_source','bluetooth_connected','battery_transport'])
            self.writers[1].writerow(['timestamp','kind','description'])
            self.note('日志保存开始；计数为本次程序运行累计值', 'session_start')
            self.note('电量按来源分别记录；BT1 为 Windows 缓存，缓存读取时间不等于键盘测量时间。','battery_sources')
            for row in self.detector.snapshots(time.perf_counter()):
                self.write_auto_row(dict(row,phase='log_start_snapshot'))
            self.save_auto_state(time.perf_counter(),force=True)
            self.telemetry.refresh()
            self.log_button.configure(text='停止保存日志')
            self.log_label.set('正在保存：'+str(self.folder))
        except OSError as exc:
            self.writers=None
            for f in self.logfiles: f.close()
            for f in self.extra_files:f.close()
            self.extra_files=[];self.extra_writers={}
            self.logfiles=[]
            messagebox.showerror('日志保存失败',str(exc))

    def start_test(self):
        if self.test or not self.capture: return
        self.test={'start':time.perf_counter()+3,'beat':-1,'baseline':{},'times':{}}
        self.note('节拍测试准备：3 秒后开始，共 30 个提示音；每声轻点并松开同一个键。','test_start')
        self.tick_test()

    def tick_test(self):
        if self.closing or not self.test: return
        t=self.test; elapsed=time.perf_counter()-t['start']
        if elapsed<0: self.test_label.set(f'准备… {int(-elapsed)+1}')
        elif elapsed>=30:
            results=[]
            for path,m in self.metrics.items():
                count=m.test_downs-t['baseline'].get(path,0)
                if count: results.append(self.interface(path)+f' 收到 {count}/30 次，差值 {count-30:+d}')
            result='；'.join(results) or '未收到 AKKO 按下事件'
            self.test_label.set(result)
            self.note('节拍测试结束：'+result+'；差值不是丢包率。','test_result')
            self.test=None; return
        else:
            beat=int(elapsed)
            if beat!=t['beat']:
                if t['beat']==-1:
                    t['baseline']={p:m.test_downs for p,m in self.metrics.items()}
                t['beat']=beat
                self.root.bell()
                self.test_label.set(f'● 第 {beat+1}/30 拍：轻点并松开一个键')
        self.root.after(30,self.tick_test)

    def open_logs(self):
        self.open_folder(BASE/'logs')

    def open_folder(self,folder):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        explorer=Path(os.environ.get('WINDIR','C:/Windows'))/'explorer.exe'
        subprocess.Popen([str(explorer),str(folder.resolve())])

    @staticmethod
    def fmt(value):return f'{value:.3f}' if value is not None else '—'

    def battery_status(self):
        if self.active_source=='BT1':return 'not_queried_in_bluetooth_mode'
        if not self.probes_enabled.get():return 'queries_disabled'
        if self.battery_error:return 'last_query_failed'
        return self.battery['status'] if self.battery else 'unavailable'

    def battery_age(self):
        return [self.battery['percent'],round(time.time()-self.battery['queried_at'],2)] if self.battery else ['','']

    def battery_sample(self,source):
        if source=='BT1':
            data=self.bt_battery
            status='last_cache_read_failed' if self.bt_battery_error else 'windows_cached' if data else 'bluetooth_battery_unavailable'
            valid=data and not self.bt_battery_error and self.current_bt_status() is True
            if data and not self.bt_battery_error and self.current_bt_status() is not True:status='windows_cached_connection_unknown_or_disconnected'
        elif source=='2.4G':
            data=self.battery;status=self.battery_status()
            valid=data and not self.battery_error and self.active_source=='2.4G' and self.probes_enabled.get()
            if self.active_source!='2.4G':status='not_queried_in_current_mode'
        else:return ['','unavailable','','','']
        return [data['percent'] if valid else '',status,data['percent'] if data else '',
                round(time.time()-data['queried_at'],2) if data else '',source]

    def render_bt_battery(self):
        if self.bt_battery:
            percent=self.bt_battery['percent'];age=max(0,time.time()-self.bt_battery['queried_at'])
            self.battery_label.set(f'BT1 电量：Windows 缓存 {percent}% · {age:.0f} 秒前读取缓存，设备测量时间未知'+
                (' · 本次缓存读取失败' if self.bt_battery_error else '')+
                (' · 蓝牙当前未确认连接' if self.current_bt_status() is not True else ''))
        else:self.battery_label.set('BT1 电量：等待 Windows 电量缓存'+('；'+self.bt_battery_error if self.bt_battery_error else '…'))

    def update_threshold(self,event=None):
        try:
            value=float(self.hold_threshold.get())
            if not .5<=value<=30:raise ValueError
        except ValueError:
            self.hold_threshold.set(str(self.detector.hold_seconds));return
        if value!=self.detector.hold_seconds:
            self.detector.hold_seconds=value
            self.save_settings()
            self.note(f'疑似卡键阈值改为 {value:g} 秒且至少 10 次重复。','detection_config')

    def toggle_probes(self):
        enabled=self.probes_enabled.get() and self.active_source!='BT1'
        self.detector.set_probes_enabled(enabled,time.perf_counter())
        self.telemetry.set_battery_enabled(enabled)
        self.save_settings()
        if self.active_source=='BT1':self.render_bt_battery()
        elif not enabled:self.battery_label.set('2.4G 电量主动查询已关闭；保留被动输入 / USB 计时。')
        self.note('电量主动查询'+('启用' if enabled else '关闭；未结束的疑似失联记录为观察结束，不算恢复'),'detection_config')

    def save_settings(self):
        self.settings.update(hold_seconds=self.detector.hold_seconds,modifier_seconds=self.detector.modifier_seconds,power_queries_enabled=self.probes_enabled.get())
        try:
            tmp=BASE/'settings.tmp';tmp.write_text(json.dumps(self.settings,ensure_ascii=False,indent=2),encoding='utf8')
            os.replace(tmp,BASE/'settings.json')
        except OSError as exc:self.note('设置保存失败：'+str(exc),'settings_error')

    def current_bt_status(self):
        return self.bt_status if self.bt_observed is not None and time.perf_counter()-self.bt_observed<=5 and not self.bt_error else None

    def update_modifier_threshold(self,event=None):
        try:
            value=float(self.modifier_threshold.get())
            if not 1<=value<=120:raise ValueError
        except ValueError:
            self.modifier_threshold.set(str(self.detector.modifier_seconds));return
        self.detector.modifier_seconds=value;self.save_settings()
        self.note(f'修饰键未松开判定阈值 {value:g} 秒；不要求重复，主动长按也可能触发。','detection_config')

    def write_auto_row(self,row):
        writer=self.extra_writers.get('automatic')
        if writer and self.writers:
            writer.writerow([row.get(k,'') for k in AUTO_FIELDS])
            self.extra_files[-1].flush()
            self.auto_rows_logged+=1

    def on_auto_event(self,row):
        self.write_auto_row(row)
        if row['phase']=='evidence_update':return
        name=row['key_name']
        if row['category']=='suspected_stuck_key':
            if row['phase']=='detected':text=f"疑似卡键：{name}，已按住 {row['duration_seconds']:.2f} 秒，重复 {row['repeat_count']} 次（也可能是主动长按）。"
            elif row['phase']=='resolved':text=f"卡键观察结束：{name} 已收到松开，按住状态持续 {row['duration_seconds']:.2f} 秒，重复 {row['repeat_count']} 次。"
            else:text=f"卡键观察中断：{name}，已观察 {row['duration_seconds']:.2f} 秒；未确认松开，原因 {row['reason']}。"
        elif row['category']=='suspected_wireless_disconnect':
            if row['phase']=='detected':text='疑似无线失联：USB 在线，但电量查询响应超时；不排除休眠或迟到回复。'
            elif row['phase']=='resolved':text=f"恢复查询响应：距首次超时观察 {row['duration_seconds']:.2f} 秒；不代表精确射频掉线时长。"
            elif row['phase']=='input_response_observed':text='疑似失联期间已观察到按键状态变化，等待电量查询确认响应。'
            else:text='疑似失联观察中断，未确认恢复：'+row['reason']
            context=json.loads(row['evidence_json']).get('modifiers_at_detection',[])
            text+=' 当时按住的修饰键：'+(', '.join(context) or '无')+'。'
        elif row['category']=='bluetooth_disconnect':text='BT1 '+('Windows 已重新连接。' if row['phase']=='resolved' else 'Windows 观察到断开（主动切换 / 关机也可能导致）。' if row['phase']=='detected' else '断开观察结束，未确认恢复。')
        elif row['category']=='usb_disconnect':text='USB 接收器'+('重新出现。' if row['phase']=='resolved' else '未检测到。' if row['phase']=='detected' else '掉线观察结束，未确认恢复。')
        else:text='采集连续性异常：'+row['reason']
        self.note('['+row['transport']+'] '+text,'auto_'+row['category']+'_'+row['phase'])

    def save_auto_state(self,now,force=False):
        if not self.writers or not self.folder:return
        rows=self.detector.snapshots(now)
        if force or now-self.last_anomaly_update>=5:
            for row in rows:
                if row['phase']=='active':self.write_auto_row(dict(row,phase='ongoing'))
            self.last_anomaly_update=now
        state={'recorded_at':datetime.now().astimezone().isoformat(),'monitor_closing':self.closing,
               'settings':{'hold_seconds':self.detector.hold_seconds,'min_repeats':self.detector.min_repeats,
                           'modifier_seconds':self.detector.modifier_seconds,
                           'power_queries_enabled':self.probes_enabled.get(),'input_capture_enabled':self.capture},
               'last_observed_input_source':self.active_source,'bluetooth_connected':self.current_bt_status(),
               'bluetooth_battery':self.bt_battery,'bluetooth_battery_error':self.bt_battery_error,
               'manual_prolonged_disconnect':dict(self.manual_outage,duration_seconds=round(max(0,now-self.manual_outage['started_monotonic']),3)) if self.manual_outage else None,
               'events':rows}
        try:
            tmp=self.folder/'automatic-state.tmp'
            tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
            os.replace(tmp,self.folder/'automatic-state.json')
        except OSError as exc:
            self.log_label.set('自动事件快照写入失败：'+str(exc))

    def start_reports(self):
        if self.report_folder:
            (self.report_folder/'stop').touch()
            self.report_label.set('USB 报告计时：正在停止…')
            self.report_button.configure(state='disabled')
            return
        self.report_folder=BASE/'runtime'/uuid.uuid4().hex
        self.report_folder.mkdir(parents=True)
        (self.report_folder/'heartbeat').touch()
        shell=ctypes.WinDLL('shell32',use_last_error=True)
        shell.ShellExecuteW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_int]
        shell.ShellExecuteW.restype=ctypes.c_void_p
        pythonw=Path(sys.executable).with_name('pythonw.exe')
        params=f'"{PROJECT / "app.py"}" --etw-helper --folder "{self.report_folder}"'
        result=shell.ShellExecuteW(None,'runas',str(pythonw),params,str(PROJECT),0)
        if not result or result<=32:
            self.note('USB 报告计时未启用：UAC 被取消或启动失败。','reports_error')
            self.report_folder=None;return
        self.report_label.set('等待 Windows UAC 授权和 USB 拓扑映射…')
        self.report_button.configure(text='停止 USB 报告计时')
        self.note('已请求管理员 USB 头部追踪；不捕获按键内容，不安装驱动。','reports_start')

    def read_reports(self):
        if not self.report_folder:return
        (self.report_folder/'heartbeat').touch()
        path=self.report_folder/'reports-status.json'
        if not path.exists():return
        try:data=json.loads(path.read_text(encoding='utf8'))
        except (OSError,ValueError):return
        self.report_status=data
        state=data['status']
        if state=='error':
            self.report_label.set('USB 报告计时失败：'+data.get('error','未知错误'))
        elif state=='stopped':self.report_label.set('USB 报告计时：已停止')
        else:
            self.report_label.set(('USB 拓扑已匹配 AKKO' if data.get('mapped') else '正在映射 AKKO USB 拓扑')+f"；ETW 丢事件 {data.get('etw_events_lost')} / 解析错误 {data.get('callback_errors')}")
            for ep,stat in data.get('endpoints',{}).items():
                values=(ep,stat['reports_total'],self.fmt(stat['last_interval_ms']),self.fmt(stat['p50_ms']),self.fmt(stat['p95_ms']),stat['transfer_errors'])
                if self.report_tree.exists(ep):self.report_tree.item(ep,values=values)
                else:self.report_tree.insert('','end',iid=ep,values=values)
                if self.writers and data['updated']!=self.report_logged_update:
                    self.extra_writers['reports'].writerow([datetime.fromtimestamp(data['updated']).astimezone().isoformat(),ep,*stat.values(),data.get('etw_events_lost')])
            self.report_logged_update=data['updated']
        if state in ('error','stopped'):
            self.report_folder=None
            self.report_button.configure(text='启用 USB 报告计时（需 UAC）',state='normal')

    def close(self):
        if self.closing: return
        self.closing=True
        if self.manual_outage:self.toggle_manual_outage(closing=True)
        try:self.detector.close(time.perf_counter())
        except OSError:pass
        try:
            if self.report_folder:(self.report_folder/'stop').touch()
        except OSError:pass
        try:
            if self.writers:self.toggle_log()
        except OSError:pass
        finally:
            for file in self.logfiles+self.extra_files:
                try:file.close()
                except OSError:pass
            for stop in ([self.tray.stop] if self.tray else [])+[self.telemetry.stop,self.bluetooth.stop,self.receiver.stop]:
                try:stop()
                except (OSError,RuntimeError):pass
            self.root.destroy()

