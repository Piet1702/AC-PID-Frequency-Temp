"""Zahlen-Entität: Ziel-Hz."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from .const import (
    CONF_MQTT_INTERVAL, CONF_MQTT_QOS, CONF_ROOM_TARGET, CONF_PREFERRED_HZ,
    CONF_ROOM_OVERHEAT_DELTA, CONF_ROOM_RESTART_DELTA, CONF_ROOM_OBSERVE_WINDOW,
    CONF_ROOM_MAX_HZ, CONF_ROOM_START_HZ, CONF_CONTROL_MODE, MODE_ROOM_AUTO, CONF_ROOM_MIN_HZ_GUARD, CONF_SILENT_BOOST_MINUTES,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfFrequency
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import TARGET_HZ_MAX, TARGET_HZ_MIN
from .controller import AcPidFrequencyController
from .entity import AcPidFrequencyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller: AcPidFrequencyController = entry.runtime_data
    async_add_entities([TargetHzNumber(controller), MqttIntervalNumber(controller), MqttQosNumber(controller), RoomTargetNumber(controller), RoomPreferredHzNumber(controller), RoomStartHzNumber(controller), RoomOverheatNumber(controller), RoomRestartDeltaNumber(controller), RoomWindowNumber(controller), RoomMaxHzNumber(controller), RoomMinHzGuardNumber(controller), SilentBoostMinutesNumber(controller)])


class TargetHzNumber(AcPidFrequencyEntity, NumberEntity):
    """Ziel-Frequenz. Hier schreiben auch eigene Automationen (z. B. PV-Logik) hinein."""

    _attr_device_class = NumberDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = TARGET_HZ_MIN
    _attr_native_max_value = TARGET_HZ_MAX
    _attr_icon = "mdi:sine-wave"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "target_hz")

    @property
    def native_value(self) -> float:
        return self.controller.target_hz

    async def async_set_native_value(self, value: float) -> None:
        if self.controller.config[CONF_CONTROL_MODE] == MODE_ROOM_AUTO:
            raise HomeAssistantError("Im Automatikmodus berechnet der Raumregler die Ziel-Hz.")
        self.controller.async_set_target_hz(value)


class MqttIntervalNumber(AcPidFrequencyEntity, NumberEntity):
    """Sekunden zwischen MQTT-Veröffentlichungen (5-60 s)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = "s"
    _attr_native_min_value = 5
    _attr_native_max_value = 60
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "mqtt_interval")

    @property
    def native_value(self) -> float:
        return float(self.controller.config[CONF_MQTT_INTERVAL])

    async def async_set_native_value(self, value: float) -> None:
        if not (5 <= value <= 60 and float(value).is_integer()):
            raise HomeAssistantError("MQTT-Intervall muss 5 bis 60 Sekunden betragen.")
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_MQTT_INTERVAL: int(value)},
        )


class MqttQosNumber(AcPidFrequencyEntity, NumberEntity):
    """MQTT-QoS 0, 1 oder 2."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:network-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 2
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "mqtt_qos")

    @property
    def native_value(self) -> float:
        return float(self.controller.config[CONF_MQTT_QOS])

    async def async_set_native_value(self, value: float) -> None:
        if value not in (0, 1, 2):
            raise HomeAssistantError("MQTT-QoS muss 0, 1 oder 2 sein.")
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_MQTT_QOS: int(value)},
        )


class RoomConfigNumber(AcPidFrequencyEntity, NumberEntity):
    """Numerische Raumregel-Option; gespeichert in HA ConfigEntry.options."""

    option_key: str
    _attr_mode = NumberMode.BOX

    def __init__(self, controller: AcPidFrequencyController, key: str) -> None:
        super().__init__(controller, key)

    @property
    def native_value(self) -> float:
        return float(self.controller.config[self.option_key])

    async def async_set_native_value(self, value: float) -> None:
        if not (self._attr_native_min_value <= value <= self._attr_native_max_value):
            raise HomeAssistantError("Wert außerhalb des zulässigen Bereichs.")
        delta = (float(value) - self._attr_native_min_value) / self._attr_native_step
        if abs(delta - round(delta)) > 0.00001:
            raise HomeAssistantError("Ungültige Schrittweite.")
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, self.option_key: float(value)},
        )


class RoomTargetNumber(RoomConfigNumber):
    option_key = CONF_ROOM_TARGET
    _attr_icon = "mdi:thermometer"
    _attr_native_unit_of_measurement = "°C"
    _attr_native_min_value = 16
    _attr_native_max_value = 30
    _attr_native_step = 0.1
    def __init__(self, controller):
        super().__init__(controller, "room_target")


class RoomPreferredHzNumber(RoomConfigNumber):
    """Niedrigste bevorzugte Dauerbetriebs-Hz, nicht Start-Hz."""
    option_key = CONF_PREFERRED_HZ
    _attr_icon = "mdi:sine-wave"
    _attr_native_unit_of_measurement = "Hz"
    _attr_native_min_value = 20
    _attr_native_max_value = 60
    _attr_native_step = 1
    def __init__(self, controller):
        super().__init__(controller, "room_preferred_hz")

class RoomStartHzNumber(RoomConfigNumber):
    """Start-Hz bei deutlicher Unterschreitung der Raum-Zieltemperatur."""
    option_key = CONF_ROOM_START_HZ
    _attr_icon = "mdi:fire"
    _attr_native_unit_of_measurement = "Hz"
    _attr_native_min_value = 20
    _attr_native_max_value = 90
    _attr_native_step = 1
    def __init__(self, controller):
        super().__init__(controller, "room_start_hz")

class RoomOverheatNumber(RoomConfigNumber):
    option_key = CONF_ROOM_OVERHEAT_DELTA
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = "K"
    _attr_native_min_value = 0.2
    _attr_native_max_value = 3.0
    _attr_native_step = 0.1
    def __init__(self, controller):
        super().__init__(controller, "room_overheat_delta")


class RoomRestartDeltaNumber(RoomConfigNumber):
    option_key = CONF_ROOM_RESTART_DELTA
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = "K"
    _attr_native_min_value = 0.1
    _attr_native_max_value = 2.0
    _attr_native_step = 0.1
    def __init__(self, controller):
        super().__init__(controller, "room_restart_delta")


class RoomWindowNumber(RoomConfigNumber):
    option_key = CONF_ROOM_OBSERVE_WINDOW
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 15
    _attr_native_max_value = 60
    _attr_native_step = 5
    def __init__(self, controller):
        super().__init__(controller, "room_observation_window")


class RoomMaxHzNumber(RoomConfigNumber):
    """Obergrenze der automatisch angeforderten Ziel-Hz, max. UI-Wert 90."""
    option_key = CONF_ROOM_MAX_HZ
    _attr_icon = "mdi:speedometer"
    _attr_native_unit_of_measurement = "Hz"
    _attr_native_min_value = 20
    _attr_native_max_value = 90
    _attr_native_step = 1
    def __init__(self, controller):
        super().__init__(controller, "room_max_hz")

class RoomMinHzGuardNumber(RoomConfigNumber):
    """Dauer in Minuten bei real gemessenen 20 Hz; 0 deaktiviert den Schutz."""
    option_key = CONF_ROOM_MIN_HZ_GUARD
    _attr_icon = "mdi:timer-alert-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 0
    _attr_native_max_value = 60
    _attr_native_step = 1
    def __init__(self, controller):
        super().__init__(controller, "room_min_hz_guard")


class SilentBoostMinutesNumber(RoomConfigNumber):
    """Wie lange der temporaere Normalleistungs-Boost dauern soll."""
    option_key = CONF_SILENT_BOOST_MINUTES
    _attr_icon = "mdi:timer-sand"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 5
    _attr_native_max_value = 120
    _attr_native_step = 5

    def __init__(self, controller):
        super().__init__(controller, "silent_boost_minutes")
