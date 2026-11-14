# AC PID Frequency Temp 2.4.1.5 – adaptive Raumregelung (Pilot)

Neuer Regelmodus `room_auto`: Nach Moduswechsel und nach HA-Neustart bleibt die
Regelung aus, bis der Benutzer den bestehenden Schalter `Hz-Regelung` aktiviert.
Das verhindert ein unerwartetes Umschalten der Wärmequelle.

- Initiale Anforderung: bevorzugte Dauerbetriebs-Hz (Standard 22 Hz).
- Nach gültigem Beobachtungsfenster: max. 1 Hz runter oder 2 Hz hoch.
- Nahe an Ziel (weniger als 0,5 K Abstand): doppeltes Intervall, max. 1 Hz Änderung.
- Auto-Hz-Limit: Standard 40 Hz, nativ einstellbar (20–60 Hz).
- Nicht unter die bevorzugten Dauerbetriebs-Hz; Ausnahme: bei Überschreiten
  von Zieltemperatur + Überhitzungstoleranz wird Wärmebedarf über den simulierten
  Temperatursensor reduziert. **Keine** MQTT-Power-Befehle.
- Wärmebedarf wird erst bei Raumtemperatur <= Ziel − Wiederanlauf-Delta angefordert.
- Keine aktiven Änderungen bei Abtauung, zehnminütiger Erholung oder unfrischen
  Messwerten. Bei Sensorausfall wird der simulierte Sensor `unavailable`.
- Automatische Ziel-Hz-Änderungen lösen keinen *Benutzer-Trigger* zum Reset der
  Mindestmodulations-Lernwerte aus.
- Der Überhitzungsschutz des Hz-Reglers bezieht sich im Auto-Modus auf die
  Raumtemperatur und die konfigurierbare Überhitzungstoleranz.
- Diagnose: `Raumregelung – Automatikstatus`, inkl. Begründung und nächster Prüfung.

WICHTIG: Die Temperaturführung ist ein vorsichtiger Pilot, noch keine erlernte
thermische Gebäudecharakteristik und keine Silent-Steuerung. 20 Hz bzw. die
bevorzugte Dauerfrequenz garantieren keinen kontinuierlichen Betrieb. Die Anlage
entscheidet weiterhin selbst über den Kompressorbetrieb.

Bis zur gezielten Umschaltung: Originalregler und alte MQTT-Automation aktiv
lassen; Auto-Regler im Fork AUS. Erst nach vollständiger Umstellung nur eine
Integration und ein MQTT-Publisher aktiv steuern lassen. Nach dem Ausrollen
unbedingt zunächst die Diagnose bei ausgeschalteter Automatik prüfen.
