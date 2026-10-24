"""Tests for bounded slicing."""
from pathlib import Path

from backend.app.slicer import slice_model

STL = str(Path(__file__).resolve().parents[1] / "web" / "fixtures" / "bracket.stl")
PROFILE = str(Path(__file__).resolve().parents[1] / "profiles" / "ender3-proven-pla.ini")
OVERLAY = str(Path(__file__).resolve().parents[1] / "profiles" / "ender3-speed-preference.ini")


def test_slice_with_profile():
    result = slice_model(STL, PROFILE, overlay_path=OVERLAY, timeout=300)
    assert result.ok is True
    assert result.gcode_path is not None
    assert Path(result.gcode_path).stat().st_size > 0
    assert "printing_time" in result.estimates
    assert result.profile_sha256


def test_slice_with_center_transform():
    result = slice_model(STL, PROFILE, center="100,100", timeout=300)
    assert result.ok is True


def test_missing_profile_fails():
    result = slice_model(STL, "/tmp/no-such-profile.ini", timeout=60)
    assert result.ok is False
