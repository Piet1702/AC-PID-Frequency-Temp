# AC PID Frequency Temp – BT-Einschalt-Hotfix (2.4.1.14 / 2.4.1.15)

## Problem

Die Fehlermeldung `Adaptive Raumregelung benötigt frische echte Raumdaten: unchanged`
trat auf, obwohl das Thermometer einen gültigen Zahlenwert hatte und der
ProtoART-MQTT-BT-Monitor regelmäßige Kontakt-Resets bestätigte. Der Schalter
(`EnabledSwitch.async_turn_on` in `switch.py`) nutzte bisher ausschließlich
den Zeitstempel `last_reported` aus Home Assistant. Ein unveränderter
Temperaturwert führt bei diesem Bluetooth-Thermometer aber nicht unbedingt zu
einer neuen HA-Zustandsmeldung.

## Änderung

Nur die Einschaltprüfung in `switch.py` ruft ab sofort
`self.controller.room_input_snapshot()` anstelle von `room_sensor_snapshot()`
auf. **Dieselbe Prüfung arbeitet bereits im laufenden Raumregler.**

* Numerischer HA-Sensorwert und bestätigter BT-Kontakt (`confirmed`): Start möglich.
* Numerischer, kürzlich neu gemeldeter Wert: Start möglich, soweit der Controller ihn als `ok` bewertet.
* `unchanged` ohne bestätigten Kontakt: Start bleibt gesperrt.
* `stale`, `invalid`, `missing`: Start bleibt gesperrt.
* Beobachtungsmodus: Start bleibt weiterhin gesperrt.
* Kein Eingriff in `regelung.py`, MQTT-Automation, Klima-On/Off, Trend, Hz-Lernwerte oder Dashboard.

**Sicherheitsgrenze:** Der Kontaktstatus basiert auf dem beobachteten Reset
von `thermometer/last`, dessen ProtoART-Bedeutung nicht offiziell
bestätigt ist. Der Patch umgeht keine ungültigen oder fehlenden HA-Zahlenwerte.
Nach einem vollständigen HA-Neustart kann der BT-Monitor zunächst `waiting`
melden, bis er einen frischen Kontakt-Reset erkannt hat.

## Installation

Das ZIP komplett ins Git-Repository `C:\GitHub\AC-PID-Frequency-Temp`
entpacken. In Git Bash:

```bash
cd /c/GitHub/AC-PID-Frequency-Temp
py -3 fix_ac_pid_bt_startup.py --dry-run
py -3 fix_ac_pid_bt_startup.py
py -3 tests/test_bt_startup_hotfix.py
py -3 -m compileall -q custom_components/ac_pid_frequency_temp
```

Anschließend mit Git committen und pushen, Home Assistant die aktualisierte
Integration installieren lassen und Home Assistant neu starten.

Das Skript erstellt bei echten Änderungen ein Backup unter
`.git/ac_pid_backup_bt_startup` und ist bei wiederholter Ausführung idempotent.
Ein Fehlschlag im Dry-Run verändert keine Dateien.

**Kein Versionssprung:** Der Hotfix wurde absichtlich nicht als
vollständige Version 2.4.1.16 ausgegeben, da er mit **2.4.1.14 oder 2.4.1.15**
kombiniert werden kann. Wenn 2.4.1.15 noch nicht installiert ist, wird
dadurch nicht fälschlich dessen Mindest-Hz-Lernkorrektur als installiert
angezeigt. Bei einer späteren vollständigen Version kann der Fix mit
entsprechender Versionsnummer übernommen werden.
