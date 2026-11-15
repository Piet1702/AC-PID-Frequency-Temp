"""MQTT-Takt ohne Abhängigkeit von der Frequenzregelung oder HA-Reloads."""
from __future__ import annotations
from datetime import datetime, timedelta

class MqttCadence:
    def __init__(self) -> None:
        self.next_due: datetime | None = None
    def reset(self) -> None:
        self.next_due = None
    def should_send(self, now: datetime, *, enabled: bool, interval: float) -> bool:
        if not enabled:
            self.next_due = None
            return False
        interval = max(5.0, min(60.0, float(interval)))
        if self.next_due is None or now >= self.next_due:
            # No backlog or burst of publishes after a delayed HA event loop.
            self.next_due = now + timedelta(seconds=interval)
            return True
        return False
