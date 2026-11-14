# AC PID Frequency Temp 2.4.1.2 — ProtoART MQTT & Diagnose

## Funktionsumfang

- Option **Konfigurieren → ProtoART MQTT & Sensordiagnose**: Aus/Ein, Topic, Intervall 5–60 s, QoS 0–2, Retain, Sensor-Verfallszeit (Standard 300 s).
- Veröffentlichung der bestehenden **simulierten Raumtemperatur** in 0,1-°C-Schritten; keine Änderung der Hz-Regelung.
- **Vier neue Diagnosesensoren**: MQTT-Sendestatus, Zeitpunkt letzte MQTT-Veröffentlichung, Raumsensor-Status, Raumsensor-Alter.
- Keine aktive MQTT-Steuerung von Klima-Power oder Silent-Modus; diese Funktionen folgen in späteren Versionen.
- MQTT ist **standardmäßig deaktiviert**, um nicht parallel zur vorhandenen Automation zu senden.

## Sichere Umstellung

1. Home Assistant neu starten nach Installation der neuen Version.
2. Unter Einstellungen → Geräte & Dienste → AC PID Frequency Temp → Konfigurieren die Option **ProtoART MQTT & Sensordiagnose** öffnen.
3. Topic z. B. `climacontrol/HVAC_9C2FDC/sensor/external/temperature/set`, Intervall 5 s, QoS 0, Retain aus, BT-Timeout 300 s eintragen. Zunächst MQTT **aus** lassen.
4. Unter den Entitäten die vier Diagnosesensoren prüfen. Die diagnostischen Entitäten werden ggf. unter „Diagnose“ angezeigt.
5. Alte MQTT-Automation in Home Assistant **deaktivieren** und erst anschließend die neue MQTT-Ausgabe aktivieren. Nicht beide Publisher gleichzeitig verwenden.
6. MQTT-Sendestatus `sent` heißt: Der Home-Assistant-MQTT-Client hat den Publish-Aufruf angenommen. Es ist **keine Bestätigung**, dass das ProtoART-Gerät die Temperatur verarbeitet hat.
7. Bei ungültigem, altem oder fehlendem BT-Raumsensor und bei nicht verfügbarer simulierter Temperatur stoppt die MQTT-Ausgabe. ProtoART kann auf seine interne Messung zurückfallen.

## Diagnose

- `room_sensor_status`: `ok`, `stale`, `missing`, `invalid`, `not_configured`.
- `room_sensor_age`: Sekunden seit dem letzten von HA protokollierten Report. Falls verfügbar wird `last_reported` verwendet, ansonsten `last_updated`. Dies ist **nicht zwangsläufig** der BLE-Funk-Empfangszeitpunkt.
- `mqtt_status`: `disabled`, `sent`, `room_stale`, `room_invalid`, `room_missing`, `output_unavailable`, `invalid_topic`, `mqtt_error`.
- `mqtt_last_publish`: letzte von HA akzeptierte Publikation. Im MQTT-Status stehen auch `publish_count`, `last_payload`, `last_error`, `topic`.

## Test

```bash
python -m pytest tests/test_protoart_mqtt.py
```

Benötigt wie das bestehende Projekt `pytest-homeassistant-custom-component`. Echtbetrieb/ProtoART-Empfang muss nach Installation separat getestet werden.
