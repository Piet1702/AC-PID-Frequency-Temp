# AC PID Frequency Temp 2.4.1.3 – Native MQTT-Bedienung

Diese Version ergänzt native Home-Assistant-Entitäten an derselben Geräte-Instanz.

- `switch` MQTT-Temperaturversand (Standard AUS)
- `text` MQTT-Topic (zuerst konfigurieren)
- `number` MQTT-Sendeintervall (5–60 s, Standard 5)
- `number` MQTT QoS (0–2, Standard 0)
- `switch` MQTT Retain (Standard AUS; bei Temperaturwerten nicht empfohlen)

Die vier Diagnosesensoren aus 2.4.1.2 bleiben erhalten.

**Wichtig:** Änderungen an den nativen Einstellungen werden über die Home-Assistant-
Konfigurationsoptionen gespeichert und lösen durch den bestehenden Options-Listener
standardmäßig ein kurzes Neuladen der Integration aus. Dadurch übernimmt auch der
MQTT-Timer die neue Frequenz. Der aktuelle Hz-Lernzustand wird vom bestehenden
Controller beim Shutdown gespeichert. Keine neue Regelungslogik in dieser Version.

Vor Aktivierung die bestehende MQTT-Automation abschalten. MQTT-Broker und Topic
müssen korrekt eingerichtet sein. Solange die neue adaptive Regelung nicht fertig
ist, diese neue MQTT-Ausgabe bitte ausgeschaltet lassen.

Die Schalter/Number/Text-Entitäten befinden sich unter Einstellungen → Geräte &
Dienste → AC PID Frequency Temp → Gerät. Erweiterte Diagnosewerte können ggf.
in einer eigenen Kategorie zusammengefasst werden.
