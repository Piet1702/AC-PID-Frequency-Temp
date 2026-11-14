"""MQTT safety/diagnostics regression tests for AC PID Frequency Temp."""
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.util import dt as dt_util
from custom_components.ac_pid_frequency_temp.const import (
    CONF_MQTT_ENABLED,
    CONF_MQTT_TOPIC,
    CONF_ROOM_STALE,
)
from custom_components.ac_pid_frequency_temp.protoart_mqtt import (
    room_sensor_snapshot,
    valid_publish_topic,
)


def test_validate_mqtt_topic():
    assert valid_publish_topic("climacontrol/HVAC_9C2FDC/sensor/external/temperature/set")
    for bad in ("", "foo/#", "foo/+", " leading", "trailing ", "x\x00y"):
        assert not valid_publish_topic(bad)


async def test_room_sensor_reports_and_staleness(hass):
    hass.states.async_set("sensor.test_bt", "21.25")
    status, age, timestamp = room_sensor_snapshot(hass, "sensor.test_bt", 300)
    assert status == "ok" and age is not None and timestamp is not None
    assert room_sensor_snapshot(hass, "sensor.missing", 300)[0] == "missing"
    hass.states.async_set("sensor.test_bt", "unavailable")
    assert room_sensor_snapshot(hass, "sensor.test_bt", 300)[0] == "invalid"


async def test_mqtt_never_sends_without_fresh_sensor(hass):
    from types import SimpleNamespace
    from custom_components.ac_pid_frequency_temp.protoart_mqtt import ProtoArtMqttBridge
    hass.states.async_set("sensor.bt_test", "unavailable")
    cfg = {
        CONF_MQTT_ENABLED: True,
        CONF_MQTT_TOPIC: "climacontrol/test/sensor/external/temperature/set",
        CONF_ROOM_STALE: 300,
        "room_temp_entity": "sensor.bt_test",
    }
    controller = SimpleNamespace(hass=hass, signal="test_mqtt_signal", config=cfg,
                                 available=True, output=20.4)
    bridge = ProtoArtMqttBridge(controller)
    with patch("custom_components.ac_pid_frequency_temp.protoart_mqtt.mqtt.async_publish", new_callable=AsyncMock) as publish:
        await bridge.async_tick()
    publish.assert_not_awaited()
    assert bridge.state == "room_invalid"


async def test_mqtt_publishes_controller_value_when_valid(hass):
    from types import SimpleNamespace
    from custom_components.ac_pid_frequency_temp.protoart_mqtt import ProtoArtMqttBridge
    hass.states.async_set("sensor.bt_test", "21.1")
    cfg = {CONF_MQTT_ENABLED: True,
           CONF_MQTT_TOPIC: "climacontrol/test/sensor/external/temperature/set",
           CONF_ROOM_STALE: 300,
           "room_temp_entity": "sensor.bt_test"}
    controller = SimpleNamespace(hass=hass, signal="test_mqtt_signal", config=cfg,
                                 available=True, output=20.4)
    bridge = ProtoArtMqttBridge(controller)
    with patch("custom_components.ac_pid_frequency_temp.protoart_mqtt.mqtt.async_publish", new_callable=AsyncMock) as publish:
        await bridge.async_tick()
    publish.assert_awaited_once_with(
        hass, "climacontrol/test/sensor/external/temperature/set", "20.4", qos=0, retain=False
    )
    assert bridge.state == "sent"
    assert bridge.publish_count == 1
