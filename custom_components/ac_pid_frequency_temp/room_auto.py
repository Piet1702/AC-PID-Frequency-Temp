"""Conservative upper-level controller for temperature-driven frequency requests.

Pure Python: no Home Assistant dependency and no direct HVAC, MQTT or power calls.
Only proposes a compressor target in Hz; lower-level frequency regulator does the rest.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math


@dataclass(frozen=True)
class AutoDecision:
    state: str = "inactive"
    action: str = "off"
    reason: str = "Automatische Raumregelung nicht aktiv."
    target_hz: float | None = None
    next_check_min: float | None = None
    heat_suppressed: bool = False


class RoomAutoController:
    """Rate-limited and guarded room-temperature outer control loop."""

    def __init__(self) -> None:
        self.target_hz: float | None = None
        self.last_adjust: datetime | None = None
        self.heat_suppressed = False
        self.decision = AutoDecision()

    def reset(self) -> None:
        self.__init__()

    def update(
        self, *, now: datetime, observation, running: bool,
        preferred_hz: float, max_hz: float, target_room_temp: float,
        max_overheat_k: float, restart_delta_k: float, observation_window_min: float,
    ) -> AutoDecision:
        """Determine new target; never issue commands or alter other controllers."""
        if not running:
            self.reset()
            return self.decision

        preferred = max(20.0, min(60.0, float(preferred_hz)))
        ceiling = max(preferred, min(60.0, float(max_hz)))
        if self.target_hz is None or not math.isfinite(self.target_hz):
            self.target_hz = preferred
            self.last_adjust = now

        def deliver(state, action, reason, *, remaining=None):
            self.decision = AutoDecision(
                state=state, action=action, reason=reason,
                target_hz=round(self.target_hz, 1),
                next_check_min=round(max(0.0, remaining), 1) if remaining is not None else None,
                heat_suppressed=self.heat_suppressed,
            )
            return self.decision

        phase = observation.phase
        if phase in ("defrost", "recovery"):
            # Keep the old target, and restart the evaluation clock after defrost.
            self.last_adjust = now
            return deliver("paused", "hold", f"{phase}: Trend und Hz-Anpassungen pausiert.")
        if phase in ("sensor_stale", "sensor_missing") or observation.room_temp is None:
            self.last_adjust = now
            return deliver("fault", "blocked", "BT-Raumwert fehlt oder ist zu alt; keine neue Heizanforderung.")
        if phase == "inactive":
            self.last_adjust = now
            return deliver("inactive", "hold", "Klimaanlage nicht im Heizbetrieb; keine Einschaltbefehle.")

        room = float(observation.room_temp)
        upper = float(target_room_temp) + float(max_overheat_k)
        lower = float(target_room_temp) - float(restart_delta_k)
        if room >= upper:
            self.heat_suppressed = True
            self.last_adjust = now
            return deliver("heat_pause", "reduce_heat_demand", "Überheizungsgrenze erreicht; keine Dauerlauf-Hz erzwingen.")
        if self.heat_suppressed:
            if room > lower:
                return deliver("heat_pause", "reduce_heat_demand", "Noch oberhalb der unteren Wiederanlaufreferenz; Heizanforderung bleibt reduziert.")
            self.heat_suppressed = False
            self.target_hz = preferred
            self.last_adjust = now
            return deliver("resuming", "resume_preferred", "Untere Referenz unterschritten; vorsichtig mit bevorzugten Hz neu anfordern.")

        # Near target, intentionally check more slowly.
        near_target = room >= target_room_temp - 0.5
        minutes = float(observation_window_min) * (2.0 if near_target else 1.0)
        minutes = min(120.0, max(15.0, minutes))
        if self.last_adjust is None or now < self.last_adjust:
            self.last_adjust = now
        elapsed = (now - self.last_adjust).total_seconds() / 60.0
        if elapsed < minutes:
            return deliver("monitoring", "hold", "Beobachtungsintervall läuft; Ziel-Hz bleiben stabil.", remaining=minutes-elapsed)

        trend = observation.trend_kph
        if trend is None:
            # Never change the frequency based on a very short/noisy observation.
            return deliver("collecting", "hold", "Noch kein ausreichend langer, gültiger Temperaturtrend.", remaining=5)

        previous = self.target_hz
        reason = "Heizleistung und Temperaturtrend sind ausreichend stabil."
        if room >= target_room_temp:
            self.target_hz = max(preferred, previous - 1.0)
            reason = "Zieltemperatur erreicht: Leistung in 1-Hz-Schritten an Dauerbetriebswert annähern."
        elif near_target:
            if trend > 0.12:
                self.target_hz = max(preferred, previous - 1.0)
                reason = "Nahe Zieltemperatur: weiterer Temperaturanstieg erwartet, 1 Hz weniger."
            elif trend < -0.02:
                self.target_hz = min(ceiling, previous + 1.0)
                reason = "Raum kühlt nahe am Ziel ab: vorsichtig 1 Hz mehr."
        elif trend < 0.05:
            self.target_hz = min(ceiling, previous + 2.0)
            reason = "Deutlich unter Ziel, kaum Temperaturanstieg: 2 Hz mehr."
        elif trend > 0.30:
            self.target_hz = max(preferred, previous - 1.0)
            reason = "Aufheizen schneller als erwünscht: 1 Hz weniger."

        self.target_hz = max(preferred, min(ceiling, self.target_hz))
        self.last_adjust = now
        if self.target_hz > previous:
            action = "increase"
        elif self.target_hz < previous:
            action = "decrease"
        else:
            action = "hold"
        return deliver("controlling", action, reason, remaining=minutes)
