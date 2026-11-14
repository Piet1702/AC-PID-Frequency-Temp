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
    async_add_entities([ControlModeSelect(entry.runtime_data)])


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
