# AC PID Frequency Temp 2.4.1.13 – Trend und BT-Topics

- Trend-Auswertefenster neu: 30 Minuten (15–90 Minuten einstellbar); der vorhandene 1–60-Minuten-Prueftakt bleibt unabhaengig.
- Lineare Ausgleichsgerade ueber unterschiedliche BT-Kontaktzeitpunkte; ein einzelner 0,1-K-Sprung dominiert nicht mehr die gesamte Trendberechnung.
- Trend-Qualitaet: `collecting`, `low_confidence`, `reliable`. In der Beobachtungsdiagnose wird die Anzahl der Wechsel zu numerischem `unknown` in den letzten 30 Minuten (`trend_unknown_entries_30m`) gezaehlt, nur seit Integrationsstart. Pausen und fehlende BT-Werte sind darin enthalten. **Nur `reliable` darf trendbasierte Hz-Anpassungen und thermische Lernvorgaenge ausloesen.** Die Temperatur-Obergrenze und das vorsichtige Absenken beim Erreichen des Raumziels gelten unabhaengig davon. `low_confidence` darf als vorlaeufiger Zahlenwert angezeigt werden.
- Zuverlässigkeit ab 75 % zeitlicher Abdeckung, mindestens 8 Punkten und ohne lange Luecken. Nach Neustart beginnt das RAM-Fenster erneut mit `collecting`.
- Sicherheit: Unverfuegbare BT-Signale, Abtau-/Erholungsphasen und Heizstopps bleiben gesperrt. Erreichen der Solltemperatur hat auch ohne zuverlaessigen Trend Vorrang vor weiterem Aufheizen.
- Zwei optionale Textfelder: `BT-Kontakt-Topic`, `BT-Temperatur-Topic`. Leer = automatisch vom Haupt-MQTT-Topic ableiten; die Entitaeten zeigen den effektiven Topic-Pfad. Aenderungen bewirken einen Integrations-Reload.
- Keine Veraenderung der ausgewählten Home-Assistant-Automation `automation.send_simulated_temp_new_pid_control`. Keine MQTT-Publish-, Power-, Mode- oder Climate-Setpoint-Befehle in diesem Update.
- MQTT `thermometer/last` wird weiterhin nur als **vermuteter** Bluetooth-Kontakt (Ruecksprung des Zaehlers) interpretiert und nicht als garantierte Herstellerinformation.

Tests: `py -3 tests/test_room_trend_2_4_1_13.py`
Dry-run: `py -3 update_ac_pid_temp_2_4_1_13.py --dry-run`
