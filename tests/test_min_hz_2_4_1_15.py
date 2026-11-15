#!/usr/bin/env python3
"""Regressiontests using the installed real pure-Python regelung.py module."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
import math

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'custom_components' / 'ac_pid_frequency_temp' / 'regelung.py'
spec = importlib.util.spec_from_file_location('ac_pid_frequency_temp_regelung_215_test', SOURCE)
assert spec is not None and spec.loader is not None
import sys
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

N = 0

def check(condition: bool, message: str) -> None:
    global N
    if not condition:
        raise AssertionError(message)
    N += 1

Params, State, step = module.Params, module.State, module.step
p = Params(interval_s=60.0)

s = State()
s.load_learned_data({'learned_min_table': {'normal': 55.0, 'warm': 40.0, 'cold': 60.0}})
check(s.learned_min_table['normal'] == 18.0, '55-Hz altzustand muss bei Neuladen bereinigt werden')
check(s.learned_min_table['warm'] == 14.0, 'Warm zone must not keep elevated persisted floor')
check(s.learned_min_table['cold'] == 24.0, 'Cold zone must not keep elevated persisted floor')

s2 = State()
s2.load_learned_data({'learned_min_table': {'normal': 12.0}})
check(s2.learned_min_table['normal'] == 12.0, 'Bereits kleineres gelerntes Minimum behalten')
s2.current_outdoor_bin = 'normal'
s2.learned_min_hz = 50
check(s2.learned_min_hz == 12.0, 'Property setter darf Minimum nicht erhoehen')

s3 = State()
s3.load_learned_data({'learned_min_hz': 55.0})
check(s3.learned_min_table['normal'] == 18.0, 'Legacy Speicherwert bereinigen')

# Reproduce the observed 21.2°C / 55Hz / 51.7Hz case. At setpoint 20°C,
# it MUST be able to raise simulated temperature over 20°C (less heat), rather
# than wrongly treating 55Hz as hardware minimum and staying in min_mod.
s = State()
s.output = 20.0
s.time_since_last_step = 300.0
s.hz_prev1 = 55.0
s.stable_cycles = 0
results = []
for _ in range(5):
    r = step(p, s, setpoint=20.0, hz=55.0, target_hz=51.7,
             outdoor_temp=9.8, room_temp=21.2, defrost=False,
             automatic_target=True, overheat_limit_temp=22.0)
    results.append(r)
check(all(result.learned_min_hz <= 18.0 for result in results),
      'Stagnation bei 55Hz darf Minimum nicht auf 55 anheben')
check(all(abs(result.effective_target_hz - 51.7) < .01 for result in results),
      'Effektives Ziel muss dem Raumregler folgen')
check(any(result.published > 20.0 for result in results),
      'Simulierte Temperatur muss sinkenden Heizbedarf signalisieren koennen')
check(all(result.mode != 'min_mod' for result in results),
      'Bei 51.7Hz Ziel / 55Hz Ist darf kein falsches min_mod entstehen')

# Apparent compressor-off at 55 Hz is not evidence of a minimum at 55 Hz.
s = State()
s.last_running_hz = 55.0
r = step(p, s, setpoint=20.0, hz=0.0, target_hz=51.7,
         outdoor_temp=9.8, room_temp=21.2, defrost=False,
         automatic_target=True, overheat_limit_temp=22.0)
check(s.learned_min_table['normal'] == 18.0,
      'Bei Abschalten aus 55Hz nicht auf 55Hz lernen')

# Non-transient observed low can only lower a previously-known floor.
s = State()
s.learned_min_table['normal'] = 25.0  # In-memory prior observation for this test.
s.current_outdoor_bin = 'normal'
s.stable_cycles = 3
s.hz_prev1 = 22.0
step(p, s, setpoint=20.0, hz=22.0, target_hz=22.0,
     outdoor_temp=9.8, room_temp=20.0,
     automatic_target=True, overheat_limit_temp=22.0)
check(s.learned_min_table['normal'] <= 22.0,
      'Bestaetigter stabiler niedriger Wert darf das Minimum senken')

# No automatic reset may increase a known lower value due to target changes.
s = State()
s.learned_min_table['normal'] = 12.0
s.last_target_hz = 40.0
s.last_setpoint = 20.0
step(p, s, setpoint=20.0, hz=30.0, target_hz=50.0,
     outdoor_temp=9.8, room_temp=20.0,
     automatic_target=False, overheat_limit_temp=22.0)
check(s.learned_min_table['normal'] == 12.0,
      'User-Trigger darf gelerntes Minimum nicht erhoehen')

print(f'OK: {N} Mindest-Hz-Regressionstests bestanden (echte regelung.py).')
