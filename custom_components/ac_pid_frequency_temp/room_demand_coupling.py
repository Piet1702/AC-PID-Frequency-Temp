"""Couple room-heat demand to the inner, original compressor-Hz controller.

Pure Python. This calculates a requested *frequency target*, never compressor
commands, HVAC power, climate setpoints or MQTT messages. The original inner
Hz controller remains responsible for manipulating the simulated temperature.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

FORECAST_MINUTES = 45.0
TARGET_APPROACH_MARGIN_K = 0.10
SLOW_HEAT_FORECAST_GAP_K = 0.30
HZ_HEADROOM_OVER_ACTUAL = 3.0  # must exceed 2-Hz inner-loop deadband
HZ_STEP = 2.0


@dataclass(frozen=True)
class RoomDemandPlan:
    target_hz: float
    reason: str
    action: str  # increase | decrease | hold
    forecast_room_c: float
    forecast_deficit_k: float
    aligned_to_actual: bool
    actual_hz_anchor: float | None
    heat_raise: bool


def plan_room_demand(
    *, old_hz: float, actual_hz: float | None,
    room_temp: float, room_target: float, trend_kph: float,
    preferred_hz: float, max_hz: float,
    may_raise: bool = True,
) -> RoomDemandPlan:
    """Return a conservative outer-loop target from a *reliable* room trend.

    Only call after normal timing, BT-quality, defrost and fault guards. An
    apparently slow warming near target is not, by itself, evidence of imminent
    overshoot. Raise from the actual running point when the old outer target
    is below it and the 45-min forecast is still far from the room target.
    """
    vals = (old_hz, room_temp, room_target, trend_kph, preferred_hz, max_hz)
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError('Room demand requires finite values')
    if actual_hz is not None and not math.isfinite(float(actual_hz)):
        actual_hz = None
    hi = max(20.0, min(90.0, float(max_hz)))
    lo = max(20.0, min(hi, float(preferred_hz)))
    old = max(lo, min(hi, float(old_hz)))
    room = float(room_temp)
    gap = float(room_target) - room
    # Bound the forecast rate against implausible isolated sensor spikes.
    capped_trend = max(-1.5, min(1.5, float(trend_kph)))
    forecast = round(room + capped_trend * FORECAST_MINUTES / 60.0, 3)
    forecast_gap = round(float(room_target) - forecast, 3)
    next_hz = old
    aligned = False
    raised = False
    anchor = round(float(actual_hz), 2) if actual_hz is not None else None

    def request_less_heat(delta: float, rationale: str) -> str:
        nonlocal next_hz, aligned
        desired = max(lo, old - delta)
        if anchor is not None and anchor > 1.0:
            # A target just 1-2 Hz below actual is still inside the original
            # PID's deadband: first correction may need virtual realignment.
            below_actual = max(lo, anchor - HZ_HEADROOM_OVER_ACTUAL)
            if old <= below_actual + 0.05:
                return (rationale + ' Bereits unter realer Ist-Hz: '
                        'wartet auf Reaktion des Kompressors.')
            if below_actual < desired:
                desired = below_actual
                aligned = True
        next_hz = desired
        return rationale

    if gap <= 0:
        delta = 4.0 if capped_trend > 0.20 else HZ_STEP
        reason = request_less_heat(
            delta, 'Raumziel erreicht: Wärmeanforderung vorsichtig reduzieren.')
    elif (forecast_gap <= TARGET_APPROACH_MARGIN_K
          and capped_trend > 0.08):
        reason = request_less_heat(
            HZ_STEP,
            '45-Minuten-Prognose erreicht Raumziel: '
            'vorausschauend weniger Heizleistung anfordern.')
    elif (gap >= 0.25 and forecast_gap >= SLOW_HEAT_FORECAST_GAP_K):
        if not may_raise:
            reason = ('Raum erwärmt sich zu langsam; 5-Minuten-Sperre '
                      'für weitere Heizanforderung aktiv.')
        elif anchor is None or anchor <= 1.0:
            reason = ('Kein laufender Kompressor-Istwert: '
                      'ohne Referenz keine blinde Heizleistungsanhebung.')
        else:
            # Virtual target must be above actual+2Hz (inner deadband),
            # but may not accumulate if the plant has not responded yet.
            target_ceiling_from_actual = min(hi, anchor + HZ_HEADROOM_OVER_ACTUAL)
            if old >= target_ceiling_from_actual - 0.05:
                reason = ('Heizbedarf besteht weiter, aber das Ziel liegt bereits '
                          'mindestens 3 Hz über Ist bzw. an der Maximalgrenze: '
                          'auf Kompressorreaktion warten, kein Windup.')
            else:
                request = min(hi, old + HZ_STEP)
                if target_ceiling_from_actual > request:
                    request = target_ceiling_from_actual
                    aligned = True
                next_hz = min(request, target_ceiling_from_actual)
                raised = next_hz > old + 0.05
                reason = (
                    'Raum erwärmt sich zu langsam: virtuelles Ziel '
                    + ('an aktuelle Kompressor-Hz + 3 angeglichen. '
                       if aligned else 'um maximal 2 Hz angehoben. ')
                    + 'Innerer PID darf simulierte Temperatur absenken.'
                )
    else:
        reason = ('Raumtemperaturentwicklung ausreichend: '
                  'beide Regelkreise vorerst halten.')
    next_hz = round(max(lo, min(hi, next_hz)), 1)
    action = ('increase' if next_hz > old + 0.05 else
              'decrease' if next_hz < old - 0.05 else 'hold')
    return RoomDemandPlan(
        target_hz=next_hz, reason=reason, action=action,
        forecast_room_c=forecast, forecast_deficit_k=forecast_gap,
        aligned_to_actual=aligned, actual_hz_anchor=anchor,
        heat_raise=raised,
    )
