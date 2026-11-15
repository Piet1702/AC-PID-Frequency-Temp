"""Standalone tests without Home Assistant or pytest dependencies."""
import importlib.util
from pathlib import Path
from datetime import datetime, timedelta, timezone
import unittest
import sys

SOURCE = Path(__file__).resolve().parents[1] / 'custom_components' / 'ac_pid_frequency_temp' / 'silent_policy.py'
spec = importlib.util.spec_from_file_location('silent_policy_under_test', SOURCE)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


class SilentTests(unittest.TestCase):
    def setUp(self):
        self.p = mod.SilentPolicy()

    def decision(self, mode, *, now=NOW, enabled=True, heating=True, phase='below_restart',
                 room_temp=19.0, trend=0.1, window=30, hz=24):
        return self.p.decide(now=now, mode=mode, enabled=enabled, heating=heating,
            phase=phase, room_temp=room_temp, target_temp=21, trend_kph=trend,
            window_minutes=window, observation_minutes=30, target_hz=hz,
            preferred_hz=22)

    def test_default_disabled_no_action(self):
        self.assertIsNone(self.decision(mod.DISABLED).desired)

    def test_heating_off_and_defrost_never_send(self):
        self.assertIsNone(self.decision(mod.ALWAYS, heating=False).desired)
        self.assertIsNone(self.decision(mod.NORMAL, enabled=False).desired)
        self.assertIsNone(self.decision(mod.AUTO, phase='defrost').desired)
        self.assertIsNone(self.decision(mod.ALWAYS, phase='sensor_stale').desired)

    def test_explicit_modes(self):
        self.assertEqual(self.decision(mod.ALWAYS).desired, 'on')
        self.assertEqual(self.decision(mod.NORMAL).desired, 'off')

    def test_auto_slow_boost_and_cooldown(self):
        d = self.decision(mod.AUTO, trend=0.01, hz=28)
        self.assertEqual((d.desired, d.state), ('off', 'boost'))
        self.assertEqual(self.decision(mod.AUTO, now=NOW+timedelta(minutes=20)).state, 'boost')
        d = self.decision(mod.AUTO, now=NOW+timedelta(minutes=31), trend=0.01, hz=28)
        self.assertEqual((d.desired, d.state), ('on', 'silent'))
        self.assertIn('Sperrzeit', d.reason)

    def test_auto_requires_reliable_data_and_deficit(self):
        self.assertEqual(self.decision(mod.AUTO, trend=None, hz=35).desired, 'on')
        self.assertEqual(self.decision(mod.AUTO, room_temp=20.8, trend=0.01, hz=35).desired, 'on')
        self.assertEqual(self.decision(mod.AUTO, trend=0.01, hz=25).desired, 'on')
        self.assertEqual(self.decision(mod.AUTO, trend=0.01, hz=32, window=5).desired, 'on')

    def test_manual_boost_expiration(self):
        self.p.start_manual_boost(NOW, 15)
        self.assertEqual(self.decision(mod.ALWAYS).desired, 'off')
        self.assertEqual(self.decision(mod.ALWAYS, now=NOW+timedelta(minutes=16)).desired, 'on')

    def test_cancel_stops_auto_from_restarting_immediately(self):
        self.p.start_manual_boost(NOW, 20)
        self.p.cancel_boost(NOW + timedelta(minutes=1))
        result = self.decision(mod.AUTO, now=NOW+timedelta(minutes=2), trend=0.01, hz=35)
        self.assertEqual(result.desired, 'on')
        self.assertEqual(result.state, 'silent')

    def test_no_reactivation_after_manual_off(self):
        self.p.start_manual_boost(NOW, 15)
        self.assertIsNone(self.decision(mod.AUTO, now=NOW+timedelta(minutes=2), heating=False).desired)
        self.assertIsNone(self.p.boost_until)


if __name__ == '__main__':
    unittest.main()
