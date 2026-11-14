"""Zahlen-Entität: Ziel-Hz."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from .const import CONF_MQTT_INTERVAL, CONF_MQTT_QOS
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
    async_add_entities([TargetHzNumber(controller), MqttIntervalNumber(controller), MqttQosNumber(controller)])


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
