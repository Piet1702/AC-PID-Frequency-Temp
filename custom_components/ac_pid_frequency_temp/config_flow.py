"""Einrichtung und Umkonfiguration: alle benötigten Entitäten sind frei wählbar."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .protoart_mqtt import valid_publish_topic
from .const import (
    CONF_CLIMATE,
    CONF_DEFROST,
    CONF_FREQUENCY,
    CONF_INDOOR_UNITS,
    CONF_MAX_OFFSET,
    CONF_MQTT_ENABLED,
    CONF_MQTT_TOPIC,
    CONF_MQTT_INTERVAL,
    CONF_MQTT_QOS,
    CONF_MQTT_RETAIN,
    CONF_ROOM_STALE,
    CONF_MAX_ROOM_OVERHEAT,
    CONF_NAME,
    CONF_OUTDOOR_TEMP,
    CONF_PROBE_INTERVAL,
    CONF_ROOM_TEMP,
    CONF_WEATHER_TRIGGER_DELTA,
    DEFAULT_NAME,
    DOMAIN,
    MQTT_DEFAULTS,
    TUNING_DEFAULTS,
)

FREQUENCY_DOMAINS = ["sensor", "number", "input_number"]

# (Schlüssel, min, max, Schritt, Einheit) – auf das absolut notwendige Minimum reduziert
TUNING_FIELDS: list[tuple[str, float, float, float, str]] = [
    (CONF_MAX_OFFSET, 0.5, 5.0, 0.1, "K"),
    (CONF_MAX_ROOM_OVERHEAT, 0.2, 5.0, 0.1, "K"),
    (CONF_WEATHER_TRIGGER_DELTA, 1.0, 15.0, 0.5, "K"),
    (CONF_PROBE_INTERVAL, 30, 720, 15, "min"),
]


def _entity_selector(domain: str | list[str], multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain, multiple=multiple)
    )


def _entities_schema(with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=DEFAULT_NAME)] = selector.TextSelector()
    fields[vol.Required(CONF_CLIMATE)] = _entity_selector("climate")
    fields[vol.Required(CONF_FREQUENCY)] = _entity_selector(FREQUENCY_DOMAINS)
    fields[vol.Optional(CONF_OUTDOOR_TEMP)] = _entity_selector(["sensor", "weather"])
    fields[vol.Optional(CONF_ROOM_TEMP)] = _entity_selector("sensor")
    fields[vol.Optional(CONF_DEFROST)] = _entity_selector(["binary_sensor", "sensor"])
    fields[vol.Optional(CONF_INDOOR_UNITS)] = _entity_selector("climate", multiple=True)
    return vol.Schema(fields)


def _tuning_schema() -> vol.Schema:
    fields: dict[Any, Any] = {}
    for key, low, high, step, unit in TUNING_FIELDS:
        config = selector.NumberSelectorConfig(
            min=low,
            max=high,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
        )
        if unit:
            config["unit_of_measurement"] = unit
        fields[vol.Required(key)] = selector.NumberSelector(config)
    return vol.Schema(fields)


def _mqtt_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_MQTT_ENABLED, default=False): selector.BooleanSelector(),
        vol.Optional(CONF_MQTT_TOPIC): selector.TextSelector(),
        vol.Required(CONF_MQTT_INTERVAL, default=5): selector.NumberSelector(
            selector.NumberSelectorConfig(min=5, max=60, step=1, mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_MQTT_QOS, default=0): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=2, step=1, mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_MQTT_RETAIN, default=False): selector.BooleanSelector(),
        vol.Required(CONF_ROOM_STALE, default=300): selector.NumberSelector(
            selector.NumberSelectorConfig(min=60, max=3600, step=30, mode=selector.NumberSelectorMode.BOX)
        ),
    })


def _clean_indoor_units(user_input: dict[str, Any]) -> list[str]:
    """Weitere Innengeräte ohne das Master-Gerät und ohne Doppelte."""
    master = user_input.get(CONF_CLIMATE)
    seen: list[str] = []
    for entity_id in user_input.get(CONF_INDOOR_UNITS) or []:
        if entity_id != master and entity_id not in seen:
            seen.append(entity_id)
    return seen


class AcPidFrequencyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ersteinrichtung."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_CLIMATE])
            self._abort_if_unique_id_configured()
            data = {**user_input, CONF_INDOOR_UNITS: _clean_indoor_units(user_input)}
            return self.async_create_entry(title=user_input[CONF_NAME], data=data)

        return self.async_show_form(step_id="user", data_schema=_entities_schema(with_name=True))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AcPidFrequencyOptionsFlow:
        return AcPidFrequencyOptionsFlow()


class AcPidFrequencyOptionsFlow(OptionsFlow):
    """Nachträglich umkonfigurieren: Entitäten oder Regelparameter."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["entities", "tuning", "mqtt"])

    def _current(self) -> dict[str, Any]:
        return {**TUNING_DEFAULTS, **MQTT_DEFAULTS, **self.config_entry.data, **self.config_entry.options}

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = {
                **self.config_entry.options,
                CONF_CLIMATE: user_input[CONF_CLIMATE],
                CONF_FREQUENCY: user_input[CONF_FREQUENCY],
                CONF_OUTDOOR_TEMP: user_input.get(CONF_OUTDOOR_TEMP),
                CONF_ROOM_TEMP: user_input.get(CONF_ROOM_TEMP),
                CONF_DEFROST: user_input.get(CONF_DEFROST),
                CONF_INDOOR_UNITS: _clean_indoor_units(user_input),
            }
            return self.async_create_entry(data=options)

        schema = self.add_suggested_values_to_schema(
            _entities_schema(with_name=False), self._current()
        )
        return self.async_show_form(step_id="entities", data_schema=schema)

    async def async_step_tuning(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})

        suggested = user_input if user_input is not None else self._current()
        schema = self.add_suggested_values_to_schema(_tuning_schema(), suggested)
        return self.async_show_form(step_id="tuning", data_schema=schema)


    async def async_step_mqtt(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """ProtoART MQTT (standardmäßig aus; Topic wird nicht automatisch geraten)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            enabled = bool(user_input.get(CONF_MQTT_ENABLED, False))
            topic = str(user_input.get(CONF_MQTT_TOPIC) or "").strip()
            if enabled and not self._current().get(CONF_ROOM_TEMP):
                errors["base"] = "room_sensor_required"
            elif enabled and not valid_publish_topic(topic):
                errors["base"] = "invalid_mqtt_topic"
            if not errors:
                changes = {**user_input, CONF_MQTT_TOPIC: topic}
                return self.async_create_entry(data={**self.config_entry.options, **changes})
        schema = self.add_suggested_values_to_schema(_mqtt_schema(), self._current())
        return self.async_show_form(step_id="mqtt", data_schema=schema, errors=errors)
