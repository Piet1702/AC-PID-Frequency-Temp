"""Rein beobachtende Raumtemperatur-Auswertung (keine Aktoren / Soll-Hz-Schreibzugriffe).

Auswertung erfolgt nur mit frischen Raumthermometer-Reports während eines
ununterbrochenen Heizfensters. Abtauung und anschließende Erholungszeit werden
vollständig aus der Temperaturtrend-Berechnung ausgeschlossen.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta


PHYSICAL_MIN_HZ = 20.0  # MHI-Anlagenannahme des Anwenders, nur Diagnose in 2.4.1.4
DEFROST_RECOVERY_MIN = 10


@dataclass(frozen=True)
class RoomObservation:
    phase: str = "collecting"
    advice: str = "wait_data"
    reason: str = "Noch keine ausreichenden Messdaten vorhanden."
    room_temp: float | None = None
    delta_k: float | None = None
    trend_kph: float | None = None
    samples: int = 0
    window_minutes: float = 0.0
    minutes_at_min_hz: float = 0.0
    input_age_seconds: float | None = None
    recovery_seconds: float = 0.0


class RoomObserver:
    """Trend und Diagnose ohne Regelbefehle; Verlauf wird nur im RAM gehalten."""

    def __init__(self) -> None:
        self.samples: deque[tuple[datetime, float]] = deque(maxlen=4096)
        self.last_report: datetime | None = None
        self.had_defrost = False
        self.recover_until: datetime | None = None
        self.at_min_since: datetime | None = None
        self.snapshot = RoomObservation()

    def _pause(self, phase: str, advice: str, reason: str, *,
               age: float | None = None, recovery: float = 0) -> RoomObservation:
        self.samples.clear()
        self.last_report = None
        self.at_min_since = None
        self.snapshot = RoomObservation(
            phase=phase, advice=advice, reason=reason,
            input_age_seconds=age, recovery_seconds=max(0, recovery),
        )
        return self.snapshot

    def update(
        self, *, now: datetime, room_temp: float | None, report_at: datetime | None,
        sensor_status: str, age_seconds: float | None, heating: bool, defrost: bool,
        actual_hz: float | None, target_temp: float, preferred_hz: float,
        max_overheat_k: float, restart_delta_k: float, window_min: float,
    ) -> RoomObservation:
        if defrost:
            self.had_defrost = True
            self.recover_until = None
            return self._pause("defrost", "paused", "Abtauung aktiv: Temperaturtrend und Lernen pausieren.", age=age_seconds)
        if self.had_defrost:
            self.had_defrost = False
            self.recover_until = now + timedelta(minutes=DEFROST_RECOVERY_MIN)
        if self.recover_until is not None:
            remaining = (self.recover_until - now).total_seconds()
            if remaining > 0:
                return self._pause("recovery", "paused", "Erholungsphase nach Abtauung: Messfenster zurückgesetzt.", age=age_seconds, recovery=remaining)
            self.recover_until = None
        if sensor_status not in ("ok", "unchanged") or room_temp is None or report_at is None:
            phase = "sensor_stale" if sensor_status == "stale" else "sensor_missing"
            return self._pause(phase, "paused", f"Raumsensor nicht auswertbar: {sensor_status}.", age=age_seconds)
        if not heating:
            return self._pause("inactive", "paused", "Anlage nicht im Heizbetrieb; keine Heizungstrends berechnen.", age=age_seconds)

        if sensor_status == "ok" and (self.last_report is None or report_at > self.last_report):
            self.samples.append((report_at, float(room_temp)))
            self.last_report = report_at
        # Bei Zeitrücksprung alte Messreihe verwerfen.
        elif sensor_status == "ok" and report_at < self.last_report:
            self.samples.clear()
            self.samples.append((report_at, float(room_temp)))
            self.last_report = report_at

        # Ein älterer Referenzpunkt bleibt erhalten, damit die Steigung exakt
        # über das konfigurierbare Fenster ermittelt werden kann.
        cutoff = now - timedelta(minutes=float(window_min))
        while len(self.samples) > 2 and self.samples[1][0] < cutoff:
            self.samples.popleft()
        window = [x for x in self.samples if x[0] >= cutoff]
        if window and self.samples and self.samples[0][0] < cutoff:
            window.insert(0, self.samples[0])
        if len(window) >= 2:
            elapsed_min = (window[-1][0] - window[0][0]).total_seconds() / 60.0
        else:
            elapsed_min = 0.0
        trend: float | None = None
        # Nicht aus einzelnen Sprüngen eine scheinbar präzise Stundenrate ableiten.
        if elapsed_min >= max(10.0, float(window_min) * 0.5):
            trend = round((window[-1][1] - window[0][1]) * 60.0 / elapsed_min, 3)

        if actual_hz is not None and PHYSICAL_MIN_HZ - 0.2 <= actual_hz <= PHYSICAL_MIN_HZ + 0.5:
            if self.at_min_since is None:
                self.at_min_since = now
        else:
            self.at_min_since = None
        min_minutes = ((now - self.at_min_since).total_seconds() / 60.0
                       if self.at_min_since else 0.0)

        delta = round(float(target_temp) - float(room_temp), 2)
        upper = float(target_temp) + float(max_overheat_k)
        lower = float(target_temp) - float(restart_delta_k)
        if sensor_status == "unchanged":
            # Keep the real value available (also for MQTT); never manufacture a
            # zero-degree-per-hour slope from absence of change-only BLE packets.
            # Kein neuer BLE-Report: keine neue Trendinformation erfinden.
            # Echte, zuvor gemessene Stichproben fuer die naechste Meldung
            # erhalten; bei Abtauung/Heizstopp wird wie bisher geloescht.
            self.at_min_since = None
            self.snapshot = RoomObservation(
                phase="sensor_unchanged", advice="hold",
                reason="Noch gueltiger Zahlenwert, aber keine neue BT-Meldung: "
                       "Hz beibehalten, keine Trend-/Lernentscheidung.",
                room_temp=float(room_temp), delta_k=delta, trend_kph=None,
                samples=0, window_minutes=0.0, minutes_at_min_hz=0.0,
                input_age_seconds=age_seconds,
            )
            return self.snapshot
        if float(room_temp) >= upper:
            phase, advice = "above_limit", "reduce_slowly"
            reason = "Erlaubte Überheizungsgrenze erreicht; später Wärmeanforderung reduzieren, ohne MQTT-Powerbefehl."
        elif float(room_temp) >= target_temp:
            phase, advice = "tolerance", "prefer_continuous"
            reason = f"Zieltemperatur erreicht; niedrigen Dauerbetrieb um {preferred_hz:.0f} Hz prüfen."
        elif float(room_temp) < lower:
            phase = "below_restart"
            if trend is None:
                advice = "wait_data"
                reason = "Deutlich unter Ziel; erst gültiges Messfenster sammeln."
            elif trend < 0.05:
                advice = "increase_slowly"
                reason = "Raumtemperatur steigt zu langsam bzw. sinkt; spätere vorsichtige Hz-Erhöhung prüfen."
            elif trend > 0.3:
                advice = "reduce_slowly"
                reason = "Raum erwärmt sich schnell; spätere vorsichtige Hz-Reduzierung prüfen."
            else:
                advice = "hold"
                reason = "Raum erwärmt sich moderat; den Arbeitspunkt zunächst halten."
        else:
            phase = "approaching"
            if trend is None:
                advice, reason = "wait_data", "Nahe am Ziel; noch kein ausreichend langes Messfenster."
            elif trend > 0.12:
                advice, reason = "reduce_slowly", "Nahe am Ziel bei steigendem Trend; später frühzeitig drosseln."
            else:
                advice, reason = "hold", "Nahe am Ziel bei geringem Trend; Arbeitspunkt halten."

        self.snapshot = RoomObservation(
            phase=phase, advice=advice, reason=reason, room_temp=float(room_temp),
            delta_k=delta, trend_kph=trend, samples=len(window),
            window_minutes=round(elapsed_min, 1),
            minutes_at_min_hz=round(min_minutes, 1),
            input_age_seconds=age_seconds,
        )
        return self.snapshot
