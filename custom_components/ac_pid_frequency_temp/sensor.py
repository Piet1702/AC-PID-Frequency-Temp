"""Sensoren: der vorgetäuschte Raumtemperatursensor plus Diagnosewerte."""

from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfFrequency, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CLIMATE,
    CONF_DEFROST,
    CONF_FREQUENCY,
    CONF_INDOOR_UNITS,
    CONF_OUTDOOR_TEMP,
    CONF_ROOM_TEMP,
    CONF_ROOM_STALE,
    MQTT_DEFAULTS,
    DOMAIN,
    STATUSES,
)
from .controller import AcPidFrequencyController
from .const import (CONF_ROOM_TARGET, CONF_ROOM_OVERHEAT_DELTA,
                    CONF_ROOM_RESTART_DELTA, CONF_PREFERRED_HZ)
from .entity import AcPidFrequencyEntity
from .protoart_mqtt import room_sensor_snapshot


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller: AcPidFrequencyController = entry.runtime_data
    async_add_entities(
        [
            FakeTemperatureSensor(controller),
            StatusSensor(controller),
            OffsetSensor(controller),
            FactorSensor(controller),
            ErrorSensor(controller),
            MinHzSensor(controller),
            RoomObservationPhaseSensor(controller),
            RoomTrendSensor(controller),
            RoomDeltaSensor(controller),
            RoomAdviceSensor(controller),
            RoomMinHzDurationSensor(controller),
            RoomAutoStatusSensor(controller),
            RoomContinuitySensor(controller),
            SilentStatusSensor(controller),
            MqttStatusSensor(controller),
            MqttLastPublishSensor(controller),
            RoomSensorStatusSensor(controller),
            RoomSensorAgeSensor(controller),
        ]
    )


class FakeTemperatureSensor(AcPidFrequencyEntity, SensorEntity):
    """Der "Raumthermometer"-Wert für die Klimaanlage (0,1-K-Schritte).

    Regelt der Regler nicht (aus / kein Heizbetrieb), wird die echte Raumtemperatur
    durchgereicht, sofern ein Raumsensor konfiguriert ist und einen Wert liefert. Sonst wird
    der Sensor ``unavailable`` und die Anlage fällt auf ihren eigenen Innensensor zurück.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "temperature")

    @property
    def available(self) -> bool:
        return self.controller.available and self.controller.output is not None

    @property
    def native_value(self) -> float | None:
        return self.controller.output


class StatusSensor(AcPidFrequencyEntity, SensorEntity):
    """Reglerstatus; trägt außerdem die Entitäts-IDs, die die Karte zum Finden braucht."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "status")

    @property
    def native_value(self) -> str:
        return self.controller.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        registry = er.async_get(self.hass)
        entry_id = self.controller.entry.entry_id
        cfg = self.controller.config

        def lookup(platform: str, key: str) -> str | None:
            return registry.async_get_entity_id(platform, DOMAIN, f"{entry_id}_{key}")

        return {
            # Schlüssel, über den die Karte "ihren" Regler zur Climate-Entität findet
            "ac_pid_frequency_temp_climate": cfg[CONF_CLIMATE],
            "frequency_entity": cfg[CONF_FREQUENCY],
            "outdoor_temperature_entity": cfg.get(CONF_OUTDOOR_TEMP),
            "room_temperature_entity": cfg.get(CONF_ROOM_TEMP),
            "defrost_entity": cfg.get(CONF_DEFROST),
            "passthrough": self.controller.passthrough,
            "indoor_units": list(cfg.get(CONF_INDOOR_UNITS) or []),
            "active_outdoor_bin": self.controller.regelung.current_outdoor_bin,
            "active_freq_bin": self.controller.regelung.current_freq_bin,
            "learned_offset": self.controller.regelung.current_learned_offset,
            "learned_min_hz": self.controller.regelung.learned_min_hz,
            "learned_reaction_time": self.controller.regelung.learned_reaction_time,
            "learned_sensitivity": self.controller.regelung.learned_sensitivity,
            "effective_target_hz": self.controller.regelung.effective_target_hz,
            "temperature_entity": lookup("sensor", "temperature"),
            "offset_entity": lookup("sensor", "offset"),
            "factor_entity": lookup("sensor", "learning_factor"),
            "error_entity": lookup("sensor", "frequency_error"),
            "min_hz_entity": lookup("sensor", "learned_min_hz"),
            "target_hz_entity": lookup("number", "target_hz"),
            "control_mode": cfg.get("control_mode"),
            "room_target_entity": lookup("number", "room_target"),
            "room_start_hz_entity": lookup("number", "room_start_hz"),
            "room_max_hz_entity": lookup("number", "room_max_hz"),
            "room_preferred_hz_entity": lookup("number", "room_preferred_hz"),
            "room_auto_status_entity": lookup("sensor", "room_auto_status"),
            "room_start_hz": cfg.get("room_start_hz"),
            "room_preferred_hz": cfg.get("room_preferred_hz"),
            "room_max_hz": cfg.get("room_max_hz"),
            "switch_entity": lookup("switch", "enabled"),
            "reset_min_hz_button_entity": lookup("button", "reset_min_hz"),
            "reset_learning_button_entity": lookup("button", "reset_learning"),
        }


class OffsetSensor(AcPidFrequencyEntity, SensorEntity):
    """Abstand des Sensorwerts zur Soll-Temperatur (positiv = Anlage wird angeschoben)."""

    _attr_native_unit_of_measurement = "K"
    _attr_suggested_display_precision = 2
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "offset")

    @property
    def native_value(self) -> float | None:
        return self.controller.offset


class FactorSensor(AcPidFrequencyEntity, SensorEntity):
    """Aktueller Erfahrungswert / gelernter Offset für den aktiven Arbeitspunkt."""

    _attr_native_unit_of_measurement = "K"
    _attr_suggested_display_precision = 2
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "learning_factor")

    @property
    def native_value(self) -> float:
        return self.controller.regelung.current_learned_offset


class ErrorSensor(AcPidFrequencyEntity, SensorEntity):
    """Regelabweichung in Hz (Ziel minus Ist)."""

    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_suggested_display_precision = 1
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "frequency_error")

    @property
    def native_value(self) -> float | None:
        return self.controller.error_hz


class MinHzSensor(AcPidFrequencyEntity, SensorEntity):
    """Erreichte bzw. erlernte Mindestmodulation des Kompressors (Hz)."""

    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_suggested_display_precision = 1
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:arrow-collapse-down"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "learned_min_hz")

    @property
    def native_value(self) -> float:
        return self.controller.regelung.learned_min_hz


class MqttStatusSensor(AcPidFrequencyEntity, SensorEntity):
    """HA-seitiger Veröffentlichungsstatus (keine ProtoART-Empfangsbestätigung)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "disabled", "sent", "invalid_topic", "room_not_configured",
        "room_missing", "room_invalid", "room_stale",
        "output_unavailable", "mqtt_error", "paused_observe",
    ]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:message-arrow-right"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "mqtt_status")

    @property
    def native_value(self) -> str:
        return self.controller.mqtt_bridge.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        bridge = self.controller.mqtt_bridge
        cfg = self.controller.config
        return {
            "topic": cfg.get("mqtt_topic"),
            "send_interval_s": cfg.get("mqtt_interval_s"),
            "publish_count": bridge.publish_count,
            "last_publish_interval_s": bridge.last_interval_s,
            "last_publish_age_s": round((datetime.now(timezone.utc) - bridge.last_success).total_seconds(), 1) if bridge.last_success else None,
            "last_payload": bridge.last_payload,
            "last_error": bridge.last_error,
            "last_publish_utc": bridge.last_success.isoformat() if bridge.last_success else None,
            "qos": cfg.get("mqtt_qos"),
            "retain": cfg.get("mqtt_retain"),
            "note": "sent = vom HA-MQTT-Client akzeptiert; keine Empfangsbestätigung des Geräts",
        }


class MqttLastPublishSensor(AcPidFrequencyEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "mqtt_last_publish")

    @property
    def native_value(self):
        return self.controller.mqtt_bridge.last_success


class RoomSensorStatusSensor(AcPidFrequencyEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["not_configured", "missing", "invalid", "stale", "ok"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:bluetooth-connect"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "room_sensor_status")

    def _snapshot(self):
        cfg = self.controller.config
        return room_sensor_snapshot(
            self.controller.hass, cfg.get(CONF_ROOM_TEMP),
            float(cfg.get(CONF_ROOM_STALE, MQTT_DEFAULTS[CONF_ROOM_STALE]))
        )

    @property
    def native_value(self) -> str:
        return self._snapshot()[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status, age, last_report = self._snapshot()
        cfg = self.controller.config
        return {
            "source_entity": cfg.get(CONF_ROOM_TEMP),
            "age_seconds": round(age, 1) if age is not None else None,
            "last_reported_utc": last_report.isoformat() if last_report else None,
            "stale_after_seconds": cfg.get(CONF_ROOM_STALE),
            "status": status,
        }


class RoomSensorAgeSensor(AcPidFrequencyEntity, SensorEntity):
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_display_precision = 0
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:timer-outline"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "room_sensor_age")

    @property
    def native_value(self) -> float | None:
        cfg = self.controller.config
        _, age, _ = room_sensor_snapshot(
            self.controller.hass, cfg.get(CONF_ROOM_TEMP),
            float(cfg.get(CONF_ROOM_STALE, MQTT_DEFAULTS[CONF_ROOM_STALE]))
        )
        return round(age, 1) if age is not None else None


class RoomObservationPhaseSensor(AcPidFrequencyEntity, SensorEntity):
    """Beobachtungsstatus; ausdrücklich keine automatische Temperaturregelung."""
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "collecting", "defrost", "recovery", "sensor_missing", "sensor_stale",
        "inactive", "below_restart", "approaching", "tolerance", "above_limit",
    ]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-timeline-variant"
    def __init__(self, controller):
        super().__init__(controller, "room_observer_phase")
    @property
    def native_value(self) -> str:
        return self.controller.room_observer.snapshot.phase
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        m = self.controller.room_observer.snapshot
        cfg = self.controller.config
        return {
            "reason": m.reason,
            "advice": m.advice,
            "observed_room_temperature": m.room_temp,
            "target_room_temperature": cfg.get(CONF_ROOM_TARGET),
            "upper_tolerance_temperature": round(cfg[CONF_ROOM_TARGET] + cfg[CONF_ROOM_OVERHEAT_DELTA], 2),
            "restart_reference_temperature": round(cfg[CONF_ROOM_TARGET] - cfg[CONF_ROOM_RESTART_DELTA], 2),
            "preferred_continuous_hz": cfg[CONF_PREFERRED_HZ],
            "physical_minimum_hz_assumed": 20,
            "observed_window_minutes": m.window_minutes,
            "sample_count": m.samples,
            "sensor_age_seconds": m.input_age_seconds,
            "recovery_seconds_remaining": m.recovery_seconds,
            "observation_only": True,
            "writes_target_hz": False,
            "writes_mqtt_power": False,
        }


class RoomTrendSensor(AcPidFrequencyEntity, SensorEntity):
    _attr_native_unit_of_measurement = "°C/h"
    _attr_suggested_display_precision = 3
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:trending-up"
    def __init__(self, controller):
        super().__init__(controller, "room_temperature_trend")
    @property
    def native_value(self) -> float | None:
        return self.controller.room_observer.snapshot.trend_kph


class RoomDeltaSensor(AcPidFrequencyEntity, SensorEntity):
    _attr_native_unit_of_measurement = "K"
    _attr_suggested_display_precision = 2
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    def __init__(self, controller):
        super().__init__(controller, "room_target_delta")
    @property
    def native_value(self) -> float | None:
        return self.controller.room_observer.snapshot.delta_k


class RoomAdviceSensor(AcPidFrequencyEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "paused", "wait_data", "hold", "increase_slowly", "reduce_slowly",
        "prefer_continuous",
    ]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    def __init__(self, controller):
        super().__init__(controller, "room_observer_advice")
    @property
    def native_value(self) -> str:
        return self.controller.room_observer.snapshot.advice
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"reason": self.controller.room_observer.snapshot.reason,
                "is_simulation": True, "writes_to_heatpump": False}


class RoomMinHzDurationSensor(AcPidFrequencyEntity, SensorEntity):
    _attr_native_unit_of_measurement = "min"
    _attr_suggested_display_precision = 1
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    def __init__(self, controller):
        super().__init__(controller, "room_time_at_min_hz")
    @property
    def native_value(self) -> float:
        return self.controller.room_observer.snapshot.minutes_at_min_hz


class RoomAutoStatusSensor(AcPidFrequencyEntity, SensorEntity):
    """Warum und wann der neue äußere Temperaturregler Ziel-Hz verändert."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:brain"
    def __init__(self, controller):
        super().__init__(controller, "room_auto_status")
    @property
    def native_value(self) -> str:
        return self.controller.room_auto.decision.state
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.controller.room_auto.decision
        return {
            "reason": d.reason,
            "action": d.action,
            "calculated_target_hz": d.target_hz,
            "start_hz": self.controller.config.get("room_start_hz"),
            "continuous_minimum_hz": self.controller.config.get("room_preferred_hz"),
            "maximum_hz": self.controller.config.get("room_max_hz"),
            "next_regular_check_min": d.next_check_min,
            "heat_suppressed": d.heat_suppressed,
            "writes_mqtt_power": False,
            "actual_room_temperature": self.controller.room_observer.snapshot.room_temp,
            "temperature_trend_c_per_h": self.controller.room_observer.snapshot.trend_kph,
        }


class RoomContinuitySensor(AcPidFrequencyEntity, SensorEntity):
    """Details zur 20-Hz-Schutzlogik und zum gelernten Heizbedarf."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-timeline-variant-shimmer"

    def __init__(self, controller):
        super().__init__(controller, "room_continuity")

    @property
    def native_value(self) -> str:
        from .const import CONF_CONTROL_MODE, MODE_ROOM_AUTO, CONF_ROOM_MIN_HZ_GUARD
        cfg = self.controller.config
        if cfg[CONF_CONTROL_MODE] != MODE_ROOM_AUTO or not self.controller.enabled:
            return "inactive"
        if self.controller.room_auto.decision.state == "min_modulation_guard":
            return "guard_active"
        if self.controller.room_auto.decision.heat_suppressed:
            return "temperature_limit"
        if self.controller.room_auto.decision.state in ("paused", "fault"):
            return "paused"
        if float(cfg[CONF_ROOM_MIN_HZ_GUARD]) <= 0:
            return "guard_disabled"
        return "monitoring"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        from .const import CONF_ROOM_MIN_HZ_GUARD
        ctrl = self.controller.room_auto
        return {
            "minutes_at_measured_20_hz": ctrl.latest_min_duration,
            "guard_threshold_minutes": self.controller.config[CONF_ROOM_MIN_HZ_GUARD],
            "outdoor_zone": ctrl.latest_zone,
            "learned_hz_in_zone": ctrl.continuity.learned_hz(None if ctrl.latest_zone == "unknown" else
                (-1 if ctrl.latest_zone == "frost" else (6 if ctrl.latest_zone == "transition" else 15))),
            "learned_zones": ctrl.continuity.export(),
            "learning_updated_this_tick": ctrl.last_learned,
            "calculated_target_hz": ctrl.decision.target_hz,
            "reason": ctrl.decision.reason,
            "mqtt_power_commands": False,
        }


class SilentStatusSensor(AcPidFrequencyEntity, SensorEntity):
    """Anforderung und beobachteter ProtoART-Silent-Zustand getrennt darstellen."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:volume-mute"

    def __init__(self, controller):
        super().__init__(controller, "silent_status")

    @property
    def native_value(self) -> str:
        return self.controller.silent_bridge.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        bridge = self.controller.silent_bridge
        return {
            "reason": bridge.reason,
            "last_requested": bridge.last_requested,
            "device_confirmed": bridge.confirmed,
            "last_publish_at": bridge.last_sent_at.isoformat() if bridge.last_sent_at else None,
            "last_confirmation_at": bridge.last_confirmed_at.isoformat() if bridge.last_confirmed_at else None,
            "unconfirmed_attempts": bridge.attempts,
            "boost_remaining_min": bridge.boost_left_min,
            "mqtt_error": bridge.last_error,
            "mqtt_power_commands": False,
        }
