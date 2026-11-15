"""Deterministische, anlagenunabhaengige Silent-Entscheidungen.

Keine direkten MQTT-, Power-, Setpoint- oder Modus-Befehle.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

DISABLED = "disabled"
ALWAYS = "always_silent"
AUTO = "auto"
NORMAL = "normal"
MODES = (DISABLED, ALWAYS, AUTO, NORMAL)


@dataclass(frozen=True)
class SilentPlan:
    desired: str | None
    state: str
    reason: str
    boost_left_min: float = 0.0


class SilentPolicy:
    """Safe default: no actuator writes until explicitly configured."""

    def __init__(self) -> None:
        self.boost_until: datetime | None = None
        self.auto_cooldown_until: datetime | None = None
        self.boost_source: str | None = None

    def start_manual_boost(self, now: datetime, minutes: int) -> None:
        if not 5 <= minutes <= 120:
            raise ValueError("Boost-Dauer ausserhalb von 5 bis 120 Minuten")
        self.boost_until = now + timedelta(minutes=minutes)
        self.boost_source = "manual"

    def stop_boost(self) -> None:
        self.boost_until = None
        self.boost_source = None

    def cancel_boost(self, now: datetime) -> None:
        """User cancel prevents immediate automatic re-boost."""
        self.stop_boost()
        self.auto_cooldown_until = now + timedelta(minutes=60)

    def decide(
        self, *, now: datetime, mode: str, enabled: bool, heating: bool,
        phase: str, room_temp: float | None, target_temp: float,
        trend_kph: float | None, window_minutes: float,
        observation_minutes: float, target_hz: float | None,
        preferred_hz: float,
    ) -> SilentPlan:
        if mode not in MODES:
            return SilentPlan(None, "error", "Unbekannte Silent-Betriebsart")
        if mode == DISABLED:
            self.stop_boost()
            return SilentPlan(None, "disabled", "Silent-Steuerung deaktiviert; keine Befehle")
        if not enabled or not heating:
            # Do not re-enable any HVAC function if user switched system off.
            self.stop_boost()
            return SilentPlan(None, "inactive", "Hz-Regler oder Heizbetrieb aus; kein Silent-Befehl")
        if phase in ("defrost", "recovery", "sensor_stale", "sensor_missing"):
            return SilentPlan(None, "paused", f"{phase}: Silent-Befehle pausiert")
        if mode == NORMAL:
            self.stop_boost()
            return SilentPlan("off", "normal", "Normale Leistung explizit gewaehlt")

        if self.boost_until is not None and now >= self.boost_until:
            if self.boost_source == "auto":
                self.auto_cooldown_until = now + timedelta(minutes=60)
            self.stop_boost()
        if self.boost_until is not None:
            left = max(0.0, (self.boost_until - now).total_seconds() / 60)
            return SilentPlan("off", "boost", f"{self.boost_source or 'manual'} Boost bis zum Ablauf aktiv", round(left, 1))

        if mode == AUTO:
            # Only permit an automatic boost after measurable sustained underheating;
            # an adaptation is meaningful only with valid long-term measurements.
            usable = room_temp is not None and trend_kph is not None and target_hz is not None
            if usable:
                usable = all(isfinite(float(v)) for v in (room_temp, trend_kph, target_hz))
            cooldown = self.auto_cooldown_until is not None and now < self.auto_cooldown_until
            if (
                usable and not cooldown
                and room_temp <= target_temp - 1.0
                and trend_kph <= 0.03
                and window_minutes >= max(10.0, observation_minutes * 0.5)
                and target_hz >= preferred_hz + 4
            ):
                self.boost_until = now + timedelta(minutes=30)
                self.boost_source = "auto"
                return SilentPlan("off", "boost", "Raum heizt trotz erhoehter Hz zu langsam: 30 min Normalleistung", 30.0)
            if cooldown:
                return SilentPlan("on", "silent", "Auto-Boost-Sperrzeit; Silent beibehalten")
            return SilentPlan("on", "silent", "Bevorzugter ruhiger Silent-Betrieb")
        return SilentPlan("on", "silent", "Silent dauerhaft angefordert")
