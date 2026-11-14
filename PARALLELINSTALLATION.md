# AC PID Frequency Temp – erste Version

Dieser Fork ist als eigenständige Home-Assistant-Integration eingerichtet.

- Integrations-Domain: `ac_pid_frequency_temp`
- Integrationsordner: `custom_components/ac_pid_frequency_temp`
- Lovelace-Karte: `custom:ac-pid-frequency-temp-card`
- Regelungsalgorithmus: gegenüber Upstream unverändert
- Keine MQTT-Steuerung, keine automatische Temperaturregelung (noch nicht implementiert)

## Wichtige Sicherheitsregel

Niemals beide Hz-Regler gleichzeitig dieselbe Klimaanlage steuern lassen. Für den ersten Test nur die Integration laden und die neue Regelung ausgeschaltet lassen. Keines der beiden erzeugten Sensor-Signale aktiv an die Klimaanlage koppeln, solange die Umschaltung nicht bewusst eingerichtet ist.

## Installation

Zunächst HACS-Repository installieren, danach Home Assistant neu starten und unter Einstellungen > Geräte & Dienste die Integration `AC PID Frequency Temp` hinzufügen. Karte: `type: custom:ac-pid-frequency-temp-card`.

## Weiterentwicklung

Der Originalcode bleibt über Git-Remote `upstream` verfügbar. Beim späteren Übernehmen von Upstream-Änderungen müssen Pfad- und Namensänderungen erneut berücksichtigt werden.
