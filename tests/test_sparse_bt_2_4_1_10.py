"""Regression tests for sparse change-only BT readings (no Home Assistant installation)."""
from __future__ import annotations
import ast
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / 'custom_components' / 'ac_pid_frequency_temp'


def load_pure(name):
    path = COMP / (name + '.py')
    spec = importlib.util.spec_from_file_location('test_' + name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class SparseBtTests(unittest.TestCase):
    def setUp(self):
        self.obs = load_pure('room_observer')
        self.auto = load_pure('room_auto')
        self.now = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)

    def observe(self, status, room=19.0, age=600, defrost=False):
        return self.obs.RoomObserver().update(
            now=self.now, report_at=self.now-timedelta(seconds=age),
            room_temp=room, sensor_status=status, age_seconds=age,
            heating=True, defrost=defrost, actual_hz=45,
            target_temp=21, preferred_hz=22,
            max_overheat_k=1, restart_delta_k=0.5, window_min=15)

    def decide(self, obs):
        return self.auto.RoomAutoController().update(
            now=self.now, observation=obs, running=True,
            preferred_hz=22, start_hz=45, max_hz=85,
            target_room_temp=21, max_overheat_k=1,
            restart_delta_k=0.5, observation_window_min=15,
            actual_hz=45, outdoor_temp=7,
            min_hz_guard_minutes=10)

    def test_old_numeric_is_not_missing(self):
        r = self.observe('unchanged')
        self.assertEqual(r.phase, 'sensor_unchanged')
        self.assertEqual(r.room_temp, 19.0)
        self.assertIsNone(r.trend_kph)

    def test_no_new_target_hz_on_unchanged(self):
        d = self.decide(self.observe('unchanged'))
        self.assertEqual(d.state, 'sensor_unchanged')
        self.assertIsNone(d.target_hz)
        self.assertEqual(d.action, 'hold')

    def test_overheat_still_takes_priority(self):
        d = self.decide(self.observe('unchanged', room=22.1))
        self.assertTrue(d.heat_suppressed)
        self.assertEqual(d.state, 'heat_pause')

    def test_invalid_fails_closed(self):
        r = self.obs.RoomObserver().update(
            now=self.now, report_at=None, room_temp=None,
            sensor_status='invalid', age_seconds=None,
            heating=True, defrost=False, actual_hz=45,
            target_temp=21, preferred_hz=22,
            max_overheat_k=1, restart_delta_k=0.5, window_min=15)
        self.assertEqual(self.decide(r).state, 'fault')

    def test_mqtt_monitor_has_event_loop_decorator(self):
        tree = ast.parse((COMP / 'automation_mqtt.py').read_text(encoding='utf-8'))
        monitor = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'AutomationMqttMonitor')
        meth = next(x for x in monitor.body if isinstance(x, ast.FunctionDef) and x.name == '_message_received')
        self.assertTrue(any(isinstance(d, ast.Name) and d.id == 'callback' for d in meth.decorator_list))

    def test_snapshot_return_path(self):
        src = (COMP / 'protoart_mqtt.py').read_text(encoding='utf-8')
        self.assertIn('return "unchanged", age, timestamp', src)
        self.assertIn('room_status not in ("ok", "unchanged")', src)

if __name__ == '__main__':
    unittest.main()
