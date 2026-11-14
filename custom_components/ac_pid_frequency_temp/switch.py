"""Schalter: Hz-Regelung ein/aus."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_MQTT_ENABLED, CONF_MQTT_RETAIN, CONF_MQTT_TOPIC, CONF_ROOM_TEMP
from .protoart_mqtt import valid_publish_topic
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import AcPidFrequencyController
from .entity import AcPidFrequencyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([EnabledSwitch(entry.runtime_data), MqttEnabledSwitch(entry.runtime_data), MqttRetainSwitch(entry.runtime_data)])


class EnabledSwitch(AcPidFrequencyEntity, SwitchEntity):
    """Aus: Vorgetäuschter Sensor reicht echte Raumtemperatur durch (oder unavailable)."""

    _attr_icon = "mdi:thermostat-auto"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "enabled")

    @property
    def is_on(self) -> bool:
        return self.controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller.async_set_enabled(False)


class MqttEnabledSwitch(AcPidFrequencyEntity, SwitchEntity):
    """Live-MQTT-Ausgabe schalten, dauerhaft als Konfigurationsoption speichern."""

    _attr_icon = "mdi:message-arrow-right"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "mqtt_enabled")

    @property
    def is_on(self) -> bool:
        return bool(self.controller.config.get(CONF_MQTT_ENABLED, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        cfg = self.controller.config
        if not valid_publish_topic(str(cfg.get(CONF_MQTT_TOPIC) or "")):
            raise HomeAssistantError("MQTT-Topic zuerst konfigurieren.")
        if not cfg.get(CONF_ROOM_TEMP):
            raise HomeAssistantError("Echten Raumtemperatursensor zuerst konfigurieren.")
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_MQTT_ENABLED: True},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_MQTT_ENABLED: False},
        )


class MqttRetainSwitch(AcPidFrequencyEntity, SwitchEntity):
    """MQTT-Retain (Standard aus), nativ konfigurierbar."""

    _attr_icon = "mdi:content-save-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "mqtt_retain")

    @property
    def is_on(self) -> bool:
        return bool(self.controller.config.get(CONF_MQTT_RETAIN, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_MQTT_RETAIN: True},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_MQTT_RETAIN: False},
        )
