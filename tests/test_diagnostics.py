"""Tests for diagnostics."""
from backend.app.diagnostics import build_diagnosis


def test_diagnosis_read_only():
    d = build_diagnosis(
        summary="Possible thermal runaway",
        evidence=[{"source": "serial.log", "excerpt": "Thermal Runaway"}],
        uncertainty="Could be sensor fault; evidence only shows temperature rise.",
        next_checks=["Check heater wiring", "Run PID tuning"],
    )
    assert d.read_only is True
    assert len(d.evidence) == 1
    assert d.to_dict()["next_checks"]
