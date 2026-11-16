"""Pure-Python strategy for two independent temperature-trend horizons.

Normal heating prefers a long-term slope; only a reliable short-term slope
can initiate an early *decrease*, never an early increase. No hardware I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

FAST_WINDOW_MIN = 15.0
MIN_LONG_WINDOW_MIN = 30.0
FAST_BRAKE_COOLDOWN_MIN = 3.0
FAST_BRAKE_STEP_HZ = 2.0
INNER_DEADBAND_HEADROOM_HZ = 3.0


@dataclass(frozen=True)
class ControlTrend:
    rate_kph: float | None
    source: str
    quality: str


@dataclass(frozen=True)
class FastBrake:
    active: bool
    reason: str
    projected_30m_c: float | None = None


def _reliable(value, quality):
    try:
        return quality == 'reliable' and value is not None and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def control_trend(observation) -> ControlTrend:
    """Long trend if reliable; short only as conservative startup fallback.

    If both trends are unknown, the existing safety hold remains in force.
    """
    rate = getattr(observation, 'long_trend_kph', None)
    quality = getattr(observation, 'long_trend_quality', 'collecting')
    if _reliable(rate, quality):
        return ControlTrend(float(rate), 'long', 'reliable')
    rate = getattr(observation, 'short_trend_kph', None)
    quality = getattr(observation, 'short_trend_quality', 'collecting')
    if _reliable(rate, quality):
        return ControlTrend(float(rate), 'short_fallback', 'reliable')
    # Backward-compatible diagnostics: do not silently treat low_confidence as reliable.
    return ControlTrend(None, 'none', 'collecting')


def fast_brake(*, room_c: float, target_c: float,
               short_kph: float | None, short_quality: str) -> FastBrake:
    """Allow only a preemptive reduction under convincing near-target heating.

    At/above target, trend is not required to begin reducing the virtual Hz
    request (the BT room temperature itself must already have passed safety
    checks in RoomAutoController). Below target, a reliable >=0.12 K/h short
    slope plus <=30-minute target arrival is required.
    """
    if not (math.isfinite(float(room_c)) and math.isfinite(float(target_c))):
        return FastBrake(False, 'invalid_temperature')
    gap = target_c - room_c
    if gap <= 0:
        return FastBrake(True, 'room_at_or_above_target', round(room_c, 3))
    if gap > 0.5 or not _reliable(short_kph, short_quality):
        return FastBrake(False, 'too_far_or_short_trend_unreliable')
    slope = max(-1.5, min(1.5, float(short_kph)))
    projected = round(room_c + 0.5 * slope, 3)
    if slope >= 0.12 and projected >= target_c - 0.05:
        return FastBrake(True, 'short_trend_predicts_near_target', projected)
    return FastBrake(False, 'short_trend_not_fast_enough', projected)


def reduced_target(*, old_hz: float, actual_hz: float | None,
                   preferred_hz: float) -> float:
    """Respect the inner-loop +/-2 Hz deadband and prevent downward windup."""
    old, preferred = float(old_hz), float(preferred_hz)
    desired = max(preferred, old - FAST_BRAKE_STEP_HZ)
    if actual_hz is not None and math.isfinite(float(actual_hz)) and actual_hz > 1.0:
        below_actual = max(preferred, float(actual_hz) - INNER_DEADBAND_HEADROOM_HZ)
        if old <= below_actual + 0.05:
            return round(old, 1)  # Wait until measured compressor has caught up.
        desired = min(desired, below_actual)
    return round(max(preferred, desired), 1)
