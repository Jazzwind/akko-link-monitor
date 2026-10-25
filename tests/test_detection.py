"""State/transition tests using monotonic traces, without device I/O."""
import unittest
import json
from akko_monitor.detection import Detector, key_name
from akko_monitor.identity import source_for, configure
configure("AABBCCDDEEFF")

RF='\\\\?\\hid#vid_320f&pid_506b&mi_00#test'
BT='\\\\?\\hid#{00001812-0000-1000-8000-00805f9b34fb}_dev_vid&0205ac_pid&024f_rev&0001_aabbccddeeff&col01#test'

class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.events=[]
        self.d=Detector(self.events.append,mono_anchor=0,wall_anchor=0)

    def press(self,t=0,key=65,path='akko',scan=30,flags=0):
        return self.d.key(t,path,scan,flags,key)

    def sustained(self,path='akko',key=65,scan=30,start=0):
        self.press(start,key,path,scan)
        for i in range(1,49):self.press(start+i*.05,key,path,scan)

    def test_idle_and_short_modifier_hold_do_not_alert(self):
        self.d.set_usb(True,0)
        self.d.tick(1000)
        self.press(1001,0x11,scan=29)
        self.d.tick(1005.9)
        self.assertEqual(self.events,[])

    def test_all_modifiers_without_repeats_record_duration(self):
        for scan,key,flags in [(56,0x12,0),(29,0x11,0),(42,0x10,0),(91,91,2),
                               (56,0x12,2),(29,0x11,2),(54,0x10,0),(92,92,2)]:
            events=[];d=Detector(events.append,mono_anchor=0,wall_anchor=0)
            d.key(0,RF,scan,flags,key);d.tick(5)
            self.assertEqual(len(events),1)
            self.assertEqual(events[0]['repeat_count'],0)
            self.assertEqual(events[0]['reason'],'modifier_release_overdue')
            self.assertEqual(events[0]['transport'],'2.4G')
            d.key(9,RF,scan,flags|1,key)
            self.assertEqual(events[-1]['duration_seconds'],9)
            self.assertEqual(events[-1]['phase'],'resolved')

    def test_alt_tab_context_and_transport_isolation(self):
        self.d.key(0,RF,56,0,0x12)
        self.d.key(0,BT,29,0,0x11)
        self.d.key(.1,RF,15,0,9)
        for i in range(1,50):self.d.key(.1+i*.05,RF,15,0,9)
        row=self.events[0];evidence=json.loads(row['evidence_json'])
        self.assertEqual(row['key_name'],'Tab')
        self.assertEqual(evidence['modifiers_at_press'],['Left Alt'])
        self.assertEqual(evidence['modifiers_at_detection'],['Left Alt'])
        self.assertNotIn('Left Ctrl',evidence['modifiers_at_detection'])

    def test_bluetooth_disconnect_and_usb_removal_are_independent(self):
        self.d.key(0,BT,56,0,0x12)
        self.d.set_usb(True,0);self.d.set_usb(False,1)
        self.assertEqual(len(self.d.keys),1)
        self.d.bluetooth_status(True,1);self.d.bluetooth_status(None,2)
        self.assertTrue(self.d.bluetooth_connected)
        self.d.tick(5)
        self.d.bluetooth_status(False,6)
        self.assertEqual(self.events[-2]['phase'],'observation_ended')
        self.assertEqual(self.events[-1]['category'],'bluetooth_disconnect')
        self.d.bluetooth_status(False,7)
        self.d.bluetooth_status(True,9)
        self.assertEqual(self.events[-1]['duration_seconds'],3)
        self.assertEqual(self.events[-1]['transport'],'BT1')

    def test_exact_verified_identity_rejects_other_devices(self):
        self.assertEqual(source_for(RF),'2.4G')
        self.assertEqual(source_for(BT),'BT1')
        self.assertEqual(source_for(BT.replace('aabbccddeeff','111111111111')),'')
        self.assertEqual(source_for('hid#vid_046d&pid_c52b'),'')

    def test_normal_taps_and_short_repeat_do_not_alert(self):
        for i in range(20):
            self.press(i)
            self.press(i+.1,flags=1)
        self.press(30)
        for i in range(1,20):self.press(30+i*.05)
        self.press(31,flags=1)
        self.assertEqual(self.events,[])

    def test_stuck_records_key_start_detection_and_release_duration(self):
        self.sustained()
        self.assertEqual(len(self.events),1)
        detected=self.events[0]
        self.assertEqual((detected['key_name'],detected['category'],detected['phase']),('A','suspected_stuck_key','detected'))
        self.assertEqual(detected['duration_seconds'],2.)
        self.assertNotEqual(detected['started_at'],detected['detected_at'])
        self.press(3,flags=1)
        ended=self.events[-1]
        self.assertEqual(ended['event_id'],detected['event_id'])
        self.assertEqual((ended['phase'],ended['duration_seconds'],ended['repeat_count']),('resolved',3.,48))

    def test_queued_release_still_records_historical_incident(self):
        self.sustained()
        self.press(2.5,flags=1)
        self.d.tick(100)
        self.assertEqual([e['phase'] for e in self.events],['detected','resolved'])
        self.assertEqual(self.events[-1]['duration_seconds'],2.5)

    def test_pause_ends_observation_not_release(self):
        self.sustained()
        self.d.set_input_enabled(False,3)
        self.assertEqual(self.events[-1]['phase'],'observation_ended')
        self.assertIn('paused',self.events[-1]['reason'])
        self.press(4)
        self.assertEqual(len(self.d.keys),0)

    def test_timeout_requires_known_usb_and_timeout_error(self):
        self.d.probe(False,True,1)
        self.d.set_usb(False,2)
        self.d.probe(False,True,3)
        self.d.set_usb(True,4)
        self.d.probe(False,False,5) # permissions / format error, not RF failure
        self.assertEqual(self.events,[])
        self.d.probe(False,True,6,requested_at=4.5)
        self.assertEqual(self.events[-1]['category'],'suspected_wireless_disconnect')

    def test_repeated_timeouts_are_one_incident_and_success_resolves(self):
        self.d.set_usb(True,0)
        self.d.probe(True,False,1)
        self.d.probe(False,True,32.5,31)
        identity=self.d.wireless.event_id
        self.d.probe(False,True,39,37.5)
        self.assertEqual(self.d.wireless.event_id,identity)
        self.assertEqual(self.d.wireless.evidence['timeouts'],2)
        self.d.probe(True,False,44)
        self.assertEqual(self.events[-1]['phase'],'resolved')
        self.assertEqual(self.events[-1]['duration_seconds'],11.5)
        self.assertIsNone(self.d.wireless)

    def test_autorepeats_and_input_activity_do_not_claim_radio_recovery(self):
        self.d.set_usb(True,0)
        self.press(0)
        self.d.probe(False,True,1)
        self.assertFalse(self.press(1.1))
        self.assertTrue(self.press(1.2,flags=1))
        self.assertIsNotNone(self.d.wireless)
        self.assertEqual(self.events[-1]['phase'],'input_response_observed')

    def test_usb_drop_closes_radio_and_keys_as_unconfirmed(self):
        self.d.set_usb(True,0)
        self.sustained(path=RF)
        self.d.probe(False,True,3)
        self.d.set_usb(False,4)
        ended=[e for e in self.events if e['phase']=='observation_ended']
        self.assertEqual(len(ended),2)
        self.assertEqual(self.events[-1]['category'],'usb_disconnect')
        self.d.set_usb(True,6)
        self.assertEqual(self.events[-1]['reason'],'receiver_present_again')
        self.assertEqual(self.events[-1]['duration_seconds'],2)

    def test_disabling_probes_and_exit_do_not_fabricate_recovery(self):
        self.d.set_usb(True,0)
        self.d.probe(False,True,1)
        self.d.set_probes_enabled(False,2)
        self.assertEqual(self.events[-1]['phase'],'observation_ended')
        self.d.probe(True,False,3)
        self.assertIsNone(self.d.last_success)
        self.sustained(start=4)
        self.d.close(7)
        self.assertEqual(self.events[-1]['phase'],'observation_ended')
        self.assertEqual(self.events[-1]['duration_seconds'],3)

    def test_interfaces_and_keys_are_independent(self):
        self.sustained('boot',65,30)
        self.sustained('nkro',66,48)
        self.press(3,65,'boot',30,1)
        active=self.d.snapshots(3,True)
        self.assertEqual(len(active),1)
        self.assertEqual((active[0]['key_name'],active[0]['interface']),('B','nkro'))

    def test_capture_gap_does_not_look_like_a_release(self):
        self.sustained()
        self.d.capture_gap(3,20)
        self.assertFalse(self.d.keys)
        self.assertFalse(any(e['reason']=='key_release_received' for e in self.events))
        self.assertTrue(any(e['category']=='capture_gap' for e in self.events))

    def test_key_names_distinguish_sides_and_numpad(self):
        self.assertEqual(key_name(0x36,0,0x10),'Right Shift')
        self.assertEqual(key_name(0x1d,2,0x11),'Right Ctrl')
        self.assertEqual(key_name(0x1c,2,13),'Numpad Enter')
        self.assertEqual(key_name(0x1c,0,13),'Enter')
        self.assertEqual(key_name(0x3b,0,0x70),'F1')

if __name__=='__main__':unittest.main()
