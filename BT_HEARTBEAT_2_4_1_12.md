# AC PID Frequency Temp 2.4.1.12 – ProtoART BT heartbeat

**Input:** `climacontrol/HVAC_9C2FDC/sensor/thermometer/last` (+ `.../tact`).

`last` is observed to count 0,-2,-7,...,-27,0. A jump toward 0 is **interpreted** as a BT contact, not officially documented. Every MQTT packet is NOT counted as a BT measurement.

Default failure timeout: **10 minutes**, configurable via the new Number entity `bt_contact_timeout` (2-120 min). After no inferred reset within this interval, adaptive regulation stops and the simulated sensor becomes unavailable; ProtoART can fall back to its own sensor. At start, outer regulation holds until first confirmed reset. If the known MQTT topic cannot be used, the previous change-only behavior remains in place.

The Home Assistant room-temperature sensor remains the primary reading; `tact` is passively observed for diagnostics. Inferred contact timestamps allow unchanged temperature reports to form time-separated trend samples. Minimum trend horizon 10 min, separate from one-minute control checks.

No HVAC power/mode/setpoint commands; no changes to Home Assistant automations; no additional MQTT publisher. The selected `automation.send_simulated_temp_new_pid_control` remains unchanged. If `last` behaves differently than the observed reset pattern, turn off room auto until validated.
