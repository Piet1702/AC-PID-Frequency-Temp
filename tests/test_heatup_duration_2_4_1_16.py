#!/usr/bin/env python3
"""Pure-Python regression tests for the configurable heat-up duration."""
import importlib.util
import math
from pathlib import Path
import sys
import unittest

COMPONENT = Path(__file__).resolve().parents[1] / 'custom_components' / 'ac_pid_frequency_temp' / 'room_demand_coupling.py'
# Allow direct test from the ZIP's root before applying the installer.
if not COMPONENT.is_file():
    COMPONENT = Path(__file__).resolve().parents[1] / 'room_demand_coupling_2_4_1_16.py'
spec = importlib.util.spec_from_file_location('room_heatup_216', COMPONENT)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def plan(**kwargs):
    return m.plan_room_demand(
        old_hz=kwargs.pop('old_hz', 45),
        actual_hz=kwargs.pop('actual_hz', 45),
        room_temp=kwargs.pop('room_temp', 19.6),
        room_target=kwargs.pop('room_target', 21.0),
        trend_kph=kwargs.pop('trend_kph', .585),
        preferred_hz=kwargs.pop('preferred_hz', 22),
        max_hz=kwargs.pop('max_hz', 70),
        heatup_minutes=kwargs.pop('heatup_minutes', 150),
        elapsed_heatup_min=kwargs.pop('elapsed_heatup_min', 0),
        **kwargs,
    )


class HeatupDurationTests(unittest.TestCase):
    def test_default_150_min_rate(self):
        p = plan(old_hz=70, actual_hz=66.7)
        self.assertAlmostEqual(p.target_rate_kph, .56)
        self.assertLess(p.target_hz, 70)
        self.assertFalse(p.heat_raise)

    def test_slow_warming_requests_more(self):
        p = plan(old_hz=45, actual_hz=45, trend_kph=.2)
        self.assertGreater(p.target_hz, 45)
        self.assertTrue(p.heat_raise)

    def test_time_budget_decreases_not_sliding(self):
        start = plan(old_hz=45, actual_hz=45, trend_kph=.45, elapsed_heatup_min=0)
        later = plan(old_hz=45, actual_hz=45, trend_kph=.45, elapsed_heatup_min=60)
        self.assertGreater(later.target_rate_kph, start.target_rate_kph)
        self.assertEqual(later.heatup_remaining_min, 90)

    def test_rate_already_enough_avoids_raising(self):
        p = plan(old_hz=50, actual_hz=50, trend_kph=.65)
        self.assertLessEqual(p.target_hz, 50)
        self.assertFalse(p.heat_raise)

    def test_target_max_respected(self):
        p = plan(old_hz=50, actual_hz=50, max_hz=50, trend_kph=.1)
        self.assertLessEqual(p.target_hz, 50)

    def test_wait_for_actuator_response(self):
        p = plan(old_hz=45, actual_hz=55, trend_kph=.585, preferred_hz=22)
        self.assertLessEqual(p.target_hz, 45)
        self.assertFalse(p.heat_raise)

    def test_5min_raise_guard(self):
        p = plan(old_hz=35, actual_hz=35, trend_kph=-.2, may_raise=False)
        self.assertEqual(p.target_hz, 35)

    def test_no_actual_no_blind_raise(self):
        p = plan(old_hz=35, actual_hz=None, trend_kph=.1)
        self.assertEqual(p.target_hz, 35)

    def test_near_target_reduce(self):
        p = plan(old_hz=55, actual_hz=54, room_temp=20.9, trend_kph=.4)
        self.assertLess(p.target_hz, 55)

    def test_over_target_priority(self):
        p = plan(old_hz=55, actual_hz=55, room_temp=21.2, trend_kph=.9)
        self.assertLess(p.target_hz, 55)
        self.assertFalse(p.heat_raise)

    def test_remaining_time_soft_floor(self):
        p = plan(old_hz=45, actual_hz=45, elapsed_heatup_min=200)
        self.assertEqual(p.heatup_remaining_min, 45)

    def test_legacy_214_call_is_accepted(self):
        p = m.plan_room_demand(old_hz=45, actual_hz=45,
            room_temp=19.6, room_target=21, trend_kph=.585,
            preferred_hz=22, max_hz=70)
        self.assertIsNone(p.target_rate_kph)
        self.assertEqual(p.forecast_room_c, 20.039)

    def test_invalid_duration(self):
        with self.assertRaises(ValueError):
            plan(heatup_minutes=float('nan'))

    def test_finite_bounded_hz(self):
        for rate in [-2, -1, 0, .2, .5, 1, 3]:
            p = plan(trend_kph=rate)
            self.assertTrue(math.isfinite(p.target_hz))
            self.assertTrue(22 <= p.target_hz <= 70)


if __name__ == '__main__':
    unittest.main(verbosity=2)
