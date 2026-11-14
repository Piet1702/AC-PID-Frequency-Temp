"""Adaptive room-temperature outer loop with bounded anti-cycling guidance.

Pure Python. Never controls HVAC power, mode, setpoint, or MQTT directly.
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


class ContinuityLearning:
    """Conservative long-running stable-frequency estimates by outdoor zone."""

    def __init__(self) -> None:
        self.learned: dict[str, dict[str, float | int]] = {}
        self.candidate_since: datetime | None = None
        self.candidate_hz: float | None = None
        self.candidate_zone: str | None = None
        self.last_learning: datetime | None = None

    @staticmethod
    def zone(outdoor_temp: float | None) -> str:
        if outdoor_temp is None or not math.isfinite(outdoor_temp):
            return "unknown"
        if outdoor_temp < 2:
            return "frost"
        if outdoor_temp <= 10:
            return "transition"
        return "mild"

    def learned_hz(self, outdoor_temp: float | None) -> float | None:
        item = self.learned.get(self.zone(outdoor_temp))
        return round(float(item["hz"]), 1) if item else None

    def clear_pending(self) -> None:
        self.candidate_since = None
        self.candidate_hz = None
        self.candidate_zone = None

    def reset_all(self) -> None:
        self.learned.clear()
        self.clear_pending()
        self.last_learning = None

    def export(self) -> dict:
        return {
            key: {"hz": float(v["hz"]), "count": int(v["count"])}
            for key, v in self.learned.items()
        }

    def load(self, raw: object) -> None:
        self.reset_all()
        if not isinstance(raw, dict):
            return
        for zone in ("unknown", "frost", "transition", "mild"):
            item = raw.get(zone)
            if not isinstance(item, dict):
                continue
            try:
                hz = float(item["hz"])
                count = int(item["count"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(hz) and 21.5 <= hz <= 60 and 1 <= count <= 1000:
                self.learned[zone] = {"hz": round(hz, 2), "count": min(count, 12)}

    def observe(
        self, *, now: datetime, observation, actual_hz: float | None,
        target_hz: float, room_target: float, outdoor_temp: float | None,
        allowed: bool,
    ) -> bool:
        """Learn only after sustained near-equilibrium at a stable operating point."""
        room = observation.room_temp
        trend = observation.trend_kph
        zone = self.zone(outdoor_temp)
        valid = (
            allowed
            and room is not None and math.isfinite(float(room))
            and trend is not None and math.isfinite(float(trend))
            and abs(float(room) - room_target) <= 0.4
            and abs(float(trend)) <= 0.06
            and getattr(observation, "window_minutes", 0.0) >= 25
            and actual_hz is not None and math.isfinite(actual_hz)
            and 21.5 <= actual_hz <= 60
            and abs(actual_hz - target_hz) <= 3
        )
        if not valid:
            self.clear_pending()
            return False
        if (
            self.candidate_since is None
            or self.candidate_zone != zone
            or self.candidate_hz is None
            or abs(actual_hz - self.candidate_hz) > 1.0
            or now < self.candidate_since
        ):
            self.candidate_since = now
            self.candidate_hz = actual_hz
            self.candidate_zone = zone
            return False
        if (now - self.candidate_since) < timedelta(minutes=30):
            return False
        if self.last_learning is not None and now >= self.last_learning and (now - self.last_learning) < timedelta(minutes=30):
            return False
        old = self.learned.get(zone)
        hz = round(actual_hz, 2)
        if old:
            count = min(int(old["count"]) + 1, 12)
            hz = round((float(old["hz"]) * (count - 1) + hz) / count, 2)
        else:
            count = 1
        self.learned[zone] = {"hz": hz, "count": count}
        self.last_learning = now
        self.clear_pending()
        return True


class RoomAutoController:
    """Slow, rate-limited room control; defrost and sensor faults always win."""

    def __init__(self) -> None:
        self.target_hz: float | None = None
        self.last_adjust: datetime | None = None
        self.last_guard: datetime | None = None
        self.heat_suppressed = False
        self.decision = AutoDecision()
        self.continuity = ContinuityLearning()
        self.latest_min_duration = 0.0
        self.latest_zone = "unknown"
        self.last_learned = False

    def reset(self) -> None:
        # A mode switch must not discard long-term learned heat-loss values.
        continuity = self.continuity
        self.__init__()
        self.continuity = continuity
        self.continuity.clear_pending()

    def update(
        self, *, now: datetime, observation, running: bool,
        preferred_hz: float, max_hz: float, target_room_temp: float,
        max_overheat_k: float, restart_delta_k: float, observation_window_min: float,
        actual_hz: float | None = None, outdoor_temp: float | None = None,
        min_hz_guard_minutes: float = 0.0,
    ) -> AutoDecision:
        """Return proposed target; never issue physical device commands."""
        if not running:
            self.reset()
            return self.decision

        preferred = max(20.0, min(60.0, float(preferred_hz)))
        ceiling = max(preferred, min(60.0, float(max_hz)))
        self.latest_zone = self.continuity.zone(outdoor_temp)
        self.latest_min_duration = float(getattr(observation, "minutes_at_min_hz", 0.0))
        self.last_learned = False
        if self.target_hz is None or not math.isfinite(self.target_hz):
            learned = self.continuity.learned_hz(outdoor_temp)
            # Learned startup values can move the requested Hz at most +2 Hz.
            self.target_hz = (min(ceiling, preferred + 2, max(preferred, learned))
                              if learned is not None else preferred)
            self.last_adjust = now

        def deliver(state, action, reason, *, remaining=None):
            self.decision = AutoDecision(
                state=state, action=action, reason=reason,
                target_hz=round(self.target_hz, 1),
                next_check_min=(round(max(0.0, remaining), 1)
                                if remaining is not None else None),
                heat_suppressed=self.heat_suppressed,
            )
            return self.decision

        phase = observation.phase
        if phase in ("defrost", "recovery"):
            self.continuity.clear_pending()
            self.last_adjust = now
            return deliver("paused", "hold", f"{phase}: Trend, Hz-Anpassungen und Lernen pausiert.")
        if phase in ("sensor_stale", "sensor_missing") or observation.room_temp is None:
            self.continuity.clear_pending()
            self.last_adjust = now
            return deliver("fault", "blocked", "BT-Raumwert fehlt oder ist zu alt; keine neue Heizanforderung.")
        if phase == "inactive":
            self.continuity.clear_pending()
            self.last_adjust = now
            return deliver("inactive", "hold", "Klimaanlage nicht im Heizbetrieb; keine Einschaltbefehle.")

        room = float(observation.room_temp)
        upper = float(target_room_temp) + float(max_overheat_k)
        lower = float(target_room_temp) - float(restart_delta_k)
        if room >= upper:
            self.continuity.clear_pending()
            self.heat_suppressed = True
            self.last_adjust = now
            return deliver("heat_pause", "reduce_heat_demand", "Überheizungsgrenze erreicht; keine Dauerlauf-Hz erzwingen.")
        if self.heat_suppressed:
            self.continuity.clear_pending()
            if room > lower:
                return deliver("heat_pause", "reduce_heat_demand", "Noch oberhalb der unteren Wiederanlaufreferenz; Heizanforderung bleibt reduziert.")
            self.heat_suppressed = False
            self.target_hz = preferred
            self.last_adjust = now
            return deliver("resuming", "resume_preferred", "Untere Referenz unterschritten; vorsichtig mit bevorzugten Hz neu anfordern.")

        self.last_learned = self.continuity.observe(
            now=now, observation=observation, actual_hz=actual_hz,
            target_hz=self.target_hz, room_target=target_room_temp,
            outdoor_temp=outdoor_temp, allowed=True,
        )

        guard_minutes = max(0.0, min(60.0, float(min_hz_guard_minutes)))
        # Only act on a *measured* 20-Hz dwell; no invented or inferred frequency.
        # Three 1-Hz nudges maximum; never in the last 0.3 K before upper limit.
        guard_ceiling = min(ceiling, preferred + 3.0)
        if (
            guard_minutes > 0
            and self.latest_min_duration >= guard_minutes
            and actual_hz is not None and 19.8 <= actual_hz <= 20.5
            and room < upper - 0.3
            and self.target_hz < guard_ceiling
            and (self.last_guard is None or (now >= self.last_guard and (now - self.last_guard) >= timedelta(minutes=20)))
        ):
            self.target_hz = min(guard_ceiling, self.target_hz + 1.0)
            self.last_guard = now
            self.last_adjust = now
            return deliver("min_modulation_guard", "increase", "20 Hz zu lange erreicht: einmalig +1 Hz (max. +3 Hz über Dauerbetriebswert).")

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
