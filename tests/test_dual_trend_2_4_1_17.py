"""Pure-Python regressions for short/long trend policy and anti-windup."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

p = Path(__file__).resolve().parents[1] / 'custom_components' / 'ac_pid_frequency_temp' / 'room_dual_trend.py'
if not p.exists():
    p = Path(__file__).resolve().parent / 'room_dual_trend_2_4_1_17.py'
spec = importlib.util.spec_from_file_location('room_dual_trend', p)
m = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def observation(short, long, sq='reliable', lq='reliable'):
    return SimpleNamespace(short_trend_kph=short, long_trend_kph=long,
                           short_trend_quality=sq, long_trend_quality=lq)


def test_17():
    assert m.control_trend(observation(1.1, 0.15)).rate_kph == 0.15
    assert m.control_trend(observation(1.1, 0.15)).source == 'long'
    assert m.control_trend(observation(0.2, 0.0, lq='low_confidence')).source == 'short_fallback'
    assert m.control_trend(observation(0.2, 0.0, sq='low_confidence', lq='collecting')).rate_kph is None
    assert m.control_trend(observation(0.2, None)).source == 'short_fallback'
    assert m.fast_brake(room_c=20.8, target_c=21.0, short_kph=0.7, short_quality='reliable').active
    assert not m.fast_brake(room_c=20.8, target_c=21.0, short_kph=0.7, short_quality='low_confidence').active
    assert not m.fast_brake(room_c=20.0, target_c=21.0, short_kph=1.0, short_quality='reliable').active
    assert not m.fast_brake(room_c=20.8, target_c=21.0, short_kph=-0.5, short_quality='reliable').active
    assert m.fast_brake(room_c=21.1, target_c=21.0, short_kph=None, short_quality='collecting').active
    assert m.reduced_target(old_hz=40, actual_hz=39, preferred_hz=22) == 36.0
    assert m.reduced_target(old_hz=35, actual_hz=40, preferred_hz=22) == 35.0
    assert m.reduced_target(old_hz=22, actual_hz=24, preferred_hz=22) == 22.0
    assert m.reduced_target(old_hz=24, actual_hz=None, preferred_hz=22) == 22.0
    assert m.reduced_target(old_hz=40, actual_hz=29, preferred_hz=22) == 26.0
    assert m.FAST_BRAKE_COOLDOWN_MIN >= 3.0
    print('16 Regressionstests erfolgreich (Kurz-/Langtrend, Schnellbremse, Anti-Windup).')

if __name__ == '__main__':
    test_17()
