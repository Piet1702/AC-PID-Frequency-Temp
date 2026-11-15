"""Standalone regression tests: run with python -3 tests/test_room_mqtt_218.py."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ac_pid_frequency_temp"

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

auto = load("acpid_218_auto_pure", "room_auto.py")
mt = load("acpid_218_mqtt_pure", "mqtt_cadence.py")
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)

def obs(temp=18.4, phase="below_restart", trend=None, window=30):
    return SimpleNamespace(room_temp=temp, phase=phase, trend_kph=trend,
                           window_minutes=window, minutes_at_min_hz=0)

def update(c, at, sample, **overrides):
    args = dict(now=at, observation=sample, running=True, preferred_hz=22,
                start_hz=45, max_hz=75, target_room_temp=21,
                max_overheat_k=2, restart_delta_k=.5,
                observation_window_min=15, actual_hz=46,
                outdoor_temp=6, min_hz_guard_minutes=0)
    args.update(overrides)
    return c.update(**args)

class Room218(unittest.TestCase):
    def test_initial_cold_uses_start_not_preferred(self):
        c=auto.RoomAutoController()
        self.assertEqual(update(c,NOW,obs()).target_hz,45)
    def test_ceiling_wins_when_preferred_is_higher(self):
        c=auto.RoomAutoController()
        d=update(c,NOW,obs(),start_hz=75,preferred_hz=45,max_hz=35)
        self.assertEqual(d.target_hz,35)
    def test_initial_near_uses_preferred(self):
        c=auto.RoomAutoController()
        self.assertEqual(update(c,NOW,obs(temp=20.6)).target_hz,22)
    def test_cold_adjust_but_not_to_max_in_one_step(self):
        c=auto.RoomAutoController()
        update(c,NOW,obs())
        d=update(c,NOW+timedelta(minutes=16),obs(trend=0.0))
        self.assertEqual(d.target_hz,49)
    def test_near_target_tapers_below_start(self):
        c=auto.RoomAutoController()
        update(c,NOW,obs())
        d=update(c,NOW+timedelta(minutes=31),obs(temp=20.8,trend=.3))
        self.assertEqual(d.target_hz,42)
    def test_overheat_and_hysteresis(self):
        c=auto.RoomAutoController()
        update(c,NOW,obs())
        d=update(c,NOW+timedelta(minutes=5),obs(temp=23.2))
        self.assertTrue(d.heat_suppressed)
        d=update(c,NOW+timedelta(minutes=40),obs(temp=21))
        self.assertTrue(d.heat_suppressed)
        d=update(c,NOW+timedelta(minutes=50),obs(temp=20.4))
        self.assertFalse(d.heat_suppressed)
        self.assertEqual(d.target_hz,22)
    def test_defrost_does_not_adjust(self):
        c=auto.RoomAutoController()
        update(c,NOW,obs())
        self.assertEqual(update(c,NOW+timedelta(minutes=50),obs(phase="defrost")).target_hz,45)
    def test_stale_blocks(self):
        c=auto.RoomAutoController()
        update(c,NOW,obs())
        self.assertEqual(update(c,NOW+timedelta(minutes=50),obs(phase="sensor_stale")).state,"fault")
    def test_max_and_floor(self):
        c=auto.RoomAutoController()
        d=update(c,NOW,obs(),start_hz=80,max_hz=65)
        self.assertEqual(d.target_hz,65)
        for i in range(15):
            d=update(c,NOW+timedelta(minutes=16*(i+1)),obs(trend=0),max_hz=65)
        self.assertLessEqual(d.target_hz,65)
        for i in range(30):
            d=update(c,NOW+timedelta(minutes=300+31*i),obs(temp=21.1,trend=.22),max_hz=65)
        self.assertGreaterEqual(d.target_hz,22)
    def test_cadence_immediate_and_repeat(self):
        c=mt.MqttCadence()
        self.assertTrue(c.should_send(NOW,enabled=True,interval=5))
        for n in range(1,5):
            self.assertFalse(c.should_send(NOW+timedelta(seconds=n),enabled=True,interval=5))
        self.assertTrue(c.should_send(NOW+timedelta(seconds=5),enabled=True,interval=5))
    def test_cadence_after_disable_enable(self):
        c=mt.MqttCadence()
        c.should_send(NOW,enabled=True,interval=5)
        self.assertFalse(c.should_send(NOW+timedelta(seconds=1),enabled=False,interval=5))
        self.assertTrue(c.should_send(NOW+timedelta(seconds=2),enabled=True,interval=5))
    def test_cadence_skipped_clock(self):
        c=mt.MqttCadence()
        c.should_send(NOW,enabled=True,interval=5)
        self.assertTrue(c.should_send(NOW+timedelta(seconds=80),enabled=True,interval=5))
        self.assertFalse(c.should_send(NOW+timedelta(seconds=81),enabled=True,interval=5))

if __name__ == "__main__": unittest.main()
