"""Bounds and simulated refusal for nozzle, bed, speed, and flow."""
import os
import tempfile
from pathlib import Path

_previous_db = os.environ.get("CALICLAW_DB")
os.environ["CALICLAW_DB"] = str(Path(tempfile.mkdtemp(prefix="caliclaw-printer-")) / "printer.db")

import pytest
from fastapi import HTTPException

from backend.app import poc_api
from backend.app.octoprint import set_printhead_factor

if _previous_db is None:
    os.environ.pop("CALICLAW_DB", None)
else:
    os.environ["CALICLAW_DB"] = _previous_db


def _live(monkeypatch):
    monkeypatch.setattr(poc_api, "_real_printer_status", lambda: {"simulated": False})


def _sim(monkeypatch):
    monkeypatch.setattr(poc_api, "_real_printer_status", lambda: {"simulated": True})


def test_nozzle_above_280_is_rejected(monkeypatch):
    def touched():
        raise AssertionError("printer status should not be read for a bad target")

    monkeypatch.setattr(poc_api, "_real_printer_status", touched)
    with pytest.raises(HTTPException) as exc:
        poc_api.printer_targets(poc_api.TargetsRequest(tool=281))
    assert exc.value.status_code == 400
    assert "0" in exc.value.detail and "280" in exc.value.detail


def test_bed_above_120_is_rejected():
    with pytest.raises(HTTPException) as exc:
        poc_api.printer_targets(poc_api.TargetsRequest(bed=121))
    assert exc.value.status_code == 400


def test_empty_targets_rejected():
    with pytest.raises(HTTPException) as exc:
        poc_api.printer_targets(poc_api.TargetsRequest())
    assert exc.value.status_code == 400


def test_simulated_targets_do_not_call_the_printer(monkeypatch):
    calls = []
    _sim(monkeypatch)
    monkeypatch.setattr(poc_api, "set_tool_target", lambda celsius: calls.append(celsius))
    with pytest.raises(HTTPException) as exc:
        poc_api.printer_targets(poc_api.TargetsRequest(tool=0))
    assert exc.value.status_code == 400
    assert "simulated" in exc.value.detail
    assert calls == []


def test_live_targets_call_both_setters(monkeypatch):
    calls = []
    _live(monkeypatch)
    monkeypatch.setattr(poc_api, "set_tool_target", lambda celsius: calls.append(("tool", celsius)) or {})
    monkeypatch.setattr(poc_api, "set_bed_target", lambda celsius: calls.append(("bed", celsius)) or {})
    assert poc_api.printer_targets(poc_api.TargetsRequest(tool=210, bed=60)) == {"ok": True}
    assert calls == [("tool", 210), ("bed", 60)]


def test_target_error_hides_the_upstream_message(monkeypatch):
    _live(monkeypatch)

    def boom(_celsius):
        raise RuntimeError("http://10.0.0.5 key=secret")

    monkeypatch.setattr(poc_api, "set_tool_target", boom)
    with pytest.raises(HTTPException) as exc:
        poc_api.printer_targets(poc_api.TargetsRequest(tool=200))
    assert exc.value.status_code == 502
    assert exc.value.detail == "printer settings were not accepted"


def test_later_target_failure_leaves_the_first_call(monkeypatch):
    calls = []
    _live(monkeypatch)
    monkeypatch.setattr(poc_api, "set_tool_target", lambda celsius: calls.append(celsius) or {})

    def boom(_celsius):
        raise RuntimeError("bed refused")

    monkeypatch.setattr(poc_api, "set_bed_target", boom)
    with pytest.raises(HTTPException) as exc:
        poc_api.printer_targets(poc_api.TargetsRequest(tool=200, bed=60))
    assert exc.value.status_code == 502
    assert calls == [200]


def test_flow_below_10_is_rejected(monkeypatch):
    calls = []
    monkeypatch.setattr(poc_api, "set_printhead_factor", lambda command, factor: calls.append((command, factor)))
    with pytest.raises(HTTPException) as exc:
        poc_api.printer_factors(poc_api.FactorsRequest(flowrate=5))
    assert exc.value.status_code == 400
    assert calls == []


def test_speed_above_200_is_rejected():
    with pytest.raises(HTTPException) as exc:
        poc_api.printer_factors(poc_api.FactorsRequest(feedrate=201))
    assert exc.value.status_code == 400


def test_empty_factors_rejected():
    with pytest.raises(HTTPException) as exc:
        poc_api.printer_factors(poc_api.FactorsRequest())
    assert exc.value.status_code == 400


def test_simulated_factors_do_not_call_the_printer(monkeypatch):
    calls = []
    _sim(monkeypatch)
    monkeypatch.setattr(poc_api, "set_printhead_factor", lambda command, factor: calls.append((command, factor)))
    with pytest.raises(HTTPException) as exc:
        poc_api.printer_factors(poc_api.FactorsRequest(feedrate=100))
    assert exc.value.status_code == 400
    assert calls == []


def test_live_factors_at_the_bounds(monkeypatch):
    calls = []
    _live(monkeypatch)
    monkeypatch.setattr(
        poc_api, "set_printhead_factor", lambda command, factor: calls.append((command, factor)) or {}
    )
    assert poc_api.printer_factors(poc_api.FactorsRequest(feedrate=10, flowrate=200)) == {"ok": True}
    assert calls == [("feedrate", 10), ("flowrate", 200)]


def test_unknown_printhead_command_is_rejected():
    with pytest.raises(ValueError):
        set_printhead_factor("jog", 100)


def test_camera_failure_hides_connection_details(monkeypatch):
    def fail():
        raise RuntimeError("http://private-host/?apikey=secret")

    monkeypatch.setattr(poc_api, "camera_snapshot", fail)
    with pytest.raises(HTTPException) as exc:
        poc_api.camera()
    assert exc.value.status_code == 503
    assert exc.value.detail == "Snapshot unavailable."


def test_camera_is_independent_of_printer_status(monkeypatch):
    def status():
        raise AssertionError("camera must not request printer status")

    monkeypatch.setattr(poc_api, "_real_printer_status", status)
    monkeypatch.setattr(poc_api, "camera_snapshot", lambda: b"jpeg fixture")
    response = poc_api.camera()
    assert response.media_type == "image/jpeg"
    assert response.body == b"jpeg fixture"
