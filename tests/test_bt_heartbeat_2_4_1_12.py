"""Pure unit tests for inferred MQTT `last` heartbeat cycle."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "custom_components/ac_pid_frequency_temp/bt_heartbeat_logic.py"
spec = importlib.util.spec_from_file_location("bt_heartbeat_logic_test", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Tracker = module.BtLastTracker
T0 = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)

class TestBtHeartbeat(unittest.TestCase):
    def test_full_cycle(self):
        t = Tracker()
        self.assertTrue(t.ingest(0, T0))
        for i, val in enumerate((-2, -7, -12, -17, -22, -27), start=1):
            self.assertFalse(t.ingest(val, T0 + timedelta(seconds=5*i)))
        self.assertEqual(t.reset_count, 1)
        self.assertTrue(t.ingest(0, T0 + timedelta(seconds=35)))
        self.assertEqual(t.reset_count, 2)
        self.assertEqual(t.contact_age(T0+timedelta(seconds=40)), 5)

    def test_first_negative_no_false_contact(self):
        t = Tracker()
        self.assertFalse(t.ingest(-20, T0))
        self.assertEqual(t.status(T0, started_at=T0, timeout_seconds=600), 'waiting')
        self.assertFalse(t.ingest(-25, T0+timedelta(seconds=5)))
        self.assertTrue(t.ingest(-2, T0+timedelta(seconds=10)))

    def test_no_fake_contacts_from_regular_packets(self):
        t=Tracker()
        t.ingest(0,T0)
        self.assertFalse(t.ingest(0,T0+timedelta(seconds=5)))
        self.assertFalse(t.ingest(-2,T0+timedelta(seconds=10)))
        self.assertFalse(t.ingest(-5,T0+timedelta(seconds=15)))
        self.assertEqual(t.reset_count,1)

    def test_retained_ignored(self):
        t=Tracker()
        self.assertFalse(t.ingest(0,T0,retained=True))
        self.assertIsNone(t.contact_at)

    def test_timeout_with_still_arriving_countdown_packets(self):
        t=Tracker()
        t.ingest(0,T0)
        t.ingest(-5,T0+timedelta(seconds=300))
        t.ingest(-10,T0+timedelta(seconds=450))
        self.assertEqual(t.status(T0+timedelta(seconds=601), started_at=T0,
                                  timeout_seconds=600),'timeout')

    def test_no_contact_startup_timeout(self):
        t=Tracker()
        self.assertEqual(t.status(T0+timedelta(seconds=599), started_at=T0,
                                  timeout_seconds=600),'waiting')
        self.assertEqual(t.status(T0+timedelta(seconds=601), started_at=T0,
                                  timeout_seconds=600),'timeout')

    def test_contact_refreshes_timeout(self):
        t=Tracker()
        t.ingest(0,T0)
        t.ingest(-27,T0+timedelta(seconds=30))
        t.ingest(0,T0+timedelta(seconds=35))
        self.assertEqual(t.status(T0+timedelta(seconds=620), started_at=T0,
                                  timeout_seconds=600),'confirmed')

    def test_invalid_payloads(self):
        t=Tracker()
        for x in ('unavailable','NaN','inf',1,'',None,-90000):
            self.assertFalse(t.ingest(x,T0))
        self.assertEqual(t.invalid_count,7)

    def test_no_false_large_jump_away_from_zero(self):
        t=Tracker()
        t.ingest(-27,T0)
        self.assertFalse(t.ingest(-15,T0+timedelta(seconds=5)))
        self.assertIsNone(t.contact_at)

    def test_trend_after_ten_minutes_with_one_minute_control_window(self):
        import sys
        filepath = PATH.with_name('room_observer.py')
        spec = importlib.util.spec_from_file_location('room_observer_for_test', filepath)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        observer = mod.RoomObserver()
        result = None
        for i in range(13):
            moment = T0 + timedelta(minutes=i)
            result = observer.update(
                now=moment, room_temp=19.3, report_at=moment,
                sensor_status='ok', age_seconds=0,
                heating=True, defrost=False, actual_hz=45,
                target_temp=21, preferred_hz=22, max_overheat_k=1,
                restart_delta_k=0.5, window_min=1,
            )
        self.assertIsNotNone(result)
        self.assertEqual(result.trend_kph, 0.0)
        self.assertGreaterEqual(result.window_minutes, 10)

if __name__ == '__main__':
    unittest.main()
