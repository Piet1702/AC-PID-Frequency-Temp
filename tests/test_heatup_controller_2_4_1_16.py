#!/usr/bin/env python3
"""Integration test using the *installed* real RoomAutoController source, no HA."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import importlib.util
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'custom_components' / 'ac_pid_frequency_temp'
pure = SRC / 'room_demand_coupling.py'
source = SRC / 'room_auto.py'
if not pure.is_file() or not source.is_file():
    raise SystemExit('Tests nur NACH Installation im echten Repository ausführen.')

spec = importlib.util.spec_from_file_location('heatup_pure_216', pure)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

tree = ast.parse(source.read_text(encoding='utf-8-sig'))
classes = [node for node in tree.body if isinstance(node, ast.ClassDef)
           and node.name in {'AutoDecision', 'ContinuityLearning', 'RoomAutoController'}]
assert len(classes) == 3, 'Drei bekannte Klassen in room_auto.py erwartet'
mod = ModuleType('heatup_runtime_216')
mod.__dict__.update(dataclass=dataclass, datetime=datetime, timedelta=timedelta,
                    math=math, plan_room_demand=m.plan_room_demand)
sys.modules[mod.__name__] = mod
exec(compile(ast.fix_missing_locations(ast.Module(body=classes, type_ignores=[])),
             str(source), 'exec'), mod.__dict__)


def obs(room, trend, quality='reliable', phase='below_restart'):
    return SimpleNamespace(phase=phase, room_temp=room, trend_kph=trend,
                           trend_quality=quality, minutes_at_min_hz=0.0)


def tick(ctrl, now, *, room=19.6, trend=.585, quality='reliable',
         phase='below_restart', actual=66.7):
    return ctrl.update(now=now, observation=obs(room, trend, quality, phase),
                       running=True, preferred_hz=22, start_hz=45,
                       max_hz=70, target_room_temp=21.0,
                       max_overheat_k=1, restart_delta_k=.5,
                       observation_window_min=5, heatup_duration_min=150,
                       actual_hz=actual, outdoor_temp=9, min_hz_guard_minutes=0)

now = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
c = mod.RoomAutoController()
c.target_hz = 70
c.last_adjust = now - timedelta(minutes=10)
x = tick(c, now)
assert x.target_hz < 70, ('Bei ausreichend schnellem Trend muss die Heizanforderung '
                           'sinken statt auf 70Hz zu verharren')
assert c.demand_requested_rate_kph == .56, c.demand_requested_rate_kph
assert c.heatup_elapsed_min == 0

x = tick(c, now + timedelta(minutes=60), room=20.0, trend=.3, actual=48)
assert c.heatup_elapsed_min == 60
assert c.demand_requested_rate_kph >= .6
assert c.demand_remaining_heatup_min == 90

x = tick(c, now + timedelta(minutes=65), room=21.2, trend=.5, actual=40,
         phase='tolerance')
assert x.action != 'increase'
assert c.heatup_started_at is None

c2 = mod.RoomAutoController()
x = tick(c2, now, room=19.5, trend=.0, quality='collecting')
assert x.action != 'increase', 'Unzuverlässiger Trend darf keine Hz-Anhebung erzeugen'

x = tick(c2, now + timedelta(minutes=15), room=19.5, trend=.0,
         phase='defrost')
assert x.state == 'paused'

print('OK: RoomAutoController 2.4.1.16 integriert: 8 Prüfungen erfolgreich.')
