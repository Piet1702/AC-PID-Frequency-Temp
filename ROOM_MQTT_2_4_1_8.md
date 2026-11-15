# AC PID Frequency Temp 2.4.1.8 – Aufheizen, Lovelace, MQTT

## Änderungen

- Aufheiz-Startfrequenz und bevorzugte **Dauerbetriebs-Untergrenze** getrennt.
- Automatische Maximal-Hz bis 90 Hz konfigurierbar. Keine Behauptung über zulässige Anlagenwerte.
- Bei kaltem Raum Start mit Start-Hz; bei Zielannäherung vorsichtige Hz-Absenkung.
- MQTT-Takt pollt sekündlich, veröffentlicht nach Aktivieren sofort und danach im konfigurierten Intervall (Standard 5 s); kein Kopplung mehr an Restart oder 60-s-Regeltakt.
- Zahl-/Text-/Schalteroptionen ohne kompletten Reload; Änderungen der ausgewählten Eingangs-Entitäten und des Basistaktes lösen weiterhin einen Reload aus.
- Neue Anzeige in der Custom-Karte: Raumtemperaturmodus mit *Raumziel*, echte und simulierte Temperatur, Start-/Dauer-/Max-Hz und begründete Entscheidung. Im Raumtemperaturmodus ändern +/- das Raumziel, niemals den Klima-Sollwert.
- Zusätzliche MQTT-Diagnose zum tatsächlichen Abstand der letzten Veröffentlichungen.
- Die Klimaanlage wird nicht automatisch ein- oder ausgeschaltet. Silent bleibt eigenständig.

## Erstkonfiguration nach Update

1. HA neu starten, Regler ausgeschaltet lassen. Neue Entität **Startfrequenz Aufheizen** auf 45 Hz setzen.
2. **Bevorzugte Dauerbetriebsfrequenz** auf 22 Hz zurücksetzen (in 2.4.1.7 stand sie ggf. auf 45 Hz).
3. **Maximale automatische Hz** zunächst auf 70 Hz setzen, nur wenn für deine Anlage geeignet.
4. Raumziel 21 °C und Beobachtung 15 min vorerst beibehalten.
5. Prüfen, dass alter Hz-Regler und alte MQTT-Automation aus sind, bevor neuer MQTT-Versand eingeschaltet wird.
6. In MQTT Diagnose `publish_count`, `last_publish_interval_s`, `last_publish_utc`, `last_error` ansehen. `sent` besagt **nicht**, dass ProtoART empfangen hat.

## Tests

`py -3 tests/test_room_mqtt_218.py`

## Sicherheitsverhalten

- Bei Abtauung, fehlendem BT-Raumwert und erreichten Überheizungsgrenzen gelten die bisherigen Sperren.
- Ein durch MQTT nicht bestätigter Versand ist keine Garantie für eine Zustellung.
- Benutzerseitiges Ausschalten bleibt Vorrang. Keine MQTT-Power-Topics im Update.
