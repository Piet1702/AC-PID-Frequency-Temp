"""Pure regression tests for conservative 20Hz guard and thermal learning."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

PATH = Path(__file__).resolve().parents[1] / "custom_components" / "ac_pid_frequency_temp" / "room_auto.py"
spec = importlib.util.spec_from_file_location("acpid_room_auto_2416", PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
START = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)


def obs(*, room=21, trend=0, min_minutes=0, window=30, phase="tolerance"):
    return SimpleNamespace(room_temp=room, trend_kph=trend,
                           minutes_at_min_hz=min_minutes, window_minutes=window,
                           phase=phase)


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.reg = module.RoomAutoController()

    def run_at(self, minute=0, *, observation=None, actual=22, outdoor=5,
               guard=10, running=True):
        return self.reg.update(
            now=START + timedelta(minutes=minute),
            observation=observation or obs(), running=running,
            preferred_hz=22, max_hz=40, target_room_temp=21,
            max_overheat_k=2, restart_delta_k=0.5,
            observation_window_min=30, actual_hz=actual,
            outdoor_temp=outdoor, min_hz_guard_minutes=guard,
        )

    def test_guard_is_disabled_by_zero_and_never_power_switches(self):
        self.run_at(0, observation=obs(room=19, min_minutes=15), actual=20, guard=0)
        result = self.run_at(1, observation=obs(room=19, min_minutes=16), actual=20, guard=0)
        self.assertEqual(result.target_hz, 22)
        self.assertNotIn("power", result.action)

    def test_guard_needs_confirmed_20hz_dwell_and_cooldown(self):
        self.run_at(0, observation=obs(room=19), actual=20)
        self.assertEqual(self.run_at(1, observation=obs(room=19, min_minutes=9), actual=20).target_hz, 22)
        self.assertEqual(self.run_at(2, observation=obs(room=19, min_minutes=10), actual=20).target_hz, 23)
        self.assertEqual(self.run_at(3, observation=obs(room=19, min_minutes=11), actual=20).target_hz, 23)
        self.assertEqual(self.run_at(22, observation=obs(room=19, min_minutes=30), actual=20).target_hz, 24)
        self.assertEqual(self.run_at(42, observation=obs(room=19, min_minutes=50), actual=20).target_hz, 25)
        self.assertEqual(self.run_at(43, observation=obs(room=19, min_minutes=51), actual=20).target_hz, 25)

    def test_upper_limit_and_defrost_override_guard(self):
        self.run_at(0, observation=obs(room=21), actual=20)
        self.assertEqual(self.run_at(11, observation=obs(room=23, min_minutes=11), actual=20).state, "heat_pause")
        self.assertTrue(self.reg.heat_suppressed)
        self.assertEqual(self.run_at(12, observation=obs(room=21, min_minutes=12), actual=20).action, "reduce_heat_demand")
        self.assertEqual(self.run_at(13, observation=obs(phase="defrost", min_minutes=0), actual=0).state, "paused")

    def test_no_guard_for_missing_actual_hz(self):
        self.run_at(0, observation=obs(room=19), actual=None)
        result = self.run_at(12, observation=obs(room=19, min_minutes=20), actual=None)
        self.assertEqual(result.target_hz, 22)

    def test_learning_needs_sustained_valid_stability_and_persists(self):
        self.run_at(0)
        self.assertFalse(self.reg.continuity.learned)
        self.run_at(30)
        self.assertEqual(self.reg.continuity.learned_hz(5), 22)
        saved = self.reg.continuity.export()
        self.reg.reset()
        self.assertEqual(self.reg.continuity.learned_hz(5), 22)
        new = module.RoomAutoController()
        new.continuity.load(saved)
        self.assertEqual(new.continuity.learned_hz(5), 22)
        self.assertIsNone(new.continuity.learned_hz(-2))

    def test_stale_and_defrost_cannot_produce_learning(self):
        self.run_at(0, observation=obs(room=21, phase="defrost"), actual=0)
        self.run_at(60, observation=obs(room=21, phase="recovery"), actual=22)
        self.run_at(90, observation=obs(room=21, phase="sensor_stale"), actual=22)
        self.assertEqual(self.reg.continuity.learned, {})

    def test_bad_persisted_values_ignored(self):
        self.reg.continuity.load({"frost": {"hz": -5, "count": 5},
                                  "mild": {"hz": 24, "count": 3},
                                  "transition": {"hz": "NaN", "count": 2}})
        self.assertEqual(self.reg.continuity.learned_hz(15), 24)
        self.assertIsNone(self.reg.continuity.learned_hz(-5))


if __name__ == "__main__":
    unittest.main()
