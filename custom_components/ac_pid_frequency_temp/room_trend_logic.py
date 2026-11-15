"""Pure bounded linear trend estimator for change-only BT temperatures.

The timestamps are inferred BT-contact times, NOT forced HA state updates.
The regression uses all available time-separated points within the configured
window. Quality is separate from numeric slope; low-confidence data is NEVER
an instruction to increase or decrease compressor Hz.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
import math


@dataclass(frozen=True)
class TrendEstimate:
    trend_kph: float | None = None
    quality: str = "collecting"
    span_minutes: float = 0.0
    samples: int = 0
    reason: str = "Zu wenig Messhistorie."


def estimate_trend(samples, *, now: datetime, window_min: float = 30.0) -> TrendEstimate:
    horizon = max(15.0, min(120.0, float(window_min)))
    cutoff = now - timedelta(minutes=horizon)
    ordered = sorted((t, float(v)) for t, v in samples
                     if cutoff <= t <= now and math.isfinite(float(v)))
    # Deduplicate timestamps; the last reading wins.
    points = []
    for t, v in ordered:
        if points and t == points[-1][0]:
            points[-1] = (t, v)
        else:
            points.append((t, v))
    if len(points) < 4:
        return TrendEstimate(samples=len(points), reason="Weniger als vier echte Kontaktzeitpunkte.")
    times = [(t - points[0][0]).total_seconds() / 3600.0 for t, _ in points]
    span = times[-1] * 60
    if span < 12.0:
        return TrendEstimate(span_minutes=round(span, 1), samples=len(points),
                             reason="Messreihe deckt noch keine 12 Minuten ab.")
    if (now - points[-1][0]).total_seconds() > 180:
        return TrendEstimate(span_minutes=round(span, 1), samples=len(points),
                             reason="Kein hinreichend aktueller BT-Kontaktzeitpunkt.")
    mean_x = sum(times) / len(times)
    mean_y = sum(v for _, v in points) / len(points)
    denom = sum((x - mean_x) ** 2 for x in times)
    if denom <= 1e-12:
        return TrendEstimate(span_minutes=round(span, 1), samples=len(points),
                             reason="Messzeitpunkte liegen zu dicht beieinander.")
    slope = sum((x - mean_x) * (v - mean_y)
                for x, (_, v) in zip(times, points)) / denom
    maximum_gap_min = max((times[i] - times[i-1]) * 60
                          for i in range(1, len(times)))
    reliable = (span >= horizon * 0.75 and len(points) >= 8
                and maximum_gap_min <= min(12.0, horizon * 0.33))
    return TrendEstimate(
        trend_kph=round(slope, 3),
        quality="reliable" if reliable else "low_confidence",
        span_minutes=round(span, 1), samples=len(points),
        reason=("Trend aus zeitlich verteilten BT-Kontakten." if reliable
                else "Vorlaeufige Steigung; fuer Hz-Aenderungen noch nicht belastbar."),
    )


class TrendUnknownHistory:
    """Counts transitions into numeric-unknown over the last 30 min in RAM."""
    def __init__(self):
        self.last_unknown = None
        self.transitions = []

    def observe(self, now: datetime, unknown: bool) -> None:
        if unknown != self.last_unknown:
            self.transitions.append((now, bool(unknown)))
            self.last_unknown = bool(unknown)
        cutoff = now - timedelta(minutes=30)
        self.transitions = [(t, u) for t, u in self.transitions if t >= cutoff]

    def unknown_entries_30m(self, now: datetime) -> int:
        cutoff = now - timedelta(minutes=30)
        return sum(1 for t, u in self.transitions if u and t >= cutoff)
