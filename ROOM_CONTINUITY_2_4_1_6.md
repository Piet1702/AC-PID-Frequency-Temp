# AC PID Frequency Temp 2.4.1.6 – Dauerbetrieb und 20-Hz-Schutz

- Erst nach echter Messung von 20 Hz über den konfigurierten Zeitraum: vorsichtige +1-Hz-Korrektur.
- Maximal drei solche Korrekturen (Ziel-Hz höchstens 3 Hz über bevorzugter Dauerfrequenz);
  Mindestabstand 20 Minuten. Die normale Temperaturregelung kann unabhängig davon höhere Hz verlangen.
- 0 Minuten bedeutet: Zusatzschutz deaktiviert (Standard; bitte erst diagnostisch prüfen).
- Bei Überhitzung, Abtauung oder Sensorfehler gibt es keinen Zusatz-Eingriff.
- Stabile Heizfrequenzen werden nur nach ausreichender Beobachtung und mit gemessenen Hz
  gelernt; getrennt nach Außentemperaturzonen gespeichert (auch ohne Außensensor: `unknown`).
- Lernwerte werden über den vorhandenen HA-Store gespeichert. Die Gesamtrücksetzung
  der Lernwerte löscht sie mit. Neustarts setzen laufende 20-Hz-Zeiten zurück.
- Gelernte Werte können beim nächsten Start um maximal +2 Hz zur bevorzugten
  Dauerbetriebsfrequenz verwendet werden. Kein direkter Power-/Setpoint-/MQTT-Befehl.
- Zusatzdiagnose: Sensor `room_continuity` mit Laufzeiten, Zonen und Lernwerten.

**Hinweis:** 20 Hz und 22 Hz sind Anlagen-Erfahrungswerte, keine garantierten
Kompressorgrenzen. 20-Hz-Nähe allein beweist noch keine drohende Abschaltung.
Aktive automatische Regelung zunächst AUS lassen und die Diagnose prüfen.
