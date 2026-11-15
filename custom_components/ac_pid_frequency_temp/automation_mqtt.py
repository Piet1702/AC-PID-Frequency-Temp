"""Beobachtet echte MQTT-Broker-Nachrichten bei Verwendung einer HA-Automation.

Kein Publish. Ein beobachtetes Paket beweist keine ProtoART-Verarbeitung und
lässt sich nicht eindeutig einem bestimmten MQTT-Publisher zuordnen.
"""
from __future__ import annotations

from datetime import datetime
import logging
import math
from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import CONF_MQTT_AUTOMATION, CONF_MQTT_INTERVAL, CONF_MQTT_TOPIC, CONF_MQTT_TRANSPORT, MQTT_TRANSPORT_AUTOMATION
from .protoart_mqtt import valid_publish_topic

_LOGGER = logging.getLogger(__name__)


def valid_automation_id(entity_id: object) -> bool:
    return isinstance(entity_id, str) and entity_id.startswith('automation.') and len(entity_id) > len('automation.')


def classify_monitor(*, automation_state: str | None, last_received: datetime | None, now: datetime, interval_s: float) -> str:
    if automation_state is None or automation_state in ('unknown', 'unavailable'):
        return 'automation_missing'
    if automation_state != 'on':
        return 'automation_off'
    if last_received is None:
        return 'monitoring'
    if (now - last_received).total_seconds() > max(15.0, 2.5 * max(1.0, interval_s)):
        return 'delayed'
    return 'receiving'


class AutomationMqttMonitor:
    """Wird unabhängig von Raumtemperatur-Veränderungen aufgerufen."""

    def __init__(self, controller) -> None:
        self.controller = controller
        self._unsubscribe = None
        self._topic: str | None = None
        self._closed = False
        self.status = 'disabled'
        self.last_error: str | None = None
        self.last_payload: str | None = None
        self.last_received: datetime | None = None
        self.last_interval_s: float | None = None
        self.received_count = 0
        self.invalid_count = 0
        self.ignored_retained = 0
        self._subscribe_started: datetime | None = None
        self._invalid_at: datetime | None = None

    def _notify(self) -> None:
        async_dispatcher_send(self.controller.hass, self.controller.signal)

    def _unsubscribe_topic(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._topic = None

    async def async_refresh(self) -> None:
        """MQTT-Subscription bei Topic-/Moduswechsel sicher neu aufbauen."""
        if self._closed:
            return
        cfg = self.controller.config
        if cfg.get(CONF_MQTT_TRANSPORT) != MQTT_TRANSPORT_AUTOMATION:
            self._unsubscribe_topic()
            self.status = 'disabled'
            self.last_error = None
            self._notify()
            return
        topic = str(cfg.get(CONF_MQTT_TOPIC) or '').strip()
        if not valid_publish_topic(topic):
            self._unsubscribe_topic()
            self.status = 'invalid_topic'
            self.last_error = 'Temperatur-MQTT-Topic ist leer oder ungueltig.'
            self._notify()
            return
        if self._topic == topic and self._unsubscribe is not None:
            self.tick()
            return
        self._unsubscribe_topic()
        self.last_received = None
        self._subscribe_started = None
        self.last_interval_s = None
        self.received_count = 0
        self.invalid_count = 0
        self.last_payload = None
        try:
            # Die Subscription ist passiv: die HA-Automation sendet weiterhin.
            self._unsubscribe = await mqtt.async_subscribe(
                self.controller.hass, topic, self._message_received, qos=0
            )
            self._topic = topic
            self._subscribe_started = dt_util.utcnow()
            self.last_error = None
            self.tick()
        except Exception as exc:  # MQTT kann beim HA-Start noch nicht bereit sein
            self.status = 'listen_error'
            self.last_error = str(exc)
            _LOGGER.warning('MQTT Monitoring konnte %s nicht abonnieren: %s', topic, exc)
            self._notify()

    @callback
    def _message_received(self, message) -> None:
        """HA MQTT callback: nur tatsächliche eingetroffene Broker-Nachrichten zählen."""
        if self._closed or self._topic is None or message.topic != self._topic:
            return
        if getattr(message, 'retain', False):
            self.ignored_retained += 1
            return
        payload = message.payload
        if isinstance(payload, bytes):
            try:
                payload = payload.decode('utf-8')
            except UnicodeDecodeError:
                payload = ''
        payload = str(payload).strip()
        try:
            value = float(payload)
            if not math.isfinite(value):
                raise ValueError('not finite')
        except (ValueError, TypeError):
            self.invalid_count += 1
            self._invalid_at = dt_util.utcnow()
            self.last_error = f'Ungueltige Temperatur-Payload: {payload[:70]!r}'
            self.status = 'invalid_payload'
            self._notify()
            return
        now = dt_util.utcnow()
        self.last_interval_s = round((now - self.last_received).total_seconds(), 2) if self.last_received else None
        self.last_received = now
        self.last_payload = payload
        self.received_count += 1
        self.last_error = None
        self._invalid_at = None
        self.tick()
        self._notify()

    def tick(self) -> None:
        """Automation-Status und Sendeintervall auswerten (ohne Sensor-Stale-Gate)."""
        if self._closed or self._topic is None:
            return
        cfg = self.controller.config
        entity_id = cfg.get(CONF_MQTT_AUTOMATION)
        state = self.controller.hass.states.get(entity_id) if valid_automation_id(entity_id) else None
        state_string = state.state if state is not None else None
        now = dt_util.utcnow()
        interval = float(cfg.get(CONF_MQTT_INTERVAL, 5))
        next_status = classify_monitor(
            automation_state=state_string, last_received=self.last_received,
            now=now, interval_s=interval,
        )
        # Ohne erste Nachricht zunächst auf Empfang warten; erst nach Timeout warnen.
        if (next_status == 'monitoring' and self._subscribe_started is not None
                and (now - self._subscribe_started).total_seconds() > max(15.0, 2.5 * max(1.0, interval))):
            next_status = 'delayed'
        if self._invalid_at and (now - self._invalid_at).total_seconds() < 15:
            next_status = 'invalid_payload'
        if next_status != self.status:
            self.status = next_status
            self._notify()

    async def async_stop(self) -> None:
        self._closed = True
        self._unsubscribe_topic()
