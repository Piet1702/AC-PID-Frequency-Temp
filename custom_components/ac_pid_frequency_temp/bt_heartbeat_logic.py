"""Pure protocol inference for ProtoART `sensor/thermometer/last`.

Observed sequence: 0,-2,-7,...,-27,0. A jump toward zero is treated as
probable new BT contact, NOT merely as a new MQTT packet. Protocol semantics
are inferred from field observations, not guaranteed by ProtoART docs.
"""
from __future__ import annotations
from datetime import datetime
import math


class BtLastTracker:
    def __init__(self) -> None:
        self.raw: float | None = None
        self.contact_at: datetime | None = None
        self.last_packet_at: datetime | None = None
        self.packet_count = 0
        self.reset_count = 0
        self.invalid_count = 0

    def ingest(self, raw: object, now: datetime, *, retained: bool = False) -> bool:
        """Return True ONLY on a probable contact/reset, never on countdown ticks."""
        if retained:
            return False
        try:
            value = float(raw)
        except (ValueError, TypeError, OverflowError):
            self.invalid_count += 1
            return False
        if not math.isfinite(value) or not -86400 <= value <= 0:
            self.invalid_count += 1
            return False
        previous = self.raw
        if previous is not None and now < (self.last_packet_at or now):
            self.raw = None
            previous = None
        reset = (
            (-3 <= value <= 0 and previous is None)
            or (previous is not None and previous <= -6
                and -5 <= value <= 0 and value - previous >= 6)
        )
        self.raw = value
        self.last_packet_at = now
        self.packet_count += 1
        if reset:
            self.contact_at = now
            self.reset_count += 1
        return reset

    def contact_age(self, now: datetime) -> float | None:
        if self.contact_at is None:
            return None
        return max(0.0, (now - self.contact_at).total_seconds())

    def status(self, now: datetime, *, started_at: datetime,
               timeout_seconds: float) -> str:
        """waiting -> confirmed -> timeout. No MQTT packets != BT contact."""
        last = self.contact_at or started_at
        if (now - last).total_seconds() > timeout_seconds:
            return "timeout"
        return "confirmed" if self.contact_at is not None else "waiting"
