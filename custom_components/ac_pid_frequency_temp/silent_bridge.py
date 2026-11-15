"""ProtoART Silent-MQTT-Bruecke: ausschliesslich silent_mode/set.

Keine Power-, Klima-Modus- oder Klimasolltemperatur-Aktionen.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from homeassistant.components import mqtt
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLIMATE, CONF_CONTROL_MODE, CONF_PREFERRED_HZ,
    CONF_ROOM_OBSERVE_WINDOW, CONF_ROOM_TARGET, CONF_ROOM_STALE, CONF_ROOM_TEMP, CONF_SILENT_MODE,
    CONF_SILENT_TOPIC, CONF_SILENT_BOOST_MINUTES, MODE_ROOM_AUTO,
)
from .silent_policy import SilentPolicy, DISABLED
from .protoart_mqtt import valid_publish_topic, room_sensor_snapshot

_LOGGER = logging.getLogger(__name__)


def valid_silent_topic(topic: str) -> bool:
    return (
        isinstance(topic, str) and valid_publish_topic(topic)
        and topic.endswith("/heatpump/silent_mode/set")
    )


class ProtoArtSilentBridge:
    """Sends commands only on deliberate configuration & with valid heating state."""

    def __init__(self, controller) -> None:
        self.controller = controller
        self.policy = SilentPolicy()
        self._unsubscribe = None
        self._subscribed_topic: str | None = None
        self._busy = False
        self._stopped = False
        self.confirmed: str | None = None
        self.last_requested: str | None = None
        self.last_sent_at: datetime | None = None
        self.last_confirmed_at: datetime | None = None
        self.last_error: str | None = None
        self.attempts = 0
        self.state = "disabled"
        self.reason = "Silent-Steuerung deaktiviert"
        self.boost_left_min = 0.0

    async def async_stop(self) -> None:
        self._stopped = True
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._subscribed_topic = None

    def _on_message(self, msg) -> None:
        if self._stopped:
            return
        raw = msg.payload
        payload = (raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)).strip().lower()
        if payload in ("on", "1", "true"):
            self.confirmed = "on"
        elif payload in ("off", "0", "false"):
            self.confirmed = "off"
        else:
            return
        self.last_confirmed_at = dt_util.utcnow()
        if self.confirmed == self.last_requested:
            self.attempts = 0
        async_dispatcher_send(self.controller.hass, self.controller.signal)

    async def _subscribe(self, topic: str) -> bool:
        status_topic = topic.removesuffix("/set")
        if self._subscribed_topic == status_topic:
            return True
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
            self._subscribed_topic = None
        try:
            self._unsubscribe = await mqtt.async_subscribe(
                self.controller.hass, status_topic, self._on_message, qos=0
            )
            self._subscribed_topic = status_topic
            return True
        except Exception as exc:
            self.last_error = f"Silent-Statusabo fehlgeschlagen: {exc}"
            _LOGGER.warning("ProtoART Silent: %s", self.last_error)
            return False

    async def async_start_boost(self) -> None:
        cfg = self.controller.config
        if cfg[CONF_SILENT_MODE] not in ("always_silent", "auto"):
            raise ValueError("Boost nur in 'Immer Silent' oder 'Automatisch' verfuegbar")
        if not self.controller.enabled:
            raise ValueError("Zuerst den Hz-Regler aktivieren")
        self.policy.start_manual_boost(dt_util.utcnow(), int(cfg[CONF_SILENT_BOOST_MINUTES]))
        await self.async_tick()

    async def async_stop_boost(self) -> None:
        self.policy.cancel_boost(dt_util.utcnow())
        await self.async_tick()

    async def async_tick(self) -> None:
        if self._busy or self._stopped:
            return
        self._busy = True
        try:
            await self._run_tick()
        finally:
            self._busy = False
            async_dispatcher_send(self.controller.hass, self.controller.signal)

    async def _run_tick(self) -> None:
        cfg = self.controller.config
        mode = cfg.get(CONF_SILENT_MODE, DISABLED)
        topic = str(cfg.get(CONF_SILENT_TOPIC) or "").strip()
        if mode == DISABLED:
            self.state, self.reason = "disabled", "Silent-Modus nicht gesteuert"
            self.boost_left_min = 0.0
            return
        if not valid_silent_topic(topic):
            self.state, self.reason = "topic_missing", "Silent-MQTT-Topic fehlt oder ist ungueltig"
            return

        climate = self.controller.hass.states.get(cfg[CONF_CLIMATE])
        heating = bool(climate and climate.state == "heat")
        # Do not send during defrost/recovery or when room measurements are stale.
        observation = self.controller.room_observer.snapshot
        phase = observation.phase
        # Check real sensors and defrost directly on every 30-second silent tick,
        # not only after the slower outer-loop observation catches up.
        try:
            if self.controller._read_defrost(climate):
                phase = "defrost"
        except (TypeError, ValueError, AttributeError):
            phase = "sensor_missing"
        room_id = cfg.get(CONF_ROOM_TEMP)
        sensor_status, _age, _stamp = room_sensor_snapshot(
            self.controller.hass, room_id, float(cfg[CONF_ROOM_STALE])
        )
        if sensor_status != "ok" and phase not in ("defrost", "recovery"):
            phase = "sensor_stale" if sensor_status == "stale" else "sensor_missing"
        if cfg[CONF_CONTROL_MODE] != MODE_ROOM_AUTO:
            # The pure Hz mode has no observer measurements; still ensure that
            # defrost / sensor errors are handled when the observer detects them.
            phase = phase if phase in ("defrost", "recovery", "sensor_stale", "sensor_missing") else "manual_frequency"
        auto = self.controller.room_auto
        plan = self.policy.decide(
            now=dt_util.utcnow(), mode=mode, enabled=self.controller.enabled,
            heating=heating, phase=phase,
            room_temp=observation.room_temp if cfg[CONF_CONTROL_MODE] == MODE_ROOM_AUTO else None,
            target_temp=float(cfg[CONF_ROOM_TARGET]),
            trend_kph=observation.trend_kph if cfg[CONF_CONTROL_MODE] == MODE_ROOM_AUTO else None,
            window_minutes=observation.window_minutes,
            observation_minutes=float(cfg[CONF_ROOM_OBSERVE_WINDOW]),
            target_hz=auto.decision.target_hz if cfg[CONF_CONTROL_MODE] == MODE_ROOM_AUTO else None,
            preferred_hz=float(cfg[CONF_PREFERRED_HZ]),
        )
        self.state, self.reason, self.boost_left_min = plan.state, plan.reason, plan.boost_left_min
        if plan.desired is None:
            return
        if not await self._subscribe(topic):
            self.state = "mqtt_error"
            return
        now = dt_util.utcnow()
        if self._stopped:
            return
        # Observed actual state wins; do not repeatedly publish a command when
        # there is already explicit confirmation from the device.
        if self.confirmed == plan.desired:
            return
        if self.last_requested != plan.desired:
            self.attempts = 0
        elif self.last_sent_at and (now - self.last_sent_at) < timedelta(seconds=120):
            return
        if self.attempts >= 3 and self.last_requested == plan.desired:
            self.state, self.reason = "unconfirmed", "Nach drei Versuchen kein bestaetigter MQTT-Status"
            return
        try:
            await mqtt.async_publish(
                self.controller.hass, topic, plan.desired, qos=0, retain=False
            )
        except Exception as exc:
            self.last_error = f"Silent-MQTT-Publish fehlgeschlagen: {exc}"
            self.state = "mqtt_error"
            _LOGGER.warning("ProtoART Silent: %s", self.last_error)
            return
        self.last_requested = plan.desired
        self.last_sent_at = now
        self.attempts += 1
        self.last_error = None
