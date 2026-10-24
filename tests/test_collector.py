"""Tests for read-only event collection and simulated printer."""
from backend.app.collector import EventCollector, SimulatedPrinterState, redact


def test_dedup_and_cursor():
    events = [
        {"id": "e1", "payload": {"msg": "hello"}, "dedup_key": "k1"},
        {"id": "e2", "payload": {"msg": "world"}, "dedup_key": "k2"},
    ]
    calls = {"n": 0}

    def fetch(cursor):
        calls["n"] += 1
        if calls["n"] == 1:
            return events, "c1"
        return [{"id": "e1", "payload": {"msg": "dup"}, "dedup_key": "k1"}], "c2"

    collector = EventCollector("pi", fetch)
    first = collector.poll()
    assert len(first) == 2
    assert collector.cursor.cursor == "c1"
    second = collector.poll()
    assert len(second) == 0
    assert collector.cursor.cursor == "c2"


def test_redaction():
    assert "<redacted>" in redact("api_key=secret123")
    assert "secret123" not in redact("api_key=secret123")


def test_simulated_printer_lifecycle():
    p = SimulatedPrinterState()
    assert p.state == "idle"
    p.start()
    assert p.state == "printing"
    p.advance(1.0)
    assert p.state == "complete"
    p2 = SimulatedPrinterState()
    p2.start()
    p2.pause()
    assert p2.state == "paused"
    p2.resume()
    assert p2.state == "printing"
    p2.cancel()
    assert p2.state == "idle"
