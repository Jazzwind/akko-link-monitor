"""Deterministic anomaly state machine. No I/O, text conversion or input injection."""
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import time
import uuid
from .identity import source_label

AUTO_FIELDS = ['event_time','event_id','category','phase','started_at','detected_at',
               'ended_at','duration_seconds','since_detection_seconds','key_name',
               'interface','repeat_count','reason','evidence_json','transport']

MODIFIERS = {'Left Alt','Right Alt','Left Ctrl','Right Ctrl',
             'Left Shift','Right Shift','Left Win','Right Win'}

def key_name(scan, flags, vkey):
    """Name the key, never translate the user's composed/shifted text."""
    ext = bool(flags & 2)
    if vkey in (0x10,0xA0,0xA1): return 'Right Shift' if scan == 0x36 or vkey == 0xA1 else 'Left Shift'
    if vkey in (0x11,0xA2,0xA3): return 'Right Ctrl' if ext or vkey == 0xA3 else 'Left Ctrl'
    if vkey in (0x12,0xA4,0xA5): return 'Right Alt' if ext or vkey == 0xA5 else 'Left Alt'
    if 0x30 <= vkey <= 0x39 or 0x41 <= vkey <= 0x5A: return chr(vkey)
    if 0x70 <= vkey <= 0x87: return f'F{vkey-0x6F}'
    if 0x60 <= vkey <= 0x69: return f'Numpad {vkey-0x60}'
    names = {8:'Backspace',9:'Tab',13:'Numpad Enter' if ext else 'Enter',19:'Pause',
             20:'Caps Lock',27:'Esc',32:'Space',33:'Page Up',34:'Page Down',35:'End',
             36:'Home',37:'Left',38:'Up',39:'Right',40:'Down',44:'Print Screen',
             45:'Insert',46:'Delete',91:'Left Win',92:'Right Win',93:'Menu',
             106:'Numpad *',107:'Numpad +',109:'Numpad -',110:'Numpad .',111:'Numpad /',
             144:'Num Lock',145:'Scroll Lock',186:'Semicolon key',187:'Equals key',
             188:'Comma key',189:'Minus key',190:'Period key',191:'Slash key',
             192:'Backtick key',219:'Left bracket',220:'Backslash key',221:'Right bracket',222:'Quote key'}
    return names.get(vkey, f'VK_{vkey:02X} / Scan_{scan:02X}')

@dataclass
class Episode:
    category: str
    start: float
    detected: float
    key: str = ''
    interface: str = ''
    repeats: int = 0
    evidence: dict = field(default_factory=dict)
    reason: str = ''
    end: float | None = None
    phase: str = 'active'
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

@dataclass
class HeldKey:
    start: float
    name: str
    repeats: int = 0
    first_repeat: float | None = None
    last_repeat: float | None = None
    episode: Episode | None = None
    modifiers_at_press: list = field(default_factory=list)

class Detector:
    def __init__(self, emit, hold_seconds=2.0, min_repeats=10,
                 mono_anchor=None, wall_anchor=None, modifier_seconds=5.0):
        self.emit = emit
        self.hold_seconds = hold_seconds
        self.min_repeats = min_repeats
        self.modifier_seconds = modifier_seconds
        self.bluetooth_connected = None
        self.bluetooth_episode = None
        self.mono_anchor = time.perf_counter() if mono_anchor is None else mono_anchor
        self.wall_anchor = time.time() if wall_anchor is None else wall_anchor
        self.keys = {}
        self.history = OrderedDict()
        self.usb_present = None
        self.wireless = None
        self.usb_episode = None
        self.last_success = None
        self.input_enabled = True
        self.probes_enabled = True

    def stamp(self, mono):
        if mono is None: return ''
        return datetime.fromtimestamp(self.wall_anchor + mono-self.mono_anchor,timezone.utc).astimezone().isoformat(timespec='milliseconds')

    def snapshot(self, episode, now, phase=None):
        end = episode.end if episode.end is not None else now
        return {'event_time':self.stamp(now),'event_id':episode.event_id,
                'category':episode.category,'phase':phase or episode.phase,
                'started_at':self.stamp(episode.start),'detected_at':self.stamp(episode.detected),
                'ended_at':self.stamp(episode.end),'duration_seconds':round(max(0,end-episode.start),3),
                'since_detection_seconds':round(max(0,end-episode.detected),3),
                'key_name':episode.key,'interface':episode.interface,
                'repeat_count':episode.repeats,'reason':episode.reason,
                'evidence_json':json.dumps(episode.evidence,ensure_ascii=False,sort_keys=True),
                'transport':episode.evidence.get('transport') or (source_label(episode.interface) if episode.interface else '2.4G' if episode.category in ('usb_disconnect','suspected_wireless_disconnect') else '')}

    def _new(self, episode, now):
        self.history[episode.event_id] = episode
        # Bound completed history while preserving every active incident.
        for identity, old in list(self.history.items()):
            if len(self.history) <= 300: break
            if old.end is not None: self.history.pop(identity)
        self.emit(self.snapshot(episode,now,'detected'))
        return episode

    def _end(self, episode, now, reason, resolved=True):
        episode.end = now
        episode.reason = reason
        episode.phase = 'resolved' if resolved else 'observation_ended'
        self.emit(self.snapshot(episode,now))

    def set_usb(self, present, now):
        previous = self.usb_present
        self.usb_present = present
        if previous is True and not present:
            self.end_source_keys('2.4G',now,'usb_receiver_removed')
            if self.wireless:
                self._end(self.wireless,now,'usb_removed_wireless_state_unknown',False)
                self.wireless = None
            self.usb_episode = self._new(Episode('usb_disconnect',now,now,
                reason='receiver_absent_in_device_snapshot'),now)
        elif present and self.usb_episode:
            self._end(self.usb_episode,now,'receiver_present_again')
            self.usb_episode = None

    def probe(self, success, timeout, now, requested_at=None):
        if not self.probes_enabled: return
        if success:
            self.last_success = now
            if self.wireless:
                self.wireless.evidence['successful_query_at'] = self.stamp(now)
                self._end(self.wireless,now,'power_query_response_received')
                self.wireless = None
        elif timeout and self.usb_present is True:
            if not self.wireless:
                self.wireless = self._new(Episode('suspected_wireless_disconnect',now,now,
                    reason='power_query_timeout_while_usb_present', evidence={
                        'timeouts':1,'usb_present':True,
                        'query_started_at':self.stamp(requested_at),
                        'last_successful_query_at':self.stamp(self.last_success),
                        'onset_is_exact':False,'normal_sleep_or_delayed_response_possible':True}),now)
            else:
                self.wireless.evidence['timeouts'] += 1
                self.wireless.evidence['last_timeout_at'] = self.stamp(now)
                self.emit(self.snapshot(self.wireless,now,'evidence_update'))

    def key(self, now, path, scan, flags, vkey):
        if not self.input_enabled: return False
        identity = (path, scan, flags & 6, vkey if scan == 0 else 0)
        state = self.keys.get(identity)
        edge = False
        if flags & 1:
            if state:
                self._check_key(state,path,now)
                if state.episode:
                    state.episode.repeats = state.repeats
                    self._end(state.episode,now,'key_release_received')
                del self.keys[identity]
                edge = True
        elif state:
            state.repeats += 1
            if state.first_repeat is None: state.first_repeat = now
            state.last_repeat = now
            self._check_key(state,path,now)
        else:
            self.keys[identity] = HeldKey(now,key_name(scan,flags,vkey),
                modifiers_at_press=self.held_modifiers(path))
            edge = True
        # Repeats alone never prove wireless recovery. A real state edge is only
        # supporting evidence; wait for a successful query to close the RF episode.
        if edge and source_label(path) == '2.4G' and self.wireless and 'input_activity_at' not in self.wireless.evidence:
            self.wireless.evidence['input_activity_at'] = self.stamp(now)
            self.emit(self.snapshot(self.wireless,now,'input_response_observed'))
            return True
        return False

    def _check_key(self, state, path, now):
        modifier_overdue = state.name in MODIFIERS and now-state.start >= self.modifier_seconds
        repeats_overdue = now-state.start >= self.hold_seconds and state.repeats >= self.min_repeats
        if not state.episode and (modifier_overdue or repeats_overdue):
            state.episode = self._new(Episode('suspected_stuck_key',state.start,now,
                key=state.name,interface=path,repeats=state.repeats,
                reason='modifier_release_overdue' if modifier_overdue else 'sustained_repeats_without_release',evidence={
                    'hold_threshold_seconds':self.hold_seconds,'minimum_repeats':self.min_repeats,
                    'modifier_threshold_seconds':self.modifier_seconds,
                    'detection_basis':'modifier_release_overdue' if modifier_overdue else 'sustained_repeats_without_release',
                    'modifiers_at_press':state.modifiers_at_press,
                    'modifiers_at_detection':self.held_modifiers(path),
                    'modifiers_seen_during_incident':self.held_modifiers(path),
                    'first_repeat_at':self.stamp(state.first_repeat),
                    'duration_basis':'first_keydown_to_observed_release_or_observation_end',
                    'intentional_hold_possible':True,
                    'wireless_episode_at_detection':self.wireless.event_id if self.wireless and source_label(path) == '2.4G' else ''}),now)
        elif state.episode:
            state.episode.repeats = state.repeats
            state.episode.evidence['last_repeat_at'] = self.stamp(state.last_repeat)
            state.episode.evidence['modifiers_currently_held'] = self.held_modifiers(path)
            state.episode.evidence['modifiers_seen_during_incident'] = sorted(set(
                state.episode.evidence['modifiers_seen_during_incident']+self.held_modifiers(path)))

    def held_modifiers(self, path):
        source = source_label(path)
        return sorted({state.name for (p,*_),state in self.keys.items()
                       if source_label(p)==source and state.name in MODIFIERS})

    def end_source_keys(self, source, now, reason):
        for identity,state in list(self.keys.items()):
            if source_label(identity[0]) != source:continue
            if state.episode:self._end(state.episode,now,reason,False)
            del self.keys[identity]

    def bluetooth_status(self, connected, now):
        if connected is None:return  # Access failure is not a disconnect.
        previous=self.bluetooth_connected
        self.bluetooth_connected=connected
        if previous is True and not connected:
            self.end_source_keys('BT1',now,'bluetooth_disconnected_release_not_observed')
            self.bluetooth_episode=self._new(Episode('bluetooth_disconnect',now,now,
                reason='windows_bluetooth_connection_status_disconnected',evidence={
                    'transport':'BT1','mode_switch_or_poweroff_possible':True,
                    'onset_is_exact':False}),now)
        elif connected and self.bluetooth_episode:
            self._end(self.bluetooth_episode,now,'windows_bluetooth_connection_status_connected')
            self.bluetooth_episode=None

    def tick(self, now):
        for (path,*_),state in list(self.keys.items()): self._check_key(state,path,now)

    def end_keys(self, now, reason):
        for state in self.keys.values():
            if state.episode: self._end(state.episode,now,reason,False)
        self.keys.clear()

    def set_input_enabled(self, enabled, now):
        self.end_keys(now,'input_capture_paused' if not enabled else 'input_capture_resumed_boundary')
        self.input_enabled = enabled

    def set_probes_enabled(self, enabled, now, reason='power_queries_disabled_state_unknown'):
        self.probes_enabled = enabled
        if not enabled and self.wireless:
            self._end(self.wireless,now,reason,False)
            self.wireless = None

    def capture_gap(self, now, dropped):
        self.end_keys(now,'capture_queue_gap_release_state_unknown')
        self._new(Episode('capture_gap',now,now,reason='raw_input_queue_overflow',
                          evidence={'dropped_events_total':dropped}),now)
        ep = next(reversed(self.history.values()))
        self._end(ep,now,'capture_continuity_lost',False)

    def snapshots(self, now, active_only=False):
        return [self.snapshot(e,now) for e in self.history.values() if not active_only or e.end is None]

    def close(self, now):
        self.end_keys(now,'monitor_closed_release_not_observed')
        for attr in ('wireless','usb_episode','bluetooth_episode'):
            ep = getattr(self,attr)
            if ep:
                self._end(ep,now,'monitor_closed_recovery_not_observed',False)
                setattr(self,attr,None)
