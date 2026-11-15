"""Native Auswahl der Regelungsart – 2.4.1.4 enthält nur Beobachtungsmodus."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_CONTROL_MODE, MODE_FREQUENCY, MODE_ROOM_OBSERVE, MODE_ROOM_AUTO
from .controller import AcPidFrequencyController
from .entity import AcPidFrequencyEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ControlModeSelect(entry.runtime_data), SilentModeSelect(entry.runtime_data), MqttTransportSelect(entry.runtime_data), MqttAutomationSelect(entry.runtime_data)])


class ControlModeSelect(AcPidFrequencyEntity, SelectEntity):
    """Explizite Auswahl: Frequenzregelung oder sichere Raum-Beobachtung."""

    _attr_icon = "mdi:thermostat-auto"
    _attr_options = [MODE_FREQUENCY, MODE_ROOM_OBSERVE, MODE_ROOM_AUTO]

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "control_mode")

    @property
    def current_option(self) -> str:
        return str(self.controller.config[CONF_CONTROL_MODE])

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            raise HomeAssistantError("Ungültiger Regelmodus")
        # Bei JEDEM Moduswechsel erst deaktivieren. Aktivierung nur manuell.
        if option != self.current_option:
            self.controller.async_set_enabled(False)
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_CONTROL_MODE: option},
        )


class SilentModeSelect(AcPidFrequencyEntity, SelectEntity):
    """Silent-Verhalten. Default disabled sendet absolut keine MQTT-Befehle."""
    _attr_icon = "mdi:volume-mute"
    _attr_options = ["disabled", "always_silent", "auto", "normal"]

    def __init__(self, controller):
        super().__init__(controller, "silent_policy")

    @property
    def current_option(self) -> str:
        from .const import CONF_SILENT_MODE
        return str(self.controller.config[CONF_SILENT_MODE])

    async def async_select_option(self, option: str) -> None:
        from .const import CONF_SILENT_MODE
        from .silent_bridge import valid_silent_topic
        from .const import CONF_SILENT_TOPIC
        if option not in self._attr_options:
            raise HomeAssistantError("Ungueltiger Silent-Modus")
        if option != "disabled" and not valid_silent_topic(str(self.controller.config.get(CONF_SILENT_TOPIC) or "")):
            raise HomeAssistantError("Vorher das gueltige ProtoART-Silent-MQTT-Topic konfigurieren")
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_SILENT_MODE: option},
        )


class MqttTransportSelect(AcPidFrequencyEntity, SelectEntity):
    """Eigener Direktversand oder vorhandene Home-Assistant-Automation."""
    _attr_icon = "mdi:source-branch"
    def __init__(self, controller):
        super().__init__(controller, "mqtt_transport")
    @property
    def options(self) -> list[str]:
        return ["direct", "automation"]
    @property
    def current_option(self) -> str:
        from .const import CONF_MQTT_TRANSPORT
        return str(self.controller.config.get(CONF_MQTT_TRANSPORT, "direct"))
    async def async_select_option(self, option: str) -> None:
        from .const import CONF_MQTT_TRANSPORT, CONF_MQTT_ENABLED
        if option not in self.options:
            raise HomeAssistantError("Ungültiger MQTT-Ausgabemodus")
        if option == self.current_option:
            return
        if option == 'direct':
            from .const import CONF_MQTT_AUTOMATION
            aid = self.controller.config.get(CONF_MQTT_AUTOMATION)
            if aid and self.hass.states.is_state(aid, 'on'):
                raise HomeAssistantError('Erst die bisherige MQTT-Automation ausschalten.')
        # Beim Wechsel wird ein alter Direktversand immer deaktiviert.
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_MQTT_TRANSPORT: option, CONF_MQTT_ENABLED: False},
        )


class MqttAutomationSelect(AcPidFrequencyEntity, SelectEntity):
    """Auf Home Assistant registrierte Automationsentitäten zugreifen."""
    _attr_icon = "mdi:robot"
    NONE = "(keine Automation)"
    def __init__(self, controller):
        super().__init__(controller, "mqtt_automation")
    @property
    def options(self) -> list[str]:
        from .const import CONF_MQTT_AUTOMATION
        candidates = sorted(s.entity_id for s in self.hass.states.async_all("automation"))
        saved = self.controller.config.get(CONF_MQTT_AUTOMATION)
        if saved and saved not in candidates:
            candidates.append(saved)
        return [self.NONE] + candidates
    @property
    def current_option(self) -> str:
        from .const import CONF_MQTT_AUTOMATION
        return str(self.controller.config.get(CONF_MQTT_AUTOMATION) or self.NONE)
    async def async_select_option(self, option: str) -> None:
        from .const import CONF_MQTT_AUTOMATION, CONF_MQTT_ENABLED
        if option not in self.options:
            raise HomeAssistantError("Automation ist nicht in Home Assistant vorhanden")
        from .const import CONF_MQTT_AUTOMATION
        previous = self.controller.config.get(CONF_MQTT_AUTOMATION)
        if previous and previous != option and self.hass.states.is_state(previous, 'on'):
            raise HomeAssistantError('Zuerst die bisherige MQTT-Automation ausschalten.')
        self.hass.config_entries.async_update_entry(
            self.controller.entry,
            options={**self.controller.entry.options, CONF_MQTT_AUTOMATION: "" if option == self.NONE else option,
                     CONF_MQTT_ENABLED: False},
        )
