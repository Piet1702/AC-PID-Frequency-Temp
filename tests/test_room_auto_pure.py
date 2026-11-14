"""Regelungs-Pilottests ohne Home-Assistant-Installation (stdlib unittest)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sys
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'custom_components' / 'ac_pid_frequency_temp' / 'room_auto.py'
spec = importlib.util.spec_from_file_location('acpid_room_auto_pure', MODULE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
BASE = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)


class AutoRoomTests(unittest.TestCase):
    def setUp(self):
        self.auto = module.RoomAutoController()

    def update(self, minutes, room=19.0, trend=0.02, phase='below_restart', running=True):
        observation = SimpleNamespace(phase=phase, room_temp=room, trend_kph=trend)
        return self.auto.update(
            now=BASE + timedelta(minutes=minutes), observation=observation,
            running=running, preferred_hz=22, max_hz=40,
            target_room_temp=21, max_overheat_k=2,
            restart_delta_k=.5, observation_window_min=30,
        )

    def test_initial_target_and_slow_adjustment(self):
        self.assertEqual(self.update(0).target_hz, 22)
        self.assertEqual(self.update(20).target_hz, 22)
        self.assertEqual(self.update(30).target_hz, 24)

    def test_upper_limit_hysteresis_without_power_commands(self):
        self.update(0)
        r = self.update(1, room=23.0, phase='above_limit')
        self.assertTrue(r.heat_suppressed)
        self.assertEqual(r.action, 'reduce_heat_demand')
        self.assertTrue(self.update(15, room=21.0, phase='tolerance').heat_suppressed)
        r = self.update(20, room=20.5)
        self.assertFalse(r.heat_suppressed)
        self.assertEqual(r.target_hz, 22)

    def test_defrost_and_stale_do_not_change_target(self):
        self.update(0)
        self.update(30)
        self.assertEqual(self.update(40, phase='defrost').target_hz, 24)
        self.assertEqual(self.update(50, phase='recovery').target_hz, 24)
        r = self.update(51, phase='sensor_stale')
        self.assertEqual(r.state, 'fault')
        self.assertEqual(r.target_hz, 24)

    def test_limit_and_reset(self):
        for minutes in range(0, 2400, 30):
            self.update(minutes)
        self.assertEqual(self.auto.target_hz, 40)
        self.assertIsNone(self.update(2401, running=False).target_hz)

    def test_near_target_interval_is_doubled(self):
        self.update(0, room=20.8, trend=0.5, phase='approaching')
        self.assertEqual(self.update(30, room=20.8, trend=0.5, phase='approaching').target_hz, 22)
        self.assertEqual(self.update(60, room=20.8, trend=0.5, phase='approaching').target_hz, 22)


if __name__ == '__main__':
    unittest.main()
