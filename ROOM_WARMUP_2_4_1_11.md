# AC PID Frequency Temp 2.4.1.11 – Winter-Aufheizen / 1-min-Check

## Funktionsweise

- Aufheizphase bei >=0,8 K Defizit: Start-Hz als MINDEST-Ziel-Hz, nicht als starre Maximalfrequenz. Tatsächliche Kompressor-Hz duerfen darueber liegen.
- Innerer Hz-PID: Klimaanlagen-Temperatur-Soll bleibt UNVERAENDERT; bei eindeutigem Heizbedarf darf eine hoehere Ist-Hz nicht zu einer immer hoeheren simulierten Temperatur fuehren. Die neue Heizbedarfskappe senkt den simulierten Wert nur schrittweise (max 0,3 K je Regeltakt), bei 1,9 K Defizit bis ca. 0,6 K unter Klimasoll. Die bestehende max_offset-Grenze bleibt erhalten.
- Bei Ist-Hz nahe/oberhalb der vom Nutzer gesetzten automatischen maximalen Ziel-Hz greift die Kappe nicht. Dies ist KEINE harte Geraete-Hz-Begrenzung.
- Sensorstatus `sensor_unchanged`: Der reale Zahlenwert bleibt verfuegbar; die AUSSERE und INNERE Regelung halten ihre zuletzt gueltigen Stellwerte. Keine neuen Lern- oder Hz-Anhebungen ohne neuen echten BT-Bericht. Vorhandene echte Temperatur-Stichproben bleiben erhalten und koennen bei einer spaeteren Meldung einen echten Trend bilden.
- Beobachtungsfenster kann auf **1 Minute** gestellt werden. Das ist eine **Prueffrequenz**, nicht die Freigabe, minuetlich Hz zu erhoehen. Temperaturtrends erfordern weiterhin mindestens 10 Minuten zwischen wirklich empfangenen Messungen. Hz-Erhoehung bei schlechtem bestaetigten Trend maximal +2 Hz alle 5 Minuten.
- Defrost + Recovery und Überhitzungsschutz bleiben prioritaer. Keine Befehle zu HVAC-Power, Klimasollwert oder MQTT-Auswahl.

## Nach dem Update

1. Home Assistant neu starten / Integration neu laden.
2. `number.wohnzimmer_ac_pid_frequency_temp_beobachtungsfenster` in HA **einmalig von 15 auf 1 min** einstellen. Ein gespeicherter HA-Optionswert wird absichtlich nicht durch die Patchdatei ueberschrieben.
3. Die richtige HA-Automation bleibt `automation.send_simulated_temp_new_pid_control`. Die alte Automation nicht umstellen. NUR eine Automation darf auf das ProtoART-Temperaturtopic schreiben.
4. Live-Diagnose: `heat_demand_guard_active`, `heating_simulated_ceiling_c` sind zusaetzliche Attribute von `sensor.wohnzimmer_ac_pid_frequency_temp_status`.

## Grenzen

Ein change-only-BT-Sensor besitzt kein nachweisbares Heartbeat-Signal. Aus langer Funkstille kann keine echte Temperaturkonstanz abgeleitet werden; deswegen keine blind aggressiveren Heizanforderungen.
Eine 1-Minuten-Prueffrequenz ersetzt keinen verifizierten, laengeren Praxistest. Um 1.9 K Defizit wird die simulierte Temperatur schrittweise abgesenkt; die resultierende Ist-Hz ermittelt das MHI-Geraet selbst. Auf reale Frequenzspitzen und Raumuebertemperaturen achten.
