"""Standalone regression tests: python -m unittest tests/test_room_observer_pure.py.

Loads the dependency-free observer module directly without importing Home Assistant.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import unittest
from datetime import datetime, timedelta, timezone

MODULE = Path(__file__).resolve().parents[1] / "custom_components" / "ac_pid_frequency_temp" / "room_observer.py"
spec = importlib.util.spec_from_file_location("testable_room_observer", MODULE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class RoomObserverTests(unittest.TestCase):
    def setUp(self):
        self.observer = module.RoomObserver()
        self.t0 = datetime(2026, 11, 14, 18, tzinfo=timezone.utc)

    def update(self, minute: int, temp: float = 20.0, *, status="ok", defrost=False,
               heating=True, hz=22.0, age=0.0):
        now = self.t0 + timedelta(minutes=minute)
        return self.observer.update(
            now=now, report_at=now-timedelta(seconds=age) if status == "ok" else None,
            room_temp=temp if status == "ok" else None,
            sensor_status=status, age_seconds=age, heating=heating,
            defrost=defrost, actual_hz=hz, target_temp=21.0,
            preferred_hz=22.0, max_overheat_k=2.0,
            restart_delta_k=0.5, window_min=30,
        )

    def test_trend_appears_only_after_window(self):
        self.assertIsNone(self.update(0, 20.0).trend_kph)
        for i in range(1, 16):
            result = self.update(i, 20.0 + i*0.003)
        self.assertAlmostEqual(result.trend_kph, 0.18, places=2)

    def test_stale_data_clears_history(self):
        for i in range(20):
            self.update(i, 20.0)
        result = self.update(21, status="stale")
        self.assertEqual(result.phase, "sensor_stale")
        self.assertIsNone(result.trend_kph)
        self.assertEqual(result.samples, 0)

    def test_defrost_and_recovery_excluded(self):
        self.update(0, 20.0)
        self.assertEqual(self.update(1, defrost=True).phase, "defrost")
        self.assertEqual(self.update(8).phase, "recovery")
        self.assertEqual(self.update(19).phase, "below_restart")
        self.assertIsNone(self.observer.snapshot.trend_kph)

    def test_overheat_boundary_and_advice(self):
        result = self.update(0, 23.0)
        self.assertEqual(result.phase, "above_limit")
        self.assertEqual(result.advice, "reduce_slowly")

    def test_min_hz_duration_is_observation_only(self):
        self.update(0, hz=20)
        result = self.update(7, hz=20)
        self.assertEqual(result.minutes_at_min_hz, 7.0)
        result = self.update(8, hz=22)
        self.assertEqual(result.minutes_at_min_hz, 0.0)


if __name__ == "__main__":
    unittest.main()
