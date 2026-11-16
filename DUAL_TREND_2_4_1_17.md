# AC PID Frequency Temp 2.4.1.17 – Dualer Temperaturtrend

## Was neu ist

- Zwei gleichzeitige Trendberechnungen aus **derselben** echten BT-Kontakthistorie:
  - **Kurztrend (15 Minuten)** für eine **vorzeitige Leistungsreduzierung** beim Annähern an den Raum-Sollwert.
  - **Langtrend (mindestens 30 Minuten)** für normale Aufheizdauer- und Hz-Entscheidungen. Ist der Langtrend noch nicht zuverlässig, darf der zuverlässige Kurztrend übergangsweise als Ausgangsbasis dienen.
- Die bestehende UI-Einstellung „Trend-Auswertefenster“ bleibt für den bisherigen Trendsensor erhalten. Für den separaten Langtrend werden mindestens 30 Minuten betrachtet, selbst wenn der bisherige Sensor auf 15 Minuten eingestellt ist.
- Die Schnellbremse greift nur bei geprüftem Raumtemperaturwert und **zuverlässigem** Kurztrend; beim bereits erreichten Sollwert genügt der geprüfte Temperaturwert. Sie kann **niemals die Ziel-Hz erhöhen**.
- Innerhalb von 0,5 K vor dem Ziel: Schnellbremse nur dann, wenn ein positiver Kurztrend eine Annäherung an das Ziel innerhalb von ca. 30 Minuten signalisiert. Vorzeitige Reduzierungen sind auf maximal einen Impuls je drei Minuten begrenzt; an die reale Kompressorfrequenz gekoppelte Anti-Windup-Sperre bleibt erhalten.
- Unverändert: Die Anlage darf vom Regler **nicht ein-/ausgeschaltet** werden. Es werden weder MQTT-Befehle noch Klima-Sollwerte direkt geschrieben; der originale innere Frequenzregler stellt weiterhin die simulierte Temperatur ein.
- BT-Timeout, Abtauung, Hysterese/Überhitzungsgrenze, Mindest-Hz-Hotfix und maximale automatische Ziel-Hz bleiben unangetastet.

## Neue Diagnosedaten

Über Attribute des bestehenden `sensor.…_raumregelung_beobachtungsphase`:

- `short_trend_kph`, `short_trend_quality`, `short_samples`, `short_span_minutes`
- `long_trend_kph`, `long_trend_quality`, `long_samples`, `long_span_minutes`

Über den bestehenden `sensor.…_adaptive_raumregelung_status`:

- `last_decision_trend_kph` – **exakt der Trend, der für die letzte Hz-Entscheidung verwendet wurde**
- `last_decision_trend_source`: `long`, `short_fallback`, `short_brake` oder `target_reached`
- `last_decision_time_utc` – Zeitstempel der letzten Hz-Entscheidung
- `last_decision_room_c` – Raumtemperatur zum Entscheidungszeitpunkt
- `fast_brake_qualified`, `fast_brake_reason`, `last_fast_brake_utc`

`forecast_room_temp_45min` ist weiterhin die Prognose **der letzten Hz-Entscheidung**, nicht eine kontinuierlich aktualisierte Live-Prognose. Die ergänzte Diagnose stellt Live-Werte und Entscheidungswerte getrennt dar.

## Hinweise zur Aufheizdauer

Die bereits vorhandene Einstellung `number.wohnzimmer_ac_pid_frequency_temp_gewunschte_aufheizdauer` bleibt korrekt und wird **nicht umbenannt**.

Empfohlener Teststart: 150–360 min je gewünschtem Tempo, 5 min Regelprüfung, 15 min bisheriges Trendfenster (Langtrend läuft separat mit 30 min), 22 Hz Dauerbetrieb, 50 Hz maximale virtuelle Ziel-Hz. Das Hz-Maximum ist keine harte physikalische Kompressor- oder Leistungsbegrenzung.

## Installation

Das Installationsskript erwartet **Version 2.4.1.16** und ein `.git`-Repository. `--dry-run` prüft alle Textanker und Python-/JSON-Syntax ohne Dateiänderung. Backups werden im Erfolgsfall unter `.git/ac_pid_backup_2_4_1_17/` angelegt. Alle Patches erfolgen ohne Änderung der MQTT-Automation. Der Test in einer nachgebildeten Umgebung ersetzt keinen Home-Assistant-Praxistest.
