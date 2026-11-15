"""AC PID Frequency Temp: stellt der Klimaanlage einen vorgetäuschten Raumsensor bereit, mit dem sie auf eine Ziel-Frequenz einpendelt."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CARD_FILE, CARD_URL, DOMAIN, PLATFORMS, STORAGE_VERSION
from .controller import AcPidFrequencyController

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def _async_get_version_url(hass: HomeAssistant) -> str:
    """Ermittelt die versions- und zeitstempelbehaftete URL der Lovelace-Karte."""
    integration = await async_get_integration(hass, DOMAIN)
    card = Path(__file__).parent / "frontend" / CARD_FILE
    try:
        timestamp = int(card.stat().st_mtime)
    except OSError:
        timestamp = 0
    return f"{CARD_URL}?v={integration.version}_{timestamp}"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Lovelace-Karte ausliefern und automatisch in alle Dashboards laden."""
    card = Path(__file__).parent / "frontend" / CARD_FILE
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card), False)])

    # Die Karte wird ausschließlich über add_extra_js_url geladen (nicht zusätzlich als
    # Lovelace-Ressource). Die URL enthält Version und Zeitstempel der Datei und ändert
    # sich damit nach jeder Änderung an der Karte (Cache-Busting für Browser und App).
    add_extra_js_url(hass, await _async_get_version_url(hass))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    controller = AcPidFrequencyController(hass, entry)
    await controller.async_load()
    entry.runtime_data = controller

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Erst jetzt starten: alle Entitäten sind registriert, die Status-Attribute vollständig
    controller.async_start()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Gespeicherten Reglerzustand löschen, wenn die Integration entfernt wird."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Entitäten/Regeltakt brauchen Reload; Laufzeitoptionen wirken sofort."""
    from .const import (
        CONF_CLIMATE, CONF_DEFROST, CONF_FREQUENCY, CONF_INDOOR_UNITS,
        CONF_OUTDOOR_TEMP, CONF_ROOM_TEMP, CONF_INTERVAL, CONF_CONTROL_MODE, CONF_MQTT_TOPIC, CONF_BT_LAST_TOPIC, CONF_BT_TACT_TOPIC,
    )
    ctrl = entry.runtime_data
    if ctrl is None:
        return
    previous = ctrl._last_options
    new_options = dict(entry.options)
    changed = {k for k in previous.keys() | new_options.keys()
               if previous.get(k) != new_options.get(k)}
    ctrl._last_options = new_options
    if not changed:
        return
    needs_reload = {
        CONF_CLIMATE, CONF_DEFROST, CONF_FREQUENCY, CONF_INDOOR_UNITS,
        CONF_OUTDOOR_TEMP, CONF_ROOM_TEMP, CONF_INTERVAL, CONF_MQTT_TOPIC, CONF_BT_LAST_TOPIC, CONF_BT_TACT_TOPIC,
    }
    if changed & needs_reload:
        await hass.config_entries.async_reload(entry.entry_id)
        return
    if CONF_CONTROL_MODE in changed:
        ctrl.async_set_enabled(False)  # Umschalten nur bewusst neu aktivieren
    else:
        ctrl._tick()
    if changed & {"mqtt_transport", "mqtt_automation_entity", "mqtt_topic"}:
        await ctrl.automation_mqtt.async_refresh()
    ctrl.mqtt_cadence.reset()
    ctrl._handle_mqtt_diag_tick(None)
    ctrl._handle_silent_tick(None)
