"""Konfigurierbares Topic für den nativen ProtoART-MQTT-Versand."""
from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MQTT_ENABLED, CONF_MQTT_TOPIC, CONF_BT_LAST_TOPIC, CONF_BT_TACT_TOPIC
from .controller import AcPidFrequencyController
from .entity import AcPidFrequencyEntity
from .protoart_mqtt import valid_publish_topic


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([MqttTopicText(entry.runtime_data), SilentTopicText(entry.runtime_data), BtLastTopicText(entry.runtime_data), BtTactTopicText(entry.runtime_data)])


class MqttTopicText(AcPidFrequencyEntity, TextEntity):
    """MQTT-Topic bearbeiten, ohne die Integrationsoptionen öffnen zu müssen."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:message-text-outline"
    _attr_native_min = 0
    _attr_native_max = 255
    _attr_mode = TextMode.TEXT

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "mqtt_topic")

    @property
    def native_value(self) -> str:
        return str(self.controller.config.get(CONF_MQTT_TOPIC) or "")

    async def async_set_value(self, value: str) -> None:
        value = value.strip()
        if value and not valid_publish_topic(value):
            raise HomeAssistantError("Ungültiges MQTT-Topic (keine Wildcards/Steuerzeichen).")
        if not value and self.controller.config.get(CONF_MQTT_ENABLED):
            raise HomeAssistantError("MQTT vor dem Löschen des Topics ausschalten.")
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_MQTT_TOPIC: value},
        )


class SilentTopicText(AcPidFrequencyEntity, TextEntity):
    """Nur separate ProtoART-Silent-Topic schreiben (niemals power/set)."""
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:message-cog-outline"
    _attr_native_min = 0
    _attr_native_max = 255
    _attr_mode = TextMode.TEXT

    def __init__(self, controller):
        super().__init__(controller, "silent_topic")

    @property
    def native_value(self) -> str:
        from .const import CONF_SILENT_TOPIC
        return str(self.controller.config.get(CONF_SILENT_TOPIC) or "")

    async def async_set_value(self, value: str) -> None:
        from .const import CONF_SILENT_TOPIC, CONF_SILENT_MODE
        from .silent_bridge import valid_silent_topic
        value = value.strip()
        if value and not valid_silent_topic(value):
            raise HomeAssistantError("Nur .../heatpump/silent_mode/set ist zulaessig")
        if not value and self.controller.config[CONF_SILENT_MODE] != "disabled":
            raise HomeAssistantError("Silent-Steuerung vor dem Loeschen des Topics deaktivieren")
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_SILENT_TOPIC: value},
        )


class _BtTopicText(AcPidFrequencyEntity, TextEntity):
    """Show effective topic, allow an override; empty input resets to auto."""
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min = 0
    _attr_native_max = 255
    _attr_mode = TextMode.TEXT
    option_key: str
    suffix: str

    @property
    def native_value(self) -> str:
        configured = str(self.controller.config.get(self.option_key) or "").strip()
        if configured:
            return configured
        from .bt_heartbeat import bt_topics
        derived = bt_topics(self.controller.config.get(CONF_MQTT_TOPIC))
        if derived is None:
            return ""
        return derived[0] if self.suffix == "/last" else derived[1]

    async def async_set_value(self, value: str) -> None:
        value = value.strip()
        if value and (not valid_publish_topic(value) or not value.endswith(self.suffix)
                      or "/sensor/thermometer/" not in value):
            raise HomeAssistantError("BT-Topic muss .../sensor/thermometer" + self.suffix + " sein.")
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, self.option_key: value},
        )

class BtLastTopicText(_BtTopicText):
    option_key = CONF_BT_LAST_TOPIC
    suffix = "/last"
    _attr_icon = "mdi:bluetooth-audio"
    def __init__(self, controller):
        super().__init__(controller, "bt_last_topic")

class BtTactTopicText(_BtTopicText):
    option_key = CONF_BT_TACT_TOPIC
    suffix = "/tact"
    _attr_icon = "mdi:thermometer-bluetooth"
    def __init__(self, controller):
        super().__init__(controller, "bt_tact_topic")
