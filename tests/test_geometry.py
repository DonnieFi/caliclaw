"""Tests for independent geometry validation."""
from pathlib import Path

from backend.app.geometry import validate_stl

STL = str(Path(__file__).resolve().parents[1] / "web" / "fixtures" / "bracket.stl")


def test_valid_bracket_geometry():
    report = validate_stl(STL, expected_bounds=(40, 25, 30), min_volume=1000)
    assert report.ok is True
    assert report.watertight is True
    assert report.components == 1


def test_wrong_bounds_fail():
    report = validate_stl(STL, expected_bounds=(100, 25, 30), bounds_tolerance=0.5)
    assert report.ok is False
    assert any("dimension 0" in e for e in report.errors)


def test_min_volume_fail():
    report = validate_stl(STL, min_volume=1_000_000)
    assert report.ok is False
    assert any("volume" in e for e in report.errors)
