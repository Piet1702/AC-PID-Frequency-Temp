"""Pure regression suite for 2.4.1.11, runnable without Home Assistant."""
from __future__ import annotations
import ast
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / 'custom_components' / 'ac_pid_frequency_temp'

def load(name):
    spec = importlib.util.spec_from_file_location('pure_211_' + name, COMP / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

class WarmupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load('heating_policy')
        cls.observer = load('room_observer')
        cls.auto = load('room_auto')
        cls.t0 = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)

    def policy_output(self, **kw):
        return self.policy.apply_heating_demand_ceiling(
            output=20.7, previous_output=20.7, climate_setpoint=20.0,
            real_room_temp=19.1, room_target=21.0, actual_hz=54.7,
            maximum_hz=85, max_offset=2.0, **kw)

    def test_warmup_cap_decreases_simulated_slowly(self):
        value, active, cap = self.policy_output()
        self.assertTrue(active)
        self.assertEqual(value, 20.4)
        self.assertLess(cap, 20.0)

    def test_warmup_cap_converges(self):
        v = 20.7
        for _ in range(10):
            v, _, cap = self.policy.apply_heating_demand_ceiling(
                output=20.7, previous_output=v, climate_setpoint=20,
                real_room_temp=19.1, room_target=21, actual_hz=54.7,
                maximum_hz=85, max_offset=2)
        self.assertLessEqual(v, cap + 0.1)

    def test_no_boost_when_near_target(self):
        v, active, _ = self.policy.apply_heating_demand_ceiling(
            output=20.7, previous_output=20.7, climate_setpoint=20,
            real_room_temp=20.5, room_target=21, actual_hz=38,
            maximum_hz=85, max_offset=2)
        self.assertFalse(active)
        self.assertEqual(v, 20.7)

    def test_no_cap_above_max_hz(self):
        v, active, _ = self.policy.apply_heating_demand_ceiling(
            output=20.7, previous_output=20.7, climate_setpoint=20,
            real_room_temp=19, room_target=21, actual_hz=84,
            maximum_hz=85, max_offset=2)
        self.assertFalse(active)

    def test_no_cap_with_invalid_measurement(self):
        v, active, _ = self.policy.apply_heating_demand_ceiling(
            output=20.7, previous_output=20.7, climate_setpoint=20,
            real_room_temp=None, room_target=21, actual_hz=38,
            maximum_hz=85, max_offset=2)
        self.assertFalse(active)

    def observe(self, ob, at, value, status='ok'):
        return ob.update(now=at, report_at=at if status == 'ok' else at-timedelta(minutes=10),
            room_temp=value, sensor_status=status, age_seconds=0 if status == 'ok' else 600,
            heating=True, defrost=False, actual_hz=45, target_temp=21,
            preferred_hz=22, max_overheat_k=1, restart_delta_k=.5, window_min=1)

    def test_sparse_bt_history_survives_unchanged(self):
        ob = self.observer.RoomObserver()
        self.observe(ob, self.t0, 19.0)
        self.observe(ob, self.t0+timedelta(minutes=6), 19.0, 'unchanged')
        self.assertEqual(len(ob.samples), 1)
        r = self.observe(ob, self.t0+timedelta(minutes=11), 19.1)
        self.assertEqual(len(ob.samples), 2)
        self.assertIsNotNone(r.trend_kph)
        self.assertAlmostEqual(r.trend_kph, .545, delta=.01)

    def auto_update(self, a, at, ob, room_target=21):
        return a.update(now=at, observation=ob, running=True,
            preferred_hz=22, start_hz=45, max_hz=85,
            target_room_temp=room_target, max_overheat_k=1,
            restart_delta_k=.5, observation_window_min=1,
            actual_hz=54.7, outdoor_temp=7.5, min_hz_guard_minutes=0)

    def test_1_min_review_no_trend_no_blind_boost(self):
        a = self.auto.RoomAutoController()
        fresh = self.observer.RoomObserver()
        first = self.auto_update(a, self.t0, self.observe(fresh, self.t0, 19.1))
        self.assertEqual(first.target_hz, 45)
        second = self.auto_update(a, self.t0+timedelta(minutes=1),
                                  self.observe(fresh,self.t0+timedelta(minutes=1),19.1))
        self.assertEqual(second.target_hz, 45)
        self.assertIn(second.state, ('heating', 'starting'))

    def test_heating_floor_prevents_target_reduction(self):
        a = self.auto.RoomAutoController()
        self.auto_update(a, self.t0, self.observe(self.observer.RoomObserver(),self.t0,19.1))
        a.target_hz = 30
        r = self.auto_update(a, self.t0+timedelta(minutes=1),
            self.observe(self.observer.RoomObserver(), self.t0+timedelta(minutes=1),19.1))
        self.assertGreaterEqual(r.target_hz,45)

    def test_unchanged_never_increases_target(self):
        a = self.auto.RoomAutoController()
        self.auto_update(a, self.t0, self.observe(self.observer.RoomObserver(),self.t0,19.1))
        ob = self.observe(self.observer.RoomObserver(),self.t0+timedelta(minutes=10),19.1,'unchanged')
        r = self.auto_update(a,self.t0+timedelta(minutes=10),ob)
        self.assertEqual(r.target_hz,45)
        self.assertEqual(r.state,'sensor_unchanged')

    def test_no_climate_power_or_setpoint_calls_in_patch(self):
        patch = (COMP/'heating_policy.py').read_text()
        self.assertNotIn('async_set_hvac',patch)
        self.assertNotIn('turn_on',patch)
        src = (COMP/'controller.py').read_text()
        self.assertIn('if decision.state == "sensor_unchanged"',src)
        self.assertIn('apply_heating_demand_ceiling',src)

if __name__ == '__main__':
    unittest.main()
