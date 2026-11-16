"""Tests RoomAutoController 2.4.1.17 using its real pure-Python module.

Run: py -3 tests/test_room_brake_integration_2_4_1_17.py
No Home Assistant installation, device access or MQTT calls are required.
"""
from __future__ import annotations
import importlib
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / 'custom_components' / 'ac_pid_frequency_temp'
assert COMP.is_dir(), 'No custom_components/ac_pid_frequency_temp directory'
# Load only pure-Python modules, skipping HA-dependent package __init__.py.
PACKAGE = '_ac_pid_217_pure'
pkg = ModuleType(PACKAGE)
pkg.__path__ = [str(COMP)]
sys.modules[PACKAGE] = pkg
RoomAutoController = importlib.import_module(PACKAGE + '.room_auto').RoomAutoController


def obs(room=20.8, trend=0.2, short=0.7, long=0.10,
        sq='reliable', lq='reliable', phase='approaching'):
    return SimpleNamespace(
        room_temp=room, trend_kph=trend, trend_quality='reliable',
        short_trend_kph=short, long_trend_kph=long,
        short_trend_quality=sq, long_trend_quality=lq,
        phase=phase, window_minutes=30.0, minutes_at_min_hz=0.0,
    )


def tick(ctrl, when, reading, actual=39):
    return ctrl.update(
        now=when, observation=reading, running=True,
        preferred_hz=22.0, start_hz=45.0, max_hz=50.0,
        target_room_temp=21.0, max_overheat_k=1.0, restart_delta_k=0.5,
        observation_window_min=5.0, heatup_duration_min=150.0,
        actual_hz=actual, outdoor_temp=10.0, min_hz_guard_minutes=0.0,
    )


def test_run():
    now = datetime(2026, 11, 16, 13, 0, tzinfo=timezone.utc)
    checks = 0
    # Fast brake bypasses 5-min interval near target, uses actual+deadband guard.
    c = RoomAutoController(); c.target_hz = 40.0; c.last_adjust = now
    d = tick(c, now + timedelta(seconds=30), obs(short=0.8, long=0.1)); checks += 1
    assert d.action == 'decrease' and c.target_hz == 36.0, (d, c.target_hz)
    assert c.last_decision_trend_source == 'short_brake'; checks += 1
    assert c.last_decision_trend_kph == 0.8; checks += 1
    # No counter-increase while short brake still calls for reduction.
    d = tick(c, now + timedelta(minutes=2), obs(short=0.8, long=-0.5)); checks += 1
    assert d.action == 'hold' and c.target_hz == 36.0, d
    d = tick(c, now + timedelta(minutes=5), obs(short=0.8, long=-0.5)); checks += 1
    assert d.action == 'hold' and c.target_hz == 36.0, d
    # Reliable short trend is a prerequisite BELOW target; no false brake.
    c = RoomAutoController(); c.target_hz = 40; c.last_adjust = now
    d = tick(c, now + timedelta(seconds=30), obs(sq='low_confidence')); checks += 1
    assert c.target_hz == 40 and d.action == 'hold', d
    c = RoomAutoController(); c.target_hz = 40; c.last_adjust = now
    d = tick(c, now + timedelta(seconds=30), obs(room=20.0, short=1.2, phase='below_restart')); checks += 1
    assert c.target_hz == 40 and d.action == 'hold', d
    # At/above setpoint: reducing a *valid* temperature is allowed without trend.
    c = RoomAutoController(); c.target_hz = 40; c.last_adjust = now
    d = tick(c, now + timedelta(seconds=30), obs(room=21.05, short=None, sq='collecting', phase='tolerance')); checks += 1
    assert d.action == 'decrease' and c.target_hz == 36, (d,c.target_hz)
    # Normal baseline should prefer long trend and diagnose that same sample.
    c = RoomAutoController(); c.target_hz = 35; c.last_adjust = now - timedelta(minutes=10)
    d = tick(c, now, obs(room=20.0, short=1.2, long=0.15, phase='below_restart'),actual=34); checks += 1
    assert c.last_decision_trend_source == 'long' and c.last_decision_trend_kph == 0.15, (d,c.last_decision_trend_source)
    assert c.last_decision_time == now and c.last_decision_room_c == 20.0; checks += 1
    # 15-min fallback while long trend still collecting.
    c = RoomAutoController(); c.target_hz = 35; c.last_adjust = now - timedelta(minutes=10)
    d = tick(c, now, obs(room=20.0, short=0.18, long=None, lq='collecting', phase='below_restart'),actual=34); checks += 1
    assert c.last_decision_trend_source == 'short_fallback'; checks += 1
    # Defrost takes precedence; no Hz change from a tempting short trend.
    c = RoomAutoController(); c.target_hz = 40; c.last_adjust = now
    d = tick(c, now + timedelta(minutes=10), obs(room=20.8, short=1.1, phase='defrost')); checks += 1
    assert d.state == 'paused' and c.target_hz == 40
    # Missing room sensor must block without attempting fast brake.
    c = RoomAutoController(); c.target_hz = 40; c.last_adjust = now
    d = tick(c, now + timedelta(minutes=10), obs(room=None, phase='sensor_missing')); checks += 1
    assert d.state == 'fault' and c.target_hz == 40
    print(f'OK: {checks} controller integration assertions (target, quality, anti-windup, timing, safety).')

if __name__ == '__main__':
    test_run()
