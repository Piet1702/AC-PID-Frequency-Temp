# AC PID Frequency Temp 2.4.1.10 – Change-only Bluetooth und MQTT

## Fehlerkorrekturen

- Ein numerisch gueltiger Raumtemperaturwert wird bei ausbleibender erneuter Meldung nicht mehr nach 300 Sekunden `unavailable`.
- Sensordiagnose: `unchanged` statt `stale`; die Reportzeit bleibt sichtbar. Bei unveraendertem Sensorwert keine Trendberechnung, keine automatische Hz-Anhebung, kein neues Lernen und kein 20-Hz-Schutz-Eingriff. Beim naechsten frischen Messwert beginnt das Beobachtungsfenster neu.
- Ausdruecklich `unknown`/`unavailable`, ungueltige Zahlen oder fehlende Entitaeten bleiben Fehler. Die obere Temperaturgrenze bleibt aktiv, falls der letzte bekannte Wert bereits zu hoch ist.
- MQTT-Broker-Monitor: `@callback` fuer `_message_received`, damit Home Assistant ihn auf dem Event Loop statt in SyncWorker aufruft.
- Die HA-Automation muss separat gueltige Zahlen filtern: Die Integration kann ihre Publish-Aktionen nicht nachtraeglich blockieren.

## Richtige Automation fuer die neue PID-Version

`automation.send_simulated_temp_new_pid_control`

Die Automation kann nicht durch eine Git-Dateiaenderung in der bereits gespeicherten Home-Assistant-Konfiguration umgestellt werden. Nach dem Update unter MQTT-Sendeautomatisierung die neue PID-Automation waehlen, **nicht** die alte.

Beide Automationen duerfen nicht gleichzeitig dasselbe Temperatur-Topic senden. Zur Kontrolle in Home Assistant MQTT-Monitor `climacontrol/HVAC_9C2FDC/sensor/external/temperature/set` verwenden.

## Sicherheitsgrenze

Ein change-only BLE-Sensor liefert keine Heartbeat-Meldung. Aus fehlenden Updates laesst sich daher kein sicherer Verbindungszustand ableiten. Ohne neue Meldung wird **keine zusaetzliche Heizleistung angefordert**, aber das bereits laufende Heizniveau nicht blind geaendert. Bei unsicherer Quellverbindung Regler stoppen und Ursache beheben.
