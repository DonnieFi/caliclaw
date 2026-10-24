"""Read-only Pi event collection and simulated printer state."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

SECRET_KEYS = ("api_key", "token", "password", "secret", "api-key", "authorization", "bearer", "key")


def redact_value(key: str, value: Any) -> Any:
    if isinstance(value, str):
        if any(s in key.lower() for s in SECRET_KEYS):
            return "<redacted>"
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(key, v) for v in value]
    return value


def redact_text(text: str) -> str:
    result = text
    for key in SECRET_KEYS:
        result = re.sub(rf"(?i)({re.escape(key)}\s*[:=]\s*)\S+", r"\1<redacted>", result)
    # Bearer tokens in headers.
    result = re.sub(r"(?i)(bearer\s+)\S+", r"\1<redacted>", result)
    return result


# Backwards-compatible alias used by tests.
redact = redact_text


@dataclass
class CollectorCursor:
    source_id: str
    cursor: Optional[str] = None
    seen: set[str] = field(default_factory=set)


class EventCollector:
    def __init__(self, source_id: str, fetch: Callable[[Optional[str]], tuple[list[dict[str, Any]], Optional[str]]]):
        self.source_id = source_id
        self.fetch = fetch
        self.cursor = CollectorCursor(source_id=source_id)

    def poll(self) -> list[dict[str, Any]]:
        events, new_cursor = self.fetch(self.cursor.cursor)
        accepted = []
        for event in events:
            dedup_key = event.get("dedup_key") or event.get("id")
            if dedup_key is None:
                # Require a stable key; fall back to a hash of the serialized event.
                import json, hashlib
                dedup_key = hashlib.sha256(json.dumps(event, sort_keys=True, default=str).encode()).hexdigest()
            if dedup_key in self.cursor.seen:
                continue
            self.cursor.seen.add(str(dedup_key))
            payload = event.get("payload", {})
            if isinstance(payload, dict):
                event["payload"] = redact_value("", payload)
            accepted.append(event)
        if new_cursor is not None:
            self.cursor.cursor = new_cursor
        return accepted


@dataclass
class SimulatedPrinterState:
    state: str = "idle"
    progress: float = 0.0
    temperature: float = 25.0
    bed_temperature: float = 25.0
    observed_at: float = 0.0

    def mark_disconnected(self) -> None:
        self.state = "disconnected"

    def mark_stale(self) -> None:
        self.state = "stale"

    def start(self) -> None:
        self.state = "printing"
        self.progress = 0.0

    def advance(self, progress: float) -> None:
        if self.state == "printing":
            self.progress = min(1.0, self.progress + progress)
            if self.progress >= 1.0:
                self.state = "complete"

    def pause(self) -> None:
        if self.state == "printing":
            self.state = "paused"

    def resume(self) -> None:
        if self.state == "paused":
            self.state = "printing"

    def cancel(self) -> None:
        self.state = "idle"
        self.progress = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "progress": self.progress,
            "temperature": self.temperature,
            "bed_temperature": self.bed_temperature,
        }
