"""Konfigurierbarer ProtoART-MQTT-Versand und Raumtemperatur-Sensordiagnose.

Diese Komponente passt die Soll-Hz nicht an und schaltet die Klimaanlage nicht ein/aus.
Sie veröffentlicht ausschließlich den vorhandenen simulierten Sensorwert.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import math
from typing import TYPE_CHECKING

from homeassistant.components import mqtt
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MQTT_ENABLED,
    CONF_MQTT_INTERVAL,
    CONF_MQTT_QOS,
    CONF_MQTT_RETAIN,
    CONF_MQTT_TOPIC,
    CONF_ROOM_TEMP,
    CONF_ROOM_STALE,
    MQTT_DEFAULTS,
    CONF_CONTROL_MODE, MODE_ROOM_OBSERVE,
)

if TYPE_CHECKING:
    from .controller import AcPidFrequencyController

_LOGGER = logging.getLogger(__name__)


def valid_publish_topic(topic: str) -> bool:
    """Ein konkretes MQTT-Publish-Topic, keine Wildcards/Steuerzeichen."""
    return (
        isinstance(topic, str)
        and bool(topic)
        and topic == topic.strip()
        and not any(c in topic for c in ("#", "+", "\x00"))
        and not any(ord(c) < 32 or ord(c) == 127 for c in topic)
        and len(topic.encode("utf-8")) <= 65535
    )


def room_sensor_snapshot(hass, entity_id: str | None, stale_after_s: float):
    """Status, Alter in Sekunden, letzter HA-Report (datetime).

    last_reported erkennt identische erneut gemeldete Messwerte. Für ältere
    HA-Versionen wird auf last_updated zurückgefallen. Ein Reportzeitpunkt ist
    kein garantiertes Bluetooth-Paket-Empfangsdatum.
    """
    if not entity_id:
        return "not_configured", None, None
    state = hass.states.get(entity_id)
    if state is None:
        return "missing", None, None
    timestamp = getattr(state, "last_reported", None) or state.last_updated
    age = max(0.0, (dt_util.utcnow() - timestamp).total_seconds()) if timestamp else None
    try:
        value = float(state.state)
        value_ok = math.isfinite(value) and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
    except (TypeError, ValueError):
        value_ok = False
    if not value_ok:
        return "invalid", age, timestamp
    if age is None or age > float(stale_after_s):
        return "stale", age, timestamp
    return "ok", age, timestamp


class ProtoArtMqttBridge:
    """Versendet periodisch den zuletzt gültigen Reglerwert unabhängig vom Hz-Takt."""

    def __init__(self, controller: AcPidFrequencyController) -> None:
        self.controller = controller
        self.state = "disabled"
        self.last_error: str | None = None
        self.last_payload: str | None = None
        self.last_success: datetime | None = None
        self.last_interval_s: float | None = None
        self.publish_count = 0
        self._lock = asyncio.Lock()
        self._stopped = False

    @property
    def enabled(self) -> bool:
        return bool(self.controller.config.get(CONF_MQTT_ENABLED, False))

    def stop(self) -> None:
        self._stopped = True

    def _notify(self) -> None:
        # Nur Entitäten aktualisieren; kein Store-Schreiben alle fünf Sekunden.
        async_dispatcher_send(self.controller.hass, self.controller.signal)

    def _set_state(self, state: str, error: str | None = None) -> None:
        if state != self.state or error != self.last_error:
            if error:
                _LOGGER.warning("ProtoART MQTT: %s: %s", state, error)
            self.state = state
            self.last_error = error
        self._notify()

    async def async_tick(self) -> None:
        if self._stopped or self._lock.locked():
            return
        async with self._lock:
            if self._stopped:
                return
            cfg = self.controller.config
            if cfg[CONF_CONTROL_MODE] == MODE_ROOM_OBSERVE:
                self._set_state("paused_observe")
                return
            if not self.enabled:
                self._set_state("disabled")
                return
            topic = str(cfg.get(CONF_MQTT_TOPIC) or "").strip()
            if not valid_publish_topic(topic):
                self._set_state("invalid_topic", "MQTT-Topic fehlt oder ist ungültig")
                return
            # Bei eingeschaltetem MQTT ist eine aktuelle unabhängige
            # Raumtemperatur verpflichtend. Kein unbekannter/veralteter Wert
            # darf per MQTT an die Anlage gelangen.
            room_id = cfg.get(CONF_ROOM_TEMP)
            stale_after = float(cfg.get(CONF_ROOM_STALE, MQTT_DEFAULTS[CONF_ROOM_STALE]))
            room_status, age, _ = room_sensor_snapshot(self.controller.hass, room_id, stale_after)
            if room_status != "ok":
                age_note = f" ({age:.0f} s alt)" if age is not None else ""
                self._set_state(f"room_{room_status}", f"Raumsensor: {room_status}{age_note}")
                return
            value = self.controller.output
            if not self.controller.available or value is None or not math.isfinite(value):
                self._set_state("output_unavailable", "Simulierter Temperaturwert nicht verfügbar")
                return
            payload = f"{value:.1f}"
            try:
                await mqtt.async_publish(
                    self.controller.hass,
                    topic,
                    payload,
                    qos=int(cfg.get(CONF_MQTT_QOS, MQTT_DEFAULTS[CONF_MQTT_QOS])),
                    retain=bool(cfg.get(CONF_MQTT_RETAIN, MQTT_DEFAULTS[CONF_MQTT_RETAIN])),
                )
            except Exception as exc:
                self._set_state("mqtt_error", f"{type(exc).__name__}: {str(exc)[:240]}")
                return
            self.last_payload = payload
            now = dt_util.utcnow()
            self.last_interval_s = round((now - self.last_success).total_seconds(), 2) if self.last_success else None
            self.last_success = now
            self.publish_count += 1
            self._set_state("sent")
