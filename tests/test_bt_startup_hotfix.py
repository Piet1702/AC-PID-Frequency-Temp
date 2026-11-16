#!/usr/bin/env python3
"""Offline-Regressionstests: Einschalten mit bestaetigtem BT und sichere Ablehnung."""
from __future__ import annotations

import ast
import asyncio
import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWITCH = ROOT / "custom_components" / "ac_pid_frequency_temp" / "switch.py"
CONTROLLER = ROOT / "custom_components" / "ac_pid_frequency_temp" / "controller.py"


def find_method(source, cls, method):
    t = ast.parse(source)
    c = [x for x in t.body if isinstance(x, ast.ClassDef) and x.name == cls]
    assert len(c) == 1, f"{cls}: Klassendefinition fehlt"
    f = [x for x in c[0].body if isinstance(x, ast.AsyncFunctionDef) and x.name == method]
    assert len(f) == 1, f"{cls}.{method}: Methode fehlt"
    return f[0]


class HomeAssistantError(Exception):
    pass


source = SWITCH.read_text(encoding="utf-8-sig")
method = find_method(source, "EnabledSwitch", "async_turn_on")
assert "self.controller.room_input_snapshot()" in ast.unparse(method)
assert "room_sensor_snapshot(" not in ast.unparse(method), "Die alte Pruefung ist noch aktiv"

# Die echte Einschaltmethode aus switch.py isoliert kompilieren, ohne HA zu importieren.
cloned = copy.deepcopy(method)
cloned.decorator_list = []
clazz = ast.ClassDef(name="SwitchUnderTest", bases=[], keywords=[], body=[cloned], decorator_list=[])
module = ast.fix_missing_locations(ast.Module(body=[clazz], type_ignores=[]))
ns = {
    "Any": object,
    "MODE_ROOM_AUTO": "room_auto",
    "MODE_ROOM_OBSERVE": "room_observe",
    "CONF_CONTROL_MODE": "mode",
    "CONF_ROOM_TEMP": "room_temp",
    "CONF_ROOM_STALE": "stale",
    "HomeAssistantError": HomeAssistantError,
}
exec(compile(module, "switch.py:EnabledSwitch", "exec"), ns)
SwitchUnderTest = ns["SwitchUnderTest"]

count = 0


def check(cond, msg):
    global count
    if not cond:
        raise AssertionError(msg)
    count += 1


class FakeController:
    def __init__(self, status, mode="room_auto"):
        self.config = {"mode": mode, "room_temp": "sensor.bt", "stale": 300}
        self.status = status
        self.calls = 0
        self.enabled_calls = []

    def room_input_snapshot(self):
        self.calls += 1
        return self.status, 8.0, None

    def async_set_enabled(self, enabled):
        self.enabled_calls.append(enabled)


async def run(status, mode="room_auto"):
    obj = SwitchUnderTest()
    obj.controller = FakeController(status, mode)
    try:
        await obj.async_turn_on()
    except HomeAssistantError as e:
        return obj.controller, str(e)
    return obj.controller, None


for status in ("ok",):
    c, error = asyncio.run(run(status))
    check(error is None, "Bestaetigter BT-Kontakt muss Einschalten erlauben")
    check(c.enabled_calls == [True], "Regler muss eingeschaltet werden")
    check(c.calls == 1, "BT-Pruefung muss Controller-Snapshot verwenden")

for status in ("unchanged", "stale", "invalid", "missing", "not_configured"):
    c, error = asyncio.run(run(status))
    check(error is not None, f"{status} muss gesperrt bleiben")
    check(not c.enabled_calls, f"{status} darf Regler nicht aktivieren")

c, error = asyncio.run(run("ok", mode="room_observe"))
check(error is not None, "Beobachtungsmodus darf nicht aktiviert werden")
check(not c.enabled_calls, "Beobachtungsmodus muss ausgeschaltet bleiben")

c, error = asyncio.run(run("unchanged", mode="manual"))
check(error is None, "Manueller Modus darf nicht durch Room-Auto-BT-Guard gesperrt sein")
check(c.enabled_calls == [True], "Manueller Modus muss einstellbar bleiben")

# Kontrolliere, dass die vorhandene Rueckmeldung fuer confirmed und timeout besteht.
csrc = CONTROLLER.read_text(encoding="utf-8-sig")
ctl = ast.parse(csrc)
classes = [x for x in ctl.body if isinstance(x, ast.ClassDef) and x.name == 'AcPidFrequencyController']
check(len(classes) == 1, "Controller fehlt")
methods = [x for x in classes[0].body if isinstance(x, ast.FunctionDef) and x.name == 'room_input_snapshot']
check(len(methods) == 1, "BT-Snapshot fehlt")
body = ast.unparse(methods[0])
check('bt_monitor.state()' in body, "BT-Kontaktsignal fehlt")
values = {n.value for n in ast.walk(methods[0])
          if isinstance(n, ast.Constant) and isinstance(n.value, str)}
check({"confirmed", "ok"}.issubset(values), "Bestaetigter Kontakt nicht erlaubt")
check({"timeout", "stale"}.issubset(values), "Timeout nicht gesperrt")

print(f"OK: {count} BT-Start-Regressionstests bestanden")
