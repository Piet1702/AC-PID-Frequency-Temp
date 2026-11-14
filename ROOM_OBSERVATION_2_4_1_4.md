# AC PID Frequency Temp – 2.4.1.4: Beobachtungsmodus

**Nur Beobachtung, noch keine adaptive Heizregelung.**

Neue Home-Assistant-Entitäten:

- Auswahl `Regelmodus`: `frequency` (bisherige Hz-Regelung) und
  `room_observe` (Raumtemperatur nur beobachten).
- Number `Ziel-Raumtemperatur` (Standard 21 °C).
- Number `Bevorzugte Dauerbetriebsfrequenz` (Standard 22 Hz).
- Number `Überheizungstoleranz` (Standard +2 K).
- Number `Wiedereinschalt-Referenz` (Standard −0,5 K; KEIN Einschaltbefehl).
- Number `Beobachtungsfenster` (Standard 30 Minuten).
- Diagnose: Raumregelungsphase, Temperaturtrend °C/h, Temperaturabweichung,
  beobachtende Empfehlung, Zeit bei ca. 20 Hz.

`room_observe` schaltet einen ggf. aktiven Hz-Regler aus. Zusätzlich wird
in diesem Modus der integrierte MQTT-Versand pausiert, auch wenn der MQTT-
Schalter eingeschaltet war. Die simulierte Temperatur wird nicht berechnet,
sondern die echte Raumtemperatur durchgereicht, sofern verfügbar.

Es gibt **keine** Befehle zum Ein-/Ausschalten der Klimaanlage und **keine**
automatische Änderung von Ziel-Hz, Silent-Modus oder Climate-Solltemperatur.
Die Empfehlungssensoren sind ausdrücklich unverbindlich und schreiben nichts.

Trends werden nur aus frischen Messungen während des Heizbetriebs ermittelt.
Abtauung und zehn Minuten Erholungsphase werden ausgeschlossen. Trend wird
frühestens nach 10 Minuten und mindestens der Hälfte des eingestellten
Beobachtungsfensters ausgegeben. Nach Neustart beginnt die Sammlung von vorn.

Bei Versionswechsel auf Raumbeobachtung bleibt die Hz-Regelung AUS, auch wenn
später wieder auf `frequency` gewechselt wird. Das erneute Einschalten muss
bewusst über den bisherigen Schalter erfolgen.

Die aktuelle MQTT-Automation und Originalintegration bleiben unberührt.
Für gleichzeitigen Betrieb am selben Gerät darf es nur einen aktiven Sender
an das externe Temperatur-Topic geben.
