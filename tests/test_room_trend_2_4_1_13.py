"""Regression tests for 2.4.1.13 without Home Assistant dependencies."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import importlib.util
import sys
import unittest

PATH = Path(__file__).resolve().parents[1] / 'custom_components/ac_pid_frequency_temp/room_trend_logic.py'
spec = importlib.util.spec_from_file_location('room_trend_logic_test', PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
fn = mod.estimate_trend
T0 = datetime(2026, 11, 15, 13, 0, tzinfo=timezone.utc)


def series(minutes=31, start=19.3, slope=0.0):
    return [(T0+timedelta(minutes=i), start+slope*i/60)
            for i in range(minutes)]

class Tests(unittest.TestCase):
    def test_flat_30min_is_reliable_zero(self):
        v = fn(series(), now=T0+timedelta(minutes=30), window_min=30)
        self.assertEqual(v.quality, 'reliable')
        self.assertEqual(v.trend_kph, 0)
        self.assertGreaterEqual(v.span_minutes, 29)

    def test_rising_30min_is_reliable(self):
        v = fn(series(slope=0.4), now=T0+timedelta(minutes=30), window_min=30)
        self.assertEqual(v.quality, 'reliable')
        self.assertAlmostEqual(v.trend_kph, 0.4, places=3)

    def test_10min_remains_collecting(self):
        v = fn(series(11), now=T0+timedelta(minutes=10), window_min=30)
        self.assertEqual(v.quality, 'collecting')
        self.assertIsNone(v.trend_kph)

    def test_15min_is_numeric_but_not_trusted(self):
        v = fn(series(16, slope=0.6), now=T0+timedelta(minutes=15), window_min=30)
        self.assertEqual(v.quality, 'low_confidence')
        self.assertAlmostEqual(v.trend_kph, 0.6, places=3)

    def test_sparse_gap_is_not_trusted(self):
        s = [x for i,x in enumerate(series()) if i < 10 or i > 24]
        v = fn(s, now=T0+timedelta(minutes=30), window_min=30)
        self.assertEqual(v.quality, 'low_confidence')

    def test_last_contact_too_old(self):
        v = fn(series(26), now=T0+timedelta(minutes=30), window_min=30)
        self.assertIsNone(v.trend_kph)

    def test_rollover_window_still_reliable(self):
        s = series(70, slope=0.25)
        v = fn(s, now=T0+timedelta(minutes=69), window_min=30)
        self.assertEqual(v.quality, 'reliable')
        self.assertAlmostEqual(v.trend_kph, 0.25, places=3)

    def test_single_jump_dampened(self):
        s = [(T0+timedelta(minutes=i), 19.6 + (0.1 if i>=20 else 0.0))
             for i in range(31)]
        v = fn(s, now=T0+timedelta(minutes=30), window_min=30)
        self.assertEqual(v.quality, 'reliable')
        self.assertGreater(v.trend_kph, 0)
        self.assertLess(v.trend_kph, 0.3)

    def test_timestamp_deduplication(self):
        s = series() + [(T0+timedelta(minutes=30), 19.3)]
        v = fn(s, now=T0+timedelta(minutes=30), window_min=30)
        self.assertEqual(v.samples, 31)

    def test_unknown_transition_counter(self):
        h = mod.TrendUnknownHistory()
        h.observe(T0, True)
        h.observe(T0+timedelta(minutes=2), True)
        h.observe(T0+timedelta(minutes=3), False)
        h.observe(T0+timedelta(minutes=10), True)
        self.assertEqual(h.unknown_entries_30m(T0+timedelta(minutes=10)), 2)
        self.assertEqual(h.unknown_entries_30m(T0+timedelta(minutes=45)), 0)

    def test_old_points_discarded(self):
        v = fn(series(70), now=T0+timedelta(minutes=69), window_min=30)
        self.assertLessEqual(v.samples, 31)

if __name__ == '__main__':
    unittest.main()
