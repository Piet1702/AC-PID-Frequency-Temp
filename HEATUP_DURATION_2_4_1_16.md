# AC PID Frequency Temp – Version 2.4.1.16: gewünschte Aufheizdauer

## Neues Einstellfeld

**Gewünschte Aufheizdauer** (`number.<instanz>_gewuenschte_aufheizdauer`)
- Standard: **150 Minuten**, einstellbar **60–360 Minuten** in 15-Minuten-Schritten.
- Die Zeit läuft ab dem Beginn eines Heizdurchgangs, während die adaptive
  Hz-Regelung aktiv ist und eine gültige Raumtemperatur vorliegt.
- Bei Erreichen der Raumzieltemperatur oder Ausschalten der Regelung wird der
  laufende Zeitplan zurückgesetzt. Nach Home-Assistant-Neustart beginnt die
  Zeitplanung ebenfalls neu.
- Die verbleibende Zeit ist eine **weiche Vorgabe**. Ab 45 Minuten Rest wird
  sie auf 45 Minuten begrenzt, damit der Regler nicht kurz vor Ablauf des
  Zeitbudgets aggressiv hochregelt.
- Solltrend = verbleibendes Temperaturdefizit ÷ verbleibende Stunden.
- Der berechnete Solltrend ist auf maximal 1,5 °C/h begrenzt.
- Bei ausreichend schnellem Aufheizen prüft die Raumautomatik vorsichtig eine
  niedrigere Ziel-Hz, anstatt weiter Leistung anzufordern.
- Bei zu langsamem Aufheizen erfolgt höchstens eine begrenzte Anpassung und
  die vorhandene Anti-Windup-/5-Minuten-Sperre bleibt erhalten.
- **Die 45-Minuten-Prognose bleibt nur zur frühzeitigen Reduzierung nahe dem
  Ziel aktiv**, nicht länger als alleinige Grundlage für maximale Heizleistung.

## Sicherheits- und Regelungsgrenzen

Die ursprüngliche Frequenzregelung, die Kompressorreaktion über den simulierten
Temperatursensor, der BT-Kontakt-Timeout, die Überhitzungssicherung, die
Abtaupause, die bevorzugten Dauerbetriebs-Hz und die maximale automatische
Ziel-Hz bleiben erhalten. Die angeforderte Ziel-Hz ist keine garantierte
physikalische Begrenzung der realen Kompressorfrequenz. Eine Watt-Begrenzung
wird mit diesem Update **nicht** implementiert.

Die bisherige permanente Start-Hz-Untergrenze während des gesamten Aufheizens
wird entfernt: Start-Hz gelten jetzt nur beim *Beginn* des Heizdurchgangs.
Andernfalls könnte die Anlage trotz ausreichendem Temperaturtrend nicht
vorsichtig unter die Startfrequenz herunterregeln.

## Updatepfade

- Von **2.4.1.15**: neue Aufheizregelung und Diagnosefelder.
- Von **2.4.1.14**: zusätzlich bisheriger **2.4.1.15 Mindest-Hz-Hotfix**;
  falsche Mindest-Hz dürfen nicht erneut nach oben gelernt werden.
- Der separate BT-Einschalt-Hotfix wird **nicht** überschrieben. Sollte er
  noch fehlen, ist er separat zu installieren.
- `--dry-run` validiert sämtliche erforderlichen Patches vor dem Schreiben.
- Backups unter `.git/ac_pid_backup_2_4_1_16/`.

## Praxisempfehlung

150 min Aufheizdauer, 30 min Trend-Auswertefenster, 5 min Prüfintervall,
45 Hz Start, 22 Hz bevorzugter Dauerbetrieb, vorläufig 50 Hz maximale
*virtuelle* Ziel-Hz. Auf echten Kompressor, Watt-Verbrauch, Temperaturtrend
und Heizverhalten achten; die Klimaanlage kann intern selbständig über das
virtuelle Ziel hinaus modulieren.

## Einschränkung der Tests

Das reine Rechenmodell wird ohne HA in Tests geprüft. Der Installationspatch
wird in einer nachgebildeten Projektstruktur geprüft; erst der Nutzerlauf
auf dem echten Fork und ein kontrollierter Home-Assistant-Test bestätigen
Kompatibilität und Geräteverhalten.
