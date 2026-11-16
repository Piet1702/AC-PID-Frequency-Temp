"""Schalter: Hz-Regelung ein/aus."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_MQTT_ENABLED, CONF_MQTT_RETAIN, CONF_MQTT_TOPIC, CONF_ROOM_TEMP, CONF_CONTROL_MODE, MODE_ROOM_OBSERVE, MODE_ROOM_AUTO, CONF_ROOM_STALE
from .protoart_mqtt import valid_publish_topic, room_sensor_snapshot
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
        if self.controller.config[CONF_CONTROL_MODE] == MODE_ROOM_OBSERVE:
            raise HomeAssistantError("Im Raum-Beobachtungsmodus ist die Hz-Regelung gesperrt.")
        cfg = self.controller.config
        if cfg[CONF_CONTROL_MODE] == MODE_ROOM_AUTO:
            room_id = cfg.get(CONF_ROOM_TEMP)
            status, _age, _report = self.controller.room_input_snapshot()
            if status != "ok":
                raise HomeAssistantError(
                    f"Adaptive Raumregelung benötigt frische echte Raumdaten: {status}"
                )
        self.controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller.async_set_enabled(False)


class MqttEnabledSwitch(AcPidFrequencyEntity, SwitchEntity):
    """Im Automationsmodus der echte Zustand von HA automation.on/off."""
    _attr_icon = "mdi:message-arrow-right"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "mqtt_enabled")

    @property
    def is_on(self) -> bool:
        from .const import CONF_MQTT_TRANSPORT, MQTT_TRANSPORT_AUTOMATION, CONF_MQTT_AUTOMATION
        cfg = self.controller.config
        if cfg.get(CONF_MQTT_TRANSPORT) == MQTT_TRANSPORT_AUTOMATION:
            eid = cfg.get(CONF_MQTT_AUTOMATION)
            return bool(eid and self.hass.states.is_state(eid, "on"))
        return bool(cfg.get(CONF_MQTT_ENABLED, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        from .const import CONF_MQTT_TRANSPORT, MQTT_TRANSPORT_AUTOMATION, CONF_MQTT_AUTOMATION
        from .automation_mqtt import valid_automation_id
        cfg = self.controller.config
        if cfg.get(CONF_MQTT_TRANSPORT) == MQTT_TRANSPORT_AUTOMATION:
            eid = cfg.get(CONF_MQTT_AUTOMATION)
            state = self.hass.states.get(eid) if valid_automation_id(eid) else None
            if state is None or state.state in ("unavailable", "unknown"):
                raise HomeAssistantError("Zuerst eine vorhandene HA-MQTT-Automation auswählen.")
            if not valid_publish_topic(str(cfg.get(CONF_MQTT_TOPIC) or "")):
                raise HomeAssistantError("Zuerst das richtige MQTT-Topic hinterlegen.")
            # Sicherheit: im Automationsmodus niemals parallel direkt publishen.
            await self.hass.services.async_call(
                "automation", "turn_on", {"entity_id": eid}, blocking=True
            )
            self.controller.automation_mqtt.tick()
            return
        if not valid_publish_topic(str(cfg.get(CONF_MQTT_TOPIC) or "")):
            raise HomeAssistantError("MQTT-Topic zuerst konfigurieren.")
        # Kein doppelter MQTT-Versand bei einer noch aktiven verknüpften Automation.
        from .const import CONF_MQTT_AUTOMATION
        aid = cfg.get(CONF_MQTT_AUTOMATION)
        if aid and self.hass.states.is_state(aid, 'on'):
            raise HomeAssistantError('Die verknuepfte MQTT-Automation zuerst deaktivieren.')
        if not cfg.get(CONF_ROOM_TEMP):
            raise HomeAssistantError("Echten Raumtemperatursensor zuerst konfigurieren.")
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_MQTT_ENABLED: True},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        from .const import CONF_MQTT_TRANSPORT, MQTT_TRANSPORT_AUTOMATION, CONF_MQTT_AUTOMATION
        from .automation_mqtt import valid_automation_id
        cfg = self.controller.config
        if cfg.get(CONF_MQTT_TRANSPORT) == MQTT_TRANSPORT_AUTOMATION:
            eid = cfg.get(CONF_MQTT_AUTOMATION)
            if not valid_automation_id(eid) or self.hass.states.get(eid) is None:
                raise HomeAssistantError("Keine gültige HA-Automation gewählt.")
            await self.hass.services.async_call(
                "automation", "turn_off", {"entity_id": eid}, blocking=True
            )
            self.controller.automation_mqtt.tick()
            return
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
