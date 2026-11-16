"""Pure-Python timeline test of the REAL installed RoomObserver.

The user can run this without a Home Assistant runtime.
"""
from __future__ import annotations
import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / 'custom_components' / 'ac_pid_frequency_temp'
assert COMP.is_dir()
name = '_ac_pid_217_observer'
pkg = ModuleType(name)
pkg.__path__ = [str(COMP)]
sys.modules[name] = pkg
RoomObserver = importlib.import_module(name + '.room_observer').RoomObserver


def test_windows():
    checks = 0
    start = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)
    observer = RoomObserver()
    states = []
    for minute in range(0, 32):
        now = start + timedelta(minutes=minute)
        t = 19.0 + 0.5 * minute / 60.0
        obs = observer.update(
            now=now, room_temp=t, report_at=now, sensor_status='ok',
            age_seconds=2.0, heating=True, defrost=False,
            actual_hz=35.0, target_temp=21.0, preferred_hz=22.0,
            max_overheat_k=1.0, restart_delta_k=0.5, window_min=5.0,
            trend_window_min=15.0,
        )
        states.append(obs)
    obs = states[15]
    assert obs.short_trend_quality == 'reliable', obs; checks += 1
    assert obs.long_trend_quality != 'reliable', obs; checks += 1
    obs = states[30]
    assert obs.short_trend_quality == 'reliable', obs; checks += 1
    assert obs.long_trend_quality == 'reliable', obs; checks += 1
    assert obs.long_window_minutes >= 22.5, obs; checks += 1
    assert 0.35 < obs.long_trend_kph < 0.65, obs; checks += 1
    assert 0.35 < obs.short_trend_kph < 0.65, obs; checks += 1
    assert obs.long_samples > obs.short_samples, obs; checks += 1
    # Defrost must invalidate both trends, not continue using old values.
    now = start + timedelta(minutes=33)
    obs = observer.update(
        now=now, room_temp=19.3, report_at=now, sensor_status='ok',
        age_seconds=1.0, heating=True, defrost=True,
        actual_hz=35.0, target_temp=21.0, preferred_hz=22.0,
        max_overheat_k=1.0, restart_delta_k=0.5, window_min=5.0,
        trend_window_min=15.0,
    )
    assert obs.short_trend_kph is None and obs.long_trend_kph is None, obs; checks += 1
    assert obs.phase == 'defrost'; checks += 1
    print(f'OK: {checks} Beobachter-Integrationstests (15/30 min, 15-min-Konfiguration, Abtauung).')

if __name__ == '__main__':
    test_windows()
