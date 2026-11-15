# AC PID Frequency Temp 2.4.1.9 – MQTT via HA-Automation

## Konzept

Die bestehende Home-Assistant-Automation veröffentlicht alle 5 Sekunden die simulierte Raumtemperatur. Die Integration schaltet diese Automation über den bisherigen MQTT-Schalter ein/aus und **beobachtet** zusätzlich die auf dem konfigurierten Topic eintreffenden Nachrichten via MQTT-Subscription.

### Konfiguration

1. Den bisherigen direkten MQTT-Schalter ausschalten.
2. **MQTT-Ausgabemethode** auf `automation` stellen.
3. Unter **MQTT-Automation auswählen** die existierende Automation (`automation.…`) auswählen.
4. Temperatur-Topic `climacontrol/HVAC_9C2FDC/sensor/external/temperature/set` beibehalten.
5. In der Automation muss der Payload auf `sensor.wohnzimmer_ac_pid_frequency_temp_simulierte_raumtemperatur` zeigen. Keine `unknown`- oder `unavailable`-Payloads senden; für die Automation ist ggf. eine Bedingung notwendig.
6. Der bisherige Schalter **MQTT-Temperaturversand** steuert nun die Automation. Falls diese bereits `on` ist, zeigt der Schalter ebenfalls `on`.

### Diagnose

- Im Automationsmodus zählt `observed_message_count` nur **am MQTT-Broker beobachtete** Nachrichten; `publish_count` ist `null`, weil die Integration nicht selbst veröffentlicht.
- `last_publish_interval_s` bezeichnet im Automationsmodus den Abstand zweier beobachteter MQTT-Pakete, nicht den Zeitpunkt eines eigenen Publish-Aufrufs.
- `last_payload`, `last_publish_utc` und `last_publish_age_s` beziehen sich im Automationsmodus auf Broker-Empfang.
- Meldung `delayed` nach längerer Lücke, `automation_off` bei abgeschalteter Automation.
- Ein identischer Wert kann weiterhin wiederholt übertragen werden. Eine abgelaufene Home-Assistant-Sensorzeit (`room_stale`) wird getrennt ausgewiesen und **unterbricht den Automations-Monitor nicht**. Damit ist die Frische des echten Bluetooth-Sensors **nicht** bewiesen. Die adaptive Hz-Regelung behält ihre bestehenden Schutzbedingungen.
- Ein auf dem Topic gesehenes Paket lässt sich nicht mit Sicherheit der ausgewählten Automation zuordnen; ebenso wenig bestätigt es, dass ProtoART es angewendet hat.
- `mqtt_topic` und `mqtt_interval_s` müssen zur tatsächlichen Automation passen. Die Integration verändert den Automation-YAML-Inhalt nicht.
- Keinerlei MQTT-Befehle zum Ein-/Ausschalten der Klimaanlage.

### Tests

`py -3 tests/test_automation_mqtt_pure.py`
