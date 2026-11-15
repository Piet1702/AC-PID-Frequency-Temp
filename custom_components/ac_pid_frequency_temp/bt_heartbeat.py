"""MQTT-only ProtoART BT-contact monitor; no MQTT writes or HTTP requests.

Only the characteristic jump of `thermometer/last` toward zero counts as a
probable physical BT contact. A regular five-second MQTT publish does not.
"""
from __future__ import annotations
from datetime import datetime, timezone
import logging
import math
import re
from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util
from .bt_heartbeat_logic import BtLastTracker
from .const import CONF_MQTT_TOPIC, CONF_BT_TIMEOUT_MIN

_LOGGER = logging.getLogger(__name__)
_TOPIC = re.compile(r"^(climacontrol/[^/]+)/sensor/external/temperature/set$")


def bt_topics(temperature_set_topic: str | None) -> tuple[str, str] | None:
    match = _TOPIC.fullmatch(str(temperature_set_topic or "").lstrip("/"))
    if match is None:
        return None
    base = match.group(1)
    return base + "/sensor/thermometer/last", base + "/sensor/thermometer/tact"


class ProtoArtBtMonitor:
    def __init__(self, controller) -> None:
        self.controller = controller
        self.tracker = BtLastTracker()
        self.started_at = dt_util.utcnow()
        self.unsubs = []
        self.topic_last: str | None = None
        self.topic_tact: str | None = None
        self.latest_tact: float | None = None
        self.tact_received_at: datetime | None = None
        self.error: str | None = None
        self.closed = False
        self.active = False

    async def async_start(self) -> None:
        topics = bt_topics(self.controller.config.get(CONF_MQTT_TOPIC))
        if topics is None:
            self.error = "MQTT-Topic nicht als ProtoART-Temperatur-Topic erkannt"
            return
        self.topic_last, self.topic_tact = topics
        try:
            self.unsubs.append(await mqtt.async_subscribe(
                self.controller.hass, self.topic_last, self._on_last, qos=0))
            self.unsubs.append(await mqtt.async_subscribe(
                self.controller.hass, self.topic_tact, self._on_tact, qos=0))
            self.active = True
            self.started_at = dt_util.utcnow()
            self.error = None
        except Exception as exc:
            self.error = f"BT MQTT Subscribe: {exc}"
            _LOGGER.warning("ProtoART BT-Monitor: %s", self.error)
            await self.async_stop()
            self.closed = False

    async def async_stop(self) -> None:
        self.closed = True
        self.active = False
        for unsub in self.unsubs:
            unsub()
        self.unsubs.clear()

    @callback
    def _on_last(self, message) -> None:
        if self.closed or not self.active or message.topic != self.topic_last:
            return
        now = dt_util.utcnow()
        if self.tracker.ingest(message.payload, now, retained=bool(getattr(message, "retain", False))):
            # Diagnose aktualisieren; kein unmittelbarer zusätzlicher Hz-Regeltakt.
            async_dispatcher_send(self.controller.hass, self.controller.signal)

    @callback
    def _on_tact(self, message) -> None:
        if self.closed or not self.active or message.topic != self.topic_tact:
            return
        if getattr(message, "retain", False):
            return
        try:
            temperature = float(message.payload)
        except (TypeError, ValueError, OverflowError):
            return
        if math.isfinite(temperature) and -20 <= temperature <= 60:
            self.latest_tact = temperature
            self.tact_received_at = dt_util.utcnow()

    def timeout_seconds(self) -> float:
        return max(120.0, min(7200.0,
            float(self.controller.config.get(CONF_BT_TIMEOUT_MIN, 10.0)) * 60.0))

    def state(self, now: datetime | None = None) -> str:
        if not self.active:
            return "unavailable"
        return self.tracker.status(now or dt_util.utcnow(),
                                   started_at=self.started_at,
                                   timeout_seconds=self.timeout_seconds())

    def snapshot_attrs(self) -> dict:
        now = dt_util.utcnow()
        t = self.tracker
        return {
            "bt_heartbeat_status": self.state(now),
            "bt_last_topic": self.topic_last,
            "bt_tact_topic": self.topic_tact,
            "bt_last_raw": t.raw,
            "bt_last_packet_utc": t.last_packet_at.isoformat() if t.last_packet_at else None,
            "bt_last_contact_utc": t.contact_at.isoformat() if t.contact_at else None,
            "bt_contact_age_s": round(t.contact_age(now), 1) if t.contact_at else None,
            "bt_probable_contact_count": t.reset_count,
            "bt_last_message_count": t.packet_count,
            "bt_last_invalid_count": t.invalid_count,
            "bt_mqtt_tact": self.latest_tact,
            "bt_timeout_min": self.timeout_seconds() / 60.0,
            "bt_monitor_error": self.error,
            "bt_note": "Kontakt aus Last-Zaehler-Reset abgeleitet, nicht per ProtoART-Dokumentation bestaetigt",
        }
