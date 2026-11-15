"""Controller: verbindet den Regelkern mit Home Assistant.

* liest Soll-Temperatur (Master-Climate) und Kompressor-Hz,
* liest optional Außentemperatur, echten Raumtemperatursensor und Abtaustatus,
* rechnet im eingestellten Takt einen Regelschritt,
* stellt das Ergebnis als Sensorwert bereit (Entitäten holen es sich vom Controller),
* speichert gelernten Arbeitspunkt, Mindestmodulation, Reaktionszeiten und Einstellungen über Neustarts hinweg.

Fehlerverhalten: Fehlen Eingangsdaten, wird der letzte Wert zunächst gehalten
(Status ``waiting``). Dauert das länger als ``fault_timeout_min``, wird der Sensor
``unavailable`` (Status ``fault``) und die Anlage fällt auf ihren eigenen Innensensor
zurück.

Durchreichen (Passthrough): Ist der Regler aus oder die Anlage nicht im Heizbetrieb und ist
ein echter Raumtemperatursensor konfiguriert, der einen gültigen Wert liefert, gibt der
erzeugte Sensor dessen Wert 1:1 weiter (Offset 0,0 K) und folgt jeder Änderung sofort. So
rechnet die Anlage weiter mit dem echten Raumthermometer statt mit ihrem Deckensensor. Nur
wenn auch dieser Wert fehlt (oder gar kein Raumsensor konfiguriert ist), wird der Sensor
``unavailable``.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLIMATE,
    CONF_DEFROST,
    CONF_FAULT_TIMEOUT,
    CONF_FREQUENCY,
    CONF_INTERVAL,
    CONF_MAX_OFFSET,
    CONF_MQTT_INTERVAL,
    CONF_MAX_ROOM_OVERHEAT,
    CONF_OUTDOOR_TEMP,
    CONF_PROBE_INTERVAL,
    CONF_ROOM_TEMP,
    CONF_WEATHER_TRIGGER_DELTA,
    DEFAULT_TARGET_HZ,
    DOMAIN,
    SILENT_DEFAULTS,
    HVAC_MODE_ACTIVE,
    STATUS_FAULT,
    STATUS_IDLE,
    STATUS_OFF,
    STATUS_WAITING,
    STORAGE_VERSION,
    TARGET_HZ_MAX,
    TARGET_HZ_MIN,
    MQTT_DEFAULTS,
    TUNING_DEFAULTS,
)
from .regelung import Params, State, round1, step
from .room_observer import RoomObserver
from .room_auto import RoomAutoController
from .heating_policy import apply_heating_demand_ceiling
from .mqtt_cadence import MqttCadence
from .silent_bridge import ProtoArtSilentBridge
from .protoart_mqtt import room_sensor_snapshot
from .const import (
    ROOM_DEFAULTS, CONF_CONTROL_MODE, MODE_ROOM_OBSERVE, CONF_ROOM_TARGET,
    CONF_PREFERRED_HZ, CONF_ROOM_OVERHEAT_DELTA, CONF_ROOM_RESTART_DELTA,
    CONF_ROOM_OBSERVE_WINDOW, CONF_ROOM_STALE, MQTT_DEFAULTS,
    MODE_ROOM_AUTO, CONF_ROOM_MAX_HZ, CONF_MAX_OFFSET, STATUS_ROOM_HEAT_PAUSE,
    CONF_ROOM_MIN_HZ_GUARD, CONF_ROOM_START_HZ,
)
from .protoart_mqtt import ProtoArtMqttBridge
from .automation_mqtt import AutomationMqttMonitor
from .bt_heartbeat import ProtoArtBtMonitor

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY_S = 30


def _to_float(value: Any) -> float | None:
    """Zahl aus Zustand/Attribut lesen; ``unavailable``/``unknown``/Müll -> None."""
    if value is None or value in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class AcPidFrequencyController:
    """Hält Zustand und Zeitgeber von AC PID Frequency Temp (ein Config-Entry)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._unsubs: list = []
        self._fault_since: datetime | None = None

        self.signal = f"{DOMAIN}_update_{entry.entry_id}"
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Eigenbau",
            model="AC PID Frequency Temp",
        )

        # Regelkern-Zustand (inkl. gelernter Werte)
        self.regelung = State()
        self.mqtt_bridge = ProtoArtMqttBridge(self)
        self.automation_mqtt = AutomationMqttMonitor(self)
        self.bt_monitor = ProtoArtBtMonitor(self)
        self.mqtt_cadence = MqttCadence()
        self._last_options = dict(entry.options)
        self.room_observer = RoomObserver()
        self.room_auto = RoomAutoController()
        self.silent_bridge = ProtoArtSilentBridge(self)

        # Vom Nutzer einstellbar (per Entität), werden gespeichert
        self.enabled = False
        self.target_hz: float = float(DEFAULT_TARGET_HZ)
        self.heat_demand_guard_active = False
        self.heating_simulated_ceiling_c: float | None = None

        # Ergebnis des letzten Taktes (für die Entitäten)
        self.status = STATUS_OFF
        self.available = False
        self.output: float | None = None
        self.offset: float | None = None
        self.error_hz: float | None = None
        self.passthrough = False  # True: Sensor spiegelt gerade die echte Raumtemperatur

    # ------------------------------------------------------------------ Konfiguration
    @property
    def config(self) -> dict[str, Any]:
        """Setup-Daten, überschrieben von den Optionen, mit Standardwerten dahinter."""
        return {**TUNING_DEFAULTS, **MQTT_DEFAULTS, **ROOM_DEFAULTS, **SILENT_DEFAULTS, **self.entry.data, **self.entry.options}

    @property
    def params(self) -> Params:
        c = self.config
        return Params(
            interval_s=float(c[CONF_INTERVAL]),
            max_offset=float(c[CONF_MAX_OFFSET]),
            max_room_overheat=float(c[CONF_MAX_ROOM_OVERHEAT]),
            weather_trigger_delta_k=float(c.get(CONF_WEATHER_TRIGGER_DELTA, 5.0)),
            probe_interval_min=float(c.get(CONF_PROBE_INTERVAL, 240.0)),
        )

    # ------------------------------------------------------------------ Lebenszyklus
    async def async_load(self) -> None:
        """Gespeicherten Zustand laden."""
        data = await self._store.async_load() or {}
        self.enabled = bool(data.get("enabled", False))
        if self.config[CONF_CONTROL_MODE] in (MODE_ROOM_OBSERVE, MODE_ROOM_AUTO):
            self.enabled = False  # Im Beobachtungsmodus niemals automatisch Hz regeln
        target = _to_float(data.get("target_hz"))
        output = _to_float(data.get("output"))
        if target is not None:
            self.target_hz = min(max(target, TARGET_HZ_MIN), TARGET_HZ_MAX)
        self.regelung.output = output
        self.regelung.load_learned_data(data)
        self.room_auto.continuity.load(data.get("room_continuity_learning"))

    @callback
    def async_start(self) -> None:
        """Zeitgeber und Beobachter starten, sofort einen ersten Takt rechnen."""
        cfg = self.config
        interval = timedelta(seconds=max(5.0, float(cfg[CONF_INTERVAL])))
        self._unsubs.append(async_track_time_interval(self.hass, self._handle_tick, interval))
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [cfg[CONF_CLIMATE]], self._handle_climate_change
            )
        )
        if cfg.get(CONF_ROOM_TEMP):
            # Echte Raumtemperatur sofort durchreichen, ohne auf den nächsten Takt zu warten
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [cfg[CONF_ROOM_TEMP]], self._handle_room_change
                )
            )
        self._tick()
        # 1-s-Prüftakt, Veröffentlichung nur zur konfigurierten Fälligkeit.
        # Der erste Publish startet sofort; keine 30-s-Diagnose-Startverzögerung.
        self._unsubs.append(async_track_time_interval(
            self.hass, self._handle_mqtt_diag_tick, timedelta(seconds=1),
        ))
        self._handle_mqtt_diag_tick(None)
        self._unsubs.append(async_track_time_interval(
            self.hass, self._handle_silent_tick, timedelta(seconds=30),
        ))
        self._handle_silent_tick(None)
        self.hass.async_create_task(self.automation_mqtt.async_refresh())
        self.hass.async_create_task(self.bt_monitor.async_start())


    async def async_shutdown(self) -> None:
        """Zeitgeber stoppen und Zustand sichern."""
        self.mqtt_bridge.stop()
        await self.silent_bridge.async_stop()
        await self.automation_mqtt.async_stop()
        await self.bt_monitor.async_stop()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data_to_save())

    async def async_remove_storage(self) -> None:
        await self._store.async_remove()

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "target_hz": self.target_hz,
            "output": self.regelung.output,
            **self.regelung.export_learned_data(),
            "room_continuity_learning": self.room_auto.continuity.export(),
        }

    # ------------------------------------------------------------------ Bedienung
    @callback
    def async_set_enabled(self, enabled: bool) -> None:
        if bool(enabled) != self.enabled:
            self.room_auto.reset()
        self.enabled = enabled
        self._tick()

    @callback
    def async_set_target_hz(self, value: float) -> None:
        self.target_hz = float(min(max(value, TARGET_HZ_MIN), TARGET_HZ_MAX))
        self._publish()

    @callback
    def async_reset_learning(self) -> None:
        """Setzt die gelernte Arbeitspunkt-Tabelle und Anlageneigenschaften auf Werkseinstellungen zurück."""
        self.regelung.reset_learning()
        self.room_auto.continuity.reset_all()
        self._publish()

    @callback
    def async_reset_min_hz(self) -> None:
        """Setzt die gelernte Mindestmodulation auf die Werkseinstellungen zurück."""
        self.regelung.reset_min_hz()
        self._publish()

    # ------------------------------------------------------------------ Takt
    @callback
    def _handle_silent_tick(self, _now: datetime | None) -> None:
        """Silent-Zustand pruefen, unabhaengig vom Temperatur-MQTT-Takt."""
        self.hass.async_create_task(self.silent_bridge.async_tick())

    @callback
    def _handle_mqtt_diag_tick(self, _now: datetime | None) -> None:
        """MQTT-Heartbeat: unabhängig vom Hz-Takt und von UI-Konfigurationsänderungen."""
        cfg = self.config
        self.automation_mqtt.tick()
        if self.mqtt_cadence.should_send(
            dt_util.utcnow(), enabled=self.mqtt_bridge.enabled,
            interval=float(cfg.get(CONF_MQTT_INTERVAL, 5)),
        ):
            self.hass.async_create_task(self.mqtt_bridge.async_tick())
        elif not self.mqtt_bridge.enabled and self.mqtt_bridge.state != "disabled":
            self.hass.async_create_task(self.mqtt_bridge.async_tick())

    @callback
    def _handle_tick(self, _now: datetime) -> None:
        self._tick()

    @callback
    def _handle_climate_change(self, event: Event[EventStateChangedData]) -> None:
        """Beim Wechsel in/aus dem Heizbetrieb sofort reagieren statt auf den Takt zu warten."""
        old, new = event.data["old_state"], event.data["new_state"]
        was_active = old is not None and old.state == HVAC_MODE_ACTIVE
        is_active = new is not None and new.state == HVAC_MODE_ACTIVE
        if was_active != is_active:
            self._tick()

    @callback
    def _handle_room_change(self, event: Event[EventStateChangedData]) -> None:
        """Raumtemperatur geändert: im Durchreich-Betrieb sofort nachziehen."""
        if self.status in (STATUS_OFF, STATUS_IDLE):
            self._tick()

    def room_input_snapshot(self):
        """Numerischer HA-Wert + separates BT-Kontakt-Signal.

        Ein MQTT-Last-Reset aktualisiert nur den glaubhaften Messzeitpunkt,
        niemals künstlich einen HA-State. Ohne Reset zuerst sicher halten und
        nach dem einstellbaren Timeout abbrechen.
        """
        cfg = self.config
        room_id = cfg.get(CONF_ROOM_TEMP)
        status, ha_age, ha_report = room_sensor_snapshot(
            self.hass, room_id, float(cfg[CONF_ROOM_STALE]))
        if status not in ("ok", "unchanged"):
            return status, ha_age, ha_report
        bt_state = self.bt_monitor.state()
        if bt_state == "confirmed":
            contact = self.bt_monitor.tracker.contact_at
            return "ok", self.bt_monitor.tracker.contact_age(dt_util.utcnow()), contact
        if bt_state == "timeout":
            return "stale", self.bt_monitor.timeout_seconds() + 1, ha_report
        if bt_state == "waiting":
            return "unchanged", ha_age, ha_report
        # Kein erkennbares ProtoART-Topic bzw. kein MQTT: alte sichere Regel.
        return status, ha_age, ha_report

    def _update_room_observer(self) -> None:
        """Raumtrend nur aus bestaetigten BT-Kontakten ableiten."""
        cfg = self.config
        room_id = cfg.get(CONF_ROOM_TEMP)
        sensor_status, sensor_age, report_at = self.room_input_snapshot()
        room_state = self.hass.states.get(room_id) if room_id else None
        room_temp = (
            _to_float(room_state.state)
            if room_state is not None and sensor_status in ("ok", "unchanged") else None
        )
        climate = self.hass.states.get(cfg[CONF_CLIMATE])
        heating = climate is not None and climate.state == HVAC_MODE_ACTIVE
        hz_state = self.hass.states.get(cfg[CONF_FREQUENCY])
        actual_hz = _to_float(hz_state.state) if hz_state is not None else None
        self.room_observer.update(
            now=dt_util.utcnow(), room_temp=room_temp, report_at=report_at,
            sensor_status=sensor_status, age_seconds=sensor_age,
            heating=heating, defrost=self._read_defrost(climate),
            actual_hz=actual_hz,
            target_temp=float(cfg[CONF_ROOM_TARGET]),
            preferred_hz=float(cfg[CONF_PREFERRED_HZ]),
            max_overheat_k=float(cfg[CONF_ROOM_OVERHEAT_DELTA]),
            restart_delta_k=float(cfg[CONF_ROOM_RESTART_DELTA]),
            window_min=float(cfg[CONF_ROOM_OBSERVE_WINDOW]),
        )

    def _update_room_auto(self) -> None:
        """Nur Ziel-Hz berechnen; keine Power- oder Climate-Befehle ausgeben."""
        cfg = self.config
        if cfg[CONF_CONTROL_MODE] != MODE_ROOM_AUTO:
            self.room_auto.reset()
            return
        outside = None
        if cfg.get(CONF_OUTDOOR_TEMP):
            outside_state = self.hass.states.get(cfg[CONF_OUTDOOR_TEMP])
            if outside_state is not None:
                outside = _to_float(outside_state.state)
                if outside is None:
                    outside = _to_float(outside_state.attributes.get("temperature"))
        decision = self.room_auto.update(
            now=dt_util.utcnow(), observation=self.room_observer.snapshot,
            running=self.enabled,
            preferred_hz=float(cfg[CONF_PREFERRED_HZ]),
            start_hz=float(cfg[CONF_ROOM_START_HZ]),
            max_hz=float(cfg[CONF_ROOM_MAX_HZ]),
            target_room_temp=float(cfg[CONF_ROOM_TARGET]),
            max_overheat_k=float(cfg[CONF_ROOM_OVERHEAT_DELTA]),
            restart_delta_k=float(cfg[CONF_ROOM_RESTART_DELTA]),
            observation_window_min=float(cfg[CONF_ROOM_OBSERVE_WINDOW]),
            actual_hz=(
                _to_float(freq_state.state)
                if (freq_state := self.hass.states.get(cfg[CONF_FREQUENCY])) is not None
                else None
            ),
            outdoor_temp=outside,
            min_hz_guard_minutes=float(cfg[CONF_ROOM_MIN_HZ_GUARD]),
        )
        if self.enabled and decision.target_hz is not None:
            self.target_hz = decision.target_hz

    @callback
    def _tick(self) -> None:
        self._update_room_observer()
        self._update_room_auto()
        self._evaluate()
        self._publish()

    @callback
    def _publish(self) -> None:
        """Entitäten benachrichtigen und Zustand verzögert speichern."""
        async_dispatcher_send(self.hass, self.signal)
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY_S)

    def _evaluate(self) -> None:
        """Einen Regelschritt rechnen (oder den Fehlerfall behandeln)."""
        cfg = self.config

        if cfg[CONF_CONTROL_MODE] == MODE_ROOM_OBSERVE:
            self._evaluate_disabled()  # Beobachtung bleibt vollständig passiv
            return
        if cfg[CONF_CONTROL_MODE] == MODE_ROOM_AUTO and self.enabled:
            decision = self.room_auto.decision
            if decision.state == "fault":
                # Keine veralteten/simulierten Werte an die Klimaanlage weitergeben.
                self._set_inactive(STATUS_FAULT)
                return
            if decision.state == "paused":
                # Kein Regeleingriff während Abtauung und 10 Min Erholung.
                self.regelung.was_defrosting = True
                self.regelung.hz_prev1 = self.regelung.hz_prev2 = None
                if self.output is None or not self.available:
                    self._set_inactive(STATUS_WAITING)
                else:
                    self.status = STATUS_WAITING
                return
            if decision.state == "sensor_unchanged" and not decision.heat_suppressed:
                # Ohne neue BT-Messung auch den INNEREN PID anhalten! Sonst
                # kann er die simulierte Temperatur weiter anheben und die
                # Heizleistung senken, obwohl das Raumziel noch nicht erreicht ist.
                if self.available and self.output is not None:
                    self.status = "hold"
                    return
            if decision.heat_suppressed:
                # Thermische Hysterese ohne MQTT-Powerbefehl: Heizbedarf herunterfahren.
                climate_state = self.hass.states.get(cfg[CONF_CLIMATE])
                if climate_state is None or climate_state.state != HVAC_MODE_ACTIVE:
                    self._set_passive(STATUS_IDLE)
                    return
                climate_target = _to_float(climate_state.attributes.get("temperature"))
                if climate_target is None:
                    self._set_inactive(STATUS_FAULT)
                    return
                delta = min(0.3, max(0.0, float(cfg[CONF_MAX_OFFSET])))
                self.output = round1(climate_target + delta)
                self.regelung.output = self.output
                self.regelung.last_running_hz = None
                self.regelung.hz_prev1 = self.regelung.hz_prev2 = None
                self.passthrough = False
                self.available = True
                self.offset = -delta
                self.error_hz = None
                self.status = STATUS_ROOM_HEAT_PAUSE
                return
        if not self.enabled:
            self._evaluate_disabled()
            return

        climate = self.hass.states.get(cfg[CONF_CLIMATE])
        climate_ok = climate is not None and climate.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )
        if climate_ok and climate.state != HVAC_MODE_ACTIVE:
            # Anlage aus / kühlt / ... -> echte Raumtemperatur durchreichen (falls vorhanden),
            # sonst Sensor sofort weg, die Anlage nutzt ihren eigenen
            self._set_passive(STATUS_IDLE)
            return

        setpoint = _to_float(climate.attributes.get("temperature")) if climate_ok else None
        freq = self.hass.states.get(cfg[CONF_FREQUENCY])
        hz = _to_float(freq.state) if freq is not None else None
        if setpoint is None or hz is None:
            self._handle_missing_data()
            return

        # Optionale Eingangsgrößen lesen
        outdoor_temp = self._read_outdoor()

        room_temp = self._configured_room_temp()
        if room_temp is None and not cfg.get(CONF_ROOM_TEMP) and climate_ok:
            room_temp = _to_float(climate.attributes.get("current_temperature"))

        defrost = self._read_defrost(climate if climate_ok else None)

        self._fault_since = None
        previous_simulated_output = (self.output if self.output is not None
                                     else self.regelung.output)
        result = step(
            self.params,
            self.regelung,
            setpoint,
            hz,
            self.target_hz,
            outdoor_temp=outdoor_temp,
            room_temp=room_temp,
            defrost=defrost,
            automatic_target=(cfg[CONF_CONTROL_MODE] == MODE_ROOM_AUTO),
            overheat_limit_temp=(
                float(cfg[CONF_ROOM_TARGET]) + float(cfg[CONF_ROOM_OVERHEAT_DELTA])
                if cfg[CONF_CONTROL_MODE] == MODE_ROOM_AUTO else None
            ),
        )
        self.available = True
        self.passthrough = False
        self.output = result.published
        self.offset = result.offset
        self.error_hz = result.error_hz
        self.status = result.mode
        self.heat_demand_guard_active = False
        self.heating_simulated_ceiling_c = None
        if cfg[CONF_CONTROL_MODE] == MODE_ROOM_AUTO and self.enabled:
            phase = self.room_observer.snapshot.phase
            # Nur bei wirklich verwertbarem BLE-Wert. Sensor_unchanged
            # wird oberhalb bereits ohne neue innere Schritte gehalten.
            if phase not in ("sensor_unchanged", "sensor_missing", "sensor_stale",
                             "defrost", "recovery", "inactive"):
                corrected, active, cap = apply_heating_demand_ceiling(
                    output=self.output, previous_output=previous_simulated_output,
                    climate_setpoint=setpoint, real_room_temp=room_temp,
                    room_target=float(cfg[CONF_ROOM_TARGET]), actual_hz=hz,
                    maximum_hz=float(cfg[CONF_ROOM_MAX_HZ]),
                    max_offset=float(cfg[CONF_MAX_OFFSET]),
                )
                if active:
                    self.output = corrected
                    self.regelung.output = corrected
                    self.offset = round(setpoint - corrected, 2)
                    self.heat_demand_guard_active = True
                    self.heating_simulated_ceiling_c = cap
                    if corrected < result.published:
                        self.status = "raise"
        _LOGGER.debug(
            "Takt: soll=%.1f hz=%.1f ziel=%.0f (eff=%.1f min=%.1f) -> %s, sensor=%.1f (offset %.2f, gelernt %.2f K [%s/%s])",
            setpoint,
            hz,
            self.target_hz,
            result.effective_target_hz,
            result.learned_min_hz,
            result.mode,
            result.published,
            result.offset,
            result.learned_offset,
            result.outdoor_bin,
            result.freq_bin,
        )

    def _read_outdoor(self) -> float | None:
        """Außentemperatur (Sensor oder weather-Entität), None wenn nicht verfügbar."""
        outdoor_ent = self.config.get(CONF_OUTDOOR_TEMP)
        if not outdoor_ent:
            return None
        out_state = self.hass.states.get(outdoor_ent)
        if out_state is None or out_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        if out_state.domain == "weather":
            return _to_float(out_state.attributes.get("temperature"))
        return _to_float(out_state.state)

    def _read_defrost(self, climate: Any) -> bool:
        """Abtauen aktiv? Eigener Abtau-Sensor, sonst hvac_action der Klimaanlage."""
        defrost_ent = self.config.get(CONF_DEFROST)
        if defrost_ent:
            def_state = self.hass.states.get(defrost_ent)
            if def_state is not None and def_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                return def_state.state.lower() in ("on", "true", "defrost", "defrosting")
            return False
        if climate is not None:
            action = str(climate.attributes.get("hvac_action") or "").lower()
            return action in ("defrosting", "preheating")
        return False

    def _evaluate_disabled(self) -> None:
        """Regler aus: echte Raumtemperatur sauber durchreichen."""
        self._set_passive(STATUS_OFF)

    def _configured_room_temp(self) -> float | None:
        """Wert des konfigurierten echten Raumtemperatursensors (None, wenn keiner/ungültig)."""
        entity_id = self.config.get(CONF_ROOM_TEMP)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        return _to_float(state.state) if state is not None else None

    def _set_passive(self, status: str) -> None:
        """Nicht regeln: echte Raumtemperatur durchreichen oder (ohne sie) unavailable."""
        self._set_inactive(status)
        room_temp = self._configured_room_temp()
        if room_temp is not None:
            self.available = True
            self.passthrough = True
            self.output = round1(room_temp)
            self.offset = 0.0

    def _set_inactive(self, status: str) -> None:
        self.passthrough = False
        self.available = False
        self.output = self.offset = self.error_hz = None
        self.status = status
        self._fault_since = None
        self.regelung.hz_prev1 = self.regelung.hz_prev2 = None

    def _handle_missing_data(self) -> None:
        """Eingangsdaten fehlen: erst Wert halten, nach Zeitlimit unavailable."""
        now = dt_util.utcnow()
        if self._fault_since is None:
            self._fault_since = now
        timeout = timedelta(minutes=float(self.config[CONF_FAULT_TIMEOUT]))
        if now - self._fault_since >= timeout:
            if self.status != STATUS_FAULT:
                _LOGGER.warning(
                    "Eingangsdaten fehlen seit %s min – Sensor wird unavailable, "
                    "die Anlage nutzt ihren eigenen Innensensor",
                    self.config[CONF_FAULT_TIMEOUT],
                )
            self.available = False
            self.passthrough = False
            self.output = self.offset = self.error_hz = None
            self.status = STATUS_FAULT
            self.regelung.hz_prev1 = self.regelung.hz_prev2 = None
        else:
            self.status = STATUS_WAITING
