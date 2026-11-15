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
            if math.isfinite(hz) and 21.5 <= hz <= 90 and 1 <= count <= 1000:
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
            and 21.5 <= actual_hz <= 90
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
    """Äußerer Raumtemperatur-Regler: Start-Hz != dauerhafte Mindest-Hz.

    Berechnet nur Ziel-Hz. Schaltet weder Gerät noch Klima-Solltemperatur um.
    Begrenzt Änderungen in der Nähe des Sollwerts und setzt während Abtauung aus.
    """

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
        learned = self.continuity
        self.__init__()
        self.continuity = learned
        self.continuity.clear_pending()

    def update(
        self, *, now: datetime, observation, running: bool,
        preferred_hz: float, start_hz: float, max_hz: float,
        target_room_temp: float, max_overheat_k: float, restart_delta_k: float,
        observation_window_min: float, actual_hz: float | None = None,
        outdoor_temp: float | None = None, min_hz_guard_minutes: float = 0.0,
    ) -> AutoDecision:
        if not running:
            self.reset()
            return self.decision

        ceiling = max(20.0, min(90.0, float(max_hz)))
        preferred = min(ceiling, max(20.0, float(preferred_hz)))
        startup = max(preferred, min(ceiling, float(start_hz)))
        self.latest_zone = self.continuity.zone(outdoor_temp)
        self.latest_min_duration = float(getattr(observation, "minutes_at_min_hz", 0.0))
        self.last_learned = False

        def deliver(state: str, action: str, reason: str, *, remaining: float | None = None):
            self.decision = AutoDecision(
                state=state, action=action, reason=reason,
                target_hz=round(self.target_hz, 1) if self.target_hz is not None else None,
                next_check_min=round(max(0.0, remaining), 1) if remaining is not None else None,
                heat_suppressed=self.heat_suppressed,
            )
            return self.decision

        phase = observation.phase
        if phase in ("defrost", "recovery"):
            self.continuity.clear_pending()
            self.last_adjust = now
            return deliver("paused", "hold", "Abtauung/Nachlauf: keine Anpassung oder Lernwerte.")
        if phase in ("sensor_stale", "sensor_missing") or observation.room_temp is None:
            self.continuity.clear_pending()
            self.last_adjust = now
            return deliver("fault", "blocked", "Raumtemperatur fehlt oder ist veraltet.")
        if phase == "inactive":
            self.continuity.clear_pending()
            self.last_adjust = now
            return deliver("inactive", "hold", "Klimaanlage heizt nicht: keine Einschaltanforderung.")

        room = float(observation.room_temp)
        upper = float(target_room_temp) + float(max_overheat_k)
        lower = float(target_room_temp) - float(restart_delta_k)
        if room >= upper:
            self.continuity.clear_pending()
            self.heat_suppressed = True
            self.last_adjust = now
            return deliver("heat_pause", "reduce_heat_demand", "Obergrenze erreicht: Wärmeanforderung reduzieren.")
        if phase == "sensor_unchanged":
            # Preserve last Hz and any active heat-suppression latch. Still
            # allow the upper temperature boundary above to take precedence.
            # Do not restart heating or accumulate 20-Hz/learning evidence.
            self.continuity.clear_pending()
            self.last_adjust = now
            if self.heat_suppressed:
                return deliver("heat_pause", "reduce_heat_demand",
                               "Keine neue BT-Meldung: bestehende Heizpause beibehalten.")
            return deliver("sensor_unchanged", "hold",
                           "Kein neues BT-Temperaturereignis: Ziel-Hz beibehalten, "
                           "keine Lernwerte oder 20-Hz-Anhebung.")
        if self.heat_suppressed:
            self.continuity.clear_pending()
            if room > lower:
                return deliver("heat_pause", "reduce_heat_demand", "Warte auf untere Hysteresegrenze.")
            self.heat_suppressed = False
            self.target_hz = preferred
            self.last_adjust = now
            return deliver("resuming", "resume_preferred", "Unterhalb Wiederanlaufreferenz: langsam erneut Wärme anfordern.")

        # Startfrequenz nur bei deutlichem Temperaturdefizit verwenden.
        if self.target_hz is None or not math.isfinite(self.target_hz):
            gap = target_room_temp - room
            self.target_hz = startup if gap >= 0.8 else preferred
            self.last_adjust = now
            return deliver("starting", "hold", "Start-Hz für kalten Raum gesetzt; erst Temperaturtrend sammeln.")
        self.target_hz = max(preferred, min(ceiling, self.target_hz))

        self.last_learned = self.continuity.observe(
            now=now, observation=observation, actual_hz=actual_hz,
            target_hz=self.target_hz, room_target=target_room_temp,
            outdoor_temp=outdoor_temp, allowed=True,
        )
        guard_minutes = max(0.0, min(60.0, float(min_hz_guard_minutes)))
        guard_ceiling = min(ceiling, preferred + 3)
        if (
            guard_minutes > 0 and self.latest_min_duration >= guard_minutes
            and actual_hz is not None and 19.8 <= actual_hz <= 20.5
            and room < upper - 0.3 and self.target_hz < guard_ceiling
            and (self.last_guard is None or
                 now - self.last_guard >= timedelta(minutes=20))
        ):
            self.target_hz = min(guard_ceiling, self.target_hz + 1)
            self.last_guard = now
            self.last_adjust = now
            return deliver("min_modulation_guard", "increase", "20-Hz-Schutz: +1 Hz, begrenzt auf Dauerwert +3 Hz.")

        near = room >= target_room_temp - 0.7
        interval = max(15.0, min(120.0, float(observation_window_min) * (2 if near else 1)))
        if self.last_adjust is None or now < self.last_adjust:
            self.last_adjust = now
        elapsed = (now - self.last_adjust).total_seconds() / 60.0
        if elapsed < interval:
            return deliver("monitoring", "hold", "Temperaturtrend wird beobachtet.", remaining=interval - elapsed)

        trend = observation.trend_kph
        if trend is None or not math.isfinite(float(trend)):
            return deliver("collecting", "hold", "Noch kein gültiger Raumtemperaturtrend.", remaining=5)
        old = self.target_hz
        gap = target_room_temp - room
        reason = "Temperaturentwicklung passt; Ziel-Hz beibehalten."
        if gap <= 0:
            step_down = 4 if trend > 0.20 else 2
            self.target_hz = max(preferred, old - step_down)
            reason = f"Zieltemperatur erreicht: {step_down} Hz vorsichtig reduzieren."
        elif near:
            if trend > 0.10:
                self.target_hz = max(preferred, old - (3 if trend > 0.25 else 2))
                reason = "Nahe Ziel, Temperatur steigt: Leistung vorzeitig reduzieren."
            elif trend < -0.03:
                self.target_hz = min(ceiling, old + 1)
                reason = "Nahe Ziel, Raum kühlt aus: +1 Hz."
        elif gap >= 0.8:
            if trend < 0.04:
                self.target_hz = min(ceiling, old + (4 if gap >= 1.5 else 2))
                reason = "Deutlich unter Ziel, Aufheizung zu langsam: Leistung moderat erhöhen."
            elif trend > 0.35:
                self.target_hz = max(preferred, old - 2)
                reason = "Raum erwärmt sich schnell: -2 Hz gegen Überschwingen."
        self.last_adjust = now
        if self.target_hz > old:
            action = "increase"
        elif self.target_hz < old:
            action = "decrease"
        else:
            action = "hold"
        return deliver("regulating", action, reason)
