# AC PID Frequency Temp 2.4.1.14 – Raumwärmebedarf ↔ Hz-Regler

## Fehlerbild (v2.4.1.13)
Bei realen 20,3 °C, Ziel 21 °C, Trend +0,267 °C/h, tatsächlicher
Kompressorfrequenz 54 Hz, Ziel 39 Hz und simulierter Temperatur 20 °C
bewertete die Raumautomatik den Raum als „nahe am Ziel“ und reduzierte die
Ziel-Hz, obwohl bis 21 °C rechnerisch noch etwa 2,6 Stunden fehlten.
Damit versuchte der unveränderte innere Frequenzregler die Frequenz weiter
zu senken, statt über eine niedrigere simulierte Temperatur mehr Wärme
anzufordern. Die 58-Hz-*Startfrequenz* ist keine dauerhafte Untergrenze.

## Neue Regelung

- Die robuste Regression und die 30-Minuten-BT-Trendqualität aus 2.4.1.13
  bleiben vollständig erhalten.
- Die Raumautomatik nutzt einen auf 45 Minuten begrenzten Kurzfrist-Forecast
  (`Raumtemp + Trend * 0,75 h`). Der Trend wird für den Forecast auf
  ±1,5 °C/h begrenzt.
- Wenn die Prognose noch mindestens 0,3 K unter Ziel liegt und noch
  mindestens 0,25 K Wärmebedarf besteht, kann bei `reliable` und gültiger
  BT-Messung alle fünf Minuten vorsichtig mehr Wärme angefordert werden.
- Wenn die **bisherige Ziel-Hz unter der tatsächlichen Kompressorfrequenz**
  liegt, wird die virtuelle Ziel-Hz bei einer echten Anhebung zunächst
  auf maximal Ist-Hz + 3 gebracht. Das überwindet die ±2-Hz-Totzone des
  **unveränderten** inneren Hz-Reglers, der daraufhin die simulierte
  Temperatur in 0,1-K-Schritten absenken kann.
- **Anti-Windup:** Liegt das virtuelle Ziel bereits bei mindestens Ist-Hz + 3,
  wird es nicht weiter angehoben, solange der echte Kompressor nicht folgt.
  Bei fehlendem/stehendem Kompressor-Istwert wird nicht blind angehoben.
- Beim rechtzeitigen Drosseln kann ein virtuelles Ziel analog einmalig bis
  auf Ist-Hz − 3 abgesenkt werden, damit auch die Reduktion die 2-Hz-Totzone
  des inneren Reglers überwindet; danach wartet der äußere Kreis ebenfalls
  auf die reale Reaktion. Die Temperaturänderung selbst bleibt beim inneren PID.
- Diese Hz-Angleichung ist **kein direkter Kompressorfrequenzbefehl**.
  Wie die Anlage reagiert, hängt von ProtoART/MHI ab.
- Eine vorsorgliche Ziel-Hz-Senkung erfolgt erst, wenn die 45-Minuten-Prognose
  bis auf 0,1 K an die Zieltemperatur heranreicht; ein tatsächliches
  Erreichen des Raumziels reduziert ebenfalls die Wärmeanforderung.
- Bei ≤0,25 K Restabstand wird die Prüfzeit weiterhin konservativ verdoppelt.
  Zwischen 0,25 und 0,7 K gilt nun wieder der reguläre Prüftakt (5 min).
- Konfiguriertes Maximum (z. B. 70 Hz), BT-Timeout, Abtau-/Recovery-Pause,
  Hysterese, Überhitzungsgrenze, Mindestmodulation, MQTT-Automation und
  Klima-Sollwert bleiben unangetastet.
- Zusatzdiagnose als Attribute des bestehenden Raumautomatik-Sensors:
  `forecast_room_temp_45min`, `forecast_room_deficit_45min_k`,
  `aligned_target_to_actual_hz`, `actual_hz_at_last_room_decision`,
  `coupling_enabled`.

## Sicherheits-/Praxishinweis

Die 45-Minuten-Prognose ist eine einfache Entscheidungshilfe, keine
physikalische Simulation oder Garantie gegen thermisches Überschwingen.
Bitte die ersten Regelentscheidungen und den realen Kompressorverlauf
beaufsichtigen. Bei unerwarteten Temperaturen/Lastwechseln PID-Schalter
ausschalten; der bestehende Durchreichmodus verwendet dann den echten
Raumsensor. Klima-Betriebsart und Sollwert werden vom Patch nicht verändert.

Die **Start-Hz** nach dem Test auf den bewährten Wert (45 Hz) zurücksetzen.

## Installation / Prüfung

`py -3 update_ac_pid_temp_2_4_1_14.py --dry-run`

`py -3 update_ac_pid_temp_2_4_1_14.py`

`py -3 tests/test_room_demand_2_4_1_14.py`

`py -3 -m compileall -q custom_components/ac_pid_frequency_temp`

Danach Git-Commit, Push, HACS-Update und Home-Assistant-Neustart.
Kein echter HVAC-/MQTT-Test im Installer; Regressionen verwenden Pure-Python-
Komponenten und tatsächliche Integrationsklasse `RoomAutoController`.
