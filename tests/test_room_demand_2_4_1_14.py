#!/usr/bin/env python3
"""Pure-Python regression tests for 2.4.1.14; no HA installation needed.

When run in the fork root, also extracts and executes the actual patched
RoomAutoController class to validate its integration with the planner.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import importlib.util
import math
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType

ROOT = Path(__file__).resolve().parent.parent
COMP = ROOT / 'custom_components' / 'ac_pid_frequency_temp'
assert COMP.is_dir(), f'Integration folder not found: {COMP}'
sys.path.insert(0, str(COMP))
from room_demand_coupling import plan_room_demand

N = 0

def check(cond: bool, message: str) -> None:
    global N
    if not cond:
        raise AssertionError(message)
    N += 1


def plan(**kw):
    args = dict(old_hz=39.0, actual_hz=54.0, room_temp=20.3,
                room_target=21.0, trend_kph=0.267,
                preferred_hz=22.0, max_hz=70.0)
    args.update(kw)
    return plan_room_demand(**args)


p = plan()
check(p.target_hz == 57.0 and p.action == 'increase' and p.aligned_to_actual,
      'real operating point 54Hz must yield target 57Hz')
check(abs(p.forecast_room_c - 20.5) < 0.001,
      '45-minute forecast for user diagnostic')
check(plan(may_raise=False).target_hz == 39,
      '5-minute raise lock must hold')
check(plan(old_hz=57.0, actual_hz=54.0).target_hz == 57.0,
      'do not keep raising if real compressor has not followed')
check(plan(old_hz=57.0, actual_hz=55.0).target_hz == 58.0,
      'a rising real compressor permits another limited virtual step')
check(plan(old_hz=39.0, actual_hz=54.0, room_temp=20.9, trend_kph=0.4).target_hz == 39.0,
      'do not keep reducing when target already below actual by >3Hz')
check(plan(old_hz=67, actual_hz=68).target_hz == 70.0,
      'must respect configured 70Hz maximum')
check(plan(old_hz=55, actual_hz=None).target_hz == 55.0,
      'missing actual-Hz must hold instead of blind raise')
check(plan(old_hz=55, actual_hz=54, room_temp=20.9, trend_kph=0.4).target_hz == 51.0,
      'approaching 21°C in forecast should gently decrease')
check(plan(old_hz=55, actual_hz=54, room_temp=20.5, trend_kph=0.2).target_hz == 57.0,
      'positive but too-slow trend must not cause early reduction')
check(plan(old_hz=55, actual_hz=54, room_temp=21.0, trend_kph=0.2).target_hz == 51.0,
      'room setpoint met must decrease')
check(plan(old_hz=55, actual_hz=54, room_temp=21.2, trend_kph=0.4).target_hz == 51.0,
      'overshoot forecast must reduce more strongly once already warm')
check(plan(old_hz=55, actual_hz=54, room_temp=20.7, trend_kph=0.5).target_hz == 51.0,
      '45-minute forecast to 21°C must reduce')
check(plan(old_hz=55, actual_hz=54, room_temp=20.55, trend_kph=0.4).target_hz == 55.0,
      'neither heat nor reduce when adequate rise but not imminent')

# Test the real RoomAutoController class without importing Home Assistant.
source = (COMP / 'room_auto.py').read_text(encoding='utf-8')
parsed = ast.parse(source)
cls_names = {'AutoDecision', 'ContinuityLearning', 'RoomAutoController'}
classes = [node for node in parsed.body if isinstance(node, ast.ClassDef) and node.name in cls_names]
check(len(classes) == 3, 'three class definitions from actual room_auto.py required')
ns = {'__name__': 'room_auto_test', 'dataclass': dataclass,
      'datetime': datetime, 'timedelta': timedelta, 'math': math,
      'plan_room_demand': plan_room_demand}
runtime_mod = ModuleType('room_auto_test')
runtime_mod.__dict__.update(ns)
sys.modules['room_auto_test'] = runtime_mod
exec(compile(ast.fix_missing_locations(ast.Module(body=classes, type_ignores=[])),
             'room_auto.py', 'exec'), runtime_mod.__dict__)
Ctrl = runtime_mod.RoomAutoController
now = datetime(2026, 11, 15, 16, 36, tzinfo=timezone.utc)


def obs(room=20.3, trend=0.267, quality='reliable', phase='below_restart'):
    return SimpleNamespace(phase=phase, room_temp=room, trend_kph=trend,
        trend_quality=quality, window_minutes=30.0,
        minutes_at_min_hz=0.0)


def update(c, at, *, observation=None, actual=54):
    return c.update(now=at, observation=observation or obs(), running=True,
        preferred_hz=22, start_hz=45, max_hz=70,
        target_room_temp=21, max_overheat_k=1,
        restart_delta_k=0.5, observation_window_min=5,
        actual_hz=actual, outdoor_temp=10.0)

c = Ctrl()
c.target_hz = 39
c.last_adjust = now - timedelta(minutes=10)
d = update(c, now)
check(d.action == 'increase' and d.target_hz == 57,
      'integrated RoomAutoController 39->57 when slow rising below target')
check(c.demand_aligned_to_actual and c.demand_actual_hz_anchor == 54,
      'alignment diagnostic populated')
check(update(c, now + timedelta(minutes=1)).target_hz == 57,
      'no extra adjustment before 5-min control interval')
check(update(c, now + timedelta(minutes=5)).target_hz == 57,
      'anti-windup: wait at actual+3Hz until compressor follows')
c.last_adjust = now - timedelta(minutes=10)
d = update(c, now + timedelta(minutes=6), observation=obs(20.9, 0.4, phase='approaching'))
check(d.action == 'decrease' and d.target_hz == 51,
      'forecast near 21C must allow the inner PID to request less heat')

c2 = Ctrl()
c2.target_hz = 45
c2.last_adjust = now - timedelta(minutes=10)
check(update(c2, now, observation=obs(19.7, 0.0)).target_hz == 57,
      'strong heat demand must align from measured 54Hz')
c3 = Ctrl()
c3.target_hz = 39
c3.last_adjust = now - timedelta(minutes=10)
check(update(c3, now, observation=obs(20.3, 0.267, quality='low_confidence')).target_hz == 39,
      'low-confidence room trend must never align')
check(update(c3, now, observation=obs(20.3, 0.267, phase='defrost')).state == 'paused',
      'defrost must override coupling')
check(update(c3, now, observation=obs(20.3, 0.267, phase='sensor_stale')).state == 'fault',
      'stale BT sensor must override coupling')
check(update(c3, now, observation=obs(22.1, 0.267, phase='above_limit')).heat_suppressed,
      'overheat limit must latch')

# Verify the real, unmodified inner PID when regelung.py is present.
inner_file = COMP / 'regelung.py'
if inner_file.is_file():
    mod_name = 'ac_pid_test_regelung'
    spec = importlib.util.spec_from_file_location(mod_name, inner_file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    state = mod.State()
    state.output = 20.0
    state.time_since_last_step = 400.0
    result = mod.step(mod.Params(), state, 20.0, 54.0, 57.0,
                      outdoor_temp=10, room_temp=20.3,
                      automatic_target=True, overheat_limit_temp=22.0)
    check(result.published < 20.0 and result.mode == 'raise',
          'inner Hz regulator must LOWER simulated T for target 57Hz vs actual 54Hz')
else:
    print('Hinweis: regelung.py im Minimal-Fixture fehlt; Inner-PID-Test nur im echten Repo.')

print(f'OK: {N} Regressionen bestanden.')
