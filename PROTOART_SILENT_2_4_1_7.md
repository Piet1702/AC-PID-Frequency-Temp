# AC PID Frequency Temp 2.4.1.7 – ProtoART Silent-MQTT

Die Silent-Steuerung ist standardmaessig **deaktiviert**, auch nach dem Update.
Sie ist unabhaengig von der Temperatur-MQTT-Ausgabe; diese bleibt unveraendert.

## Erste Inbetriebnahme

1. `text.*_silent_topic`: Nur ein passendes Topic der Form
   `climacontrol/HVAC_9C2FDC/heatpump/silent_mode/set` verwenden.
   In der ProtoART-Dokumentation ist dieser Befehl nur bei bestimmten MHI-Modulen verfuegbar.
2. `select.*_silent_policy` explizit auf `always_silent`, `auto` oder `normal` stellen.
   `disabled` sendet keine Befehle und veraendert keine vorhandenen Einstellungen am Geraet.
3. Keine Silent-Befehle bei ausgeschalteter HA-Hz-Regelung, Nicht-Heizen,
   Abtauung, Nachlauf oder fehlenden/veralteten Raumdaten.
4. `number.*_silent_boost_minutes` (5-120 min) einstellen, dann
   `button.*_silent_boost_start` oder `button.*_silent_boost_cancel` verwenden.
   Boost ist nur in `always_silent` und `auto` moeglich.

## Automatik

Normalzustand = Silent aktiv. Ein 30-minuetiger automatischer Boost ist nur
bei Raumtemperatur >=1 K unter Ziel, langsamer Erwaermung (Trend <=0.03 K/h),
beobachtetem Fenster >= der Haelfte des Sollfensters und erhoehter Ziel-Hz
(mindestens bevorzugte Hz +4) moeglich. Danach 60 min Boost-Sperre.

## Sicherheit & Diagnose

MQTT-Kommandos gehen ausschliesslich an `/heatpump/silent_mode/set`
mit `on` oder `off`, QoS 0, retain=False. Keine HVAC-Ein/Aus- oder Solltemp.-Befehle.
Statusabo `/heatpump/silent_mode` zeigt vorhandene Rueckmeldungen; ohne
Bestaetigung wird ein Befehl max. 3-mal im Abstand von >=120 Sekunden gesendet.
Nach max. 3 Versuchen wird `unconfirmed` diagnostiziert.
Boost-Zustand wird bei Neustart nicht wiederhergestellt.

WICHTIG: Keine Garantie fuer reale Leistungsbegrenzung. Erst manuell verifizieren,
dass das konkrete ProtoART-Modul das Silent-Topic unterstuetzt.
