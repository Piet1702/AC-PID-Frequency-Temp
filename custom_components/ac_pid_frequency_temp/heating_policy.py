"""Conservative simulated-temperature ceiling for strong room heat demand.

Pure Python: does not alter any HA climate, power, MQTT, or selected automation.
The cap is active only for a *valid measured* temperature, room >=0.8 K below
its target, and compressor below the user-selected maximum-Hz threshold.
"""
from __future__ import annotations
import math


def apply_heating_demand_ceiling(*, output: float, previous_output: float | None,
                                 climate_setpoint: float, real_room_temp: float | None,
                                 room_target: float, actual_hz: float,
                                 maximum_hz: float, max_offset: float,
                                 max_drop_per_tick_k: float = 0.3,
                                 ) -> tuple[float, bool, float | None]:
    values = (output, climate_setpoint, room_target, actual_hz, maximum_hz, max_offset)
    if real_room_temp is None or not all(math.isfinite(float(v)) for v in values):
        return output, False, None
    if not math.isfinite(float(real_room_temp)):
        return output, False, None
    gap = room_target - real_room_temp
    if gap < 0.8 or actual_hz >= maximum_hz - 2.0 or max_offset < 0.2:
        return output, False, None
    # Unlike the inner Hz PID, this cap signals the *room's* urgent heat need.
    # 1.9 K gap => approx. 0.6 K below the HVAC's own unchanged setpoint.
    desired_delta = min(0.8, max(0.35, 0.25 + (gap - 0.8) * 0.30), max_offset)
    cap = round(climate_setpoint - desired_delta, 2)
    if output <= cap + 0.001:
        return output, False, cap
    next_output = cap
    if previous_output is not None and math.isfinite(float(previous_output)):
        next_output = max(cap, float(previous_output) - max_drop_per_tick_k)
    # Never raise an already lower simulated temperature; respect the
    # outer regulator's configured offset bound and a slow 0.3-K-per-tick ramp.
    fixed = min(output, next_output)
    fixed = max(climate_setpoint - max_offset, fixed)
    fixed = math.floor(fixed * 10.0 + 0.5) / 10.0
    return fixed, fixed < output - 0.001, cap
