"""Tests for bounded OpenSCAD execution."""
from __future__ import annotations

import time
from pathlib import Path

from backend.app.worker import build_model, cleanup_workspace

FIXTURE = (Path(__file__).resolve().parents[1] / "fixtures" / "bracket.scad").read_text()


def test_build_valid_bracket():
    result = build_model(FIXTURE, timeout=60)
    assert result.ok is True
    assert result.mesh["watertight"] is True
    assert result.mesh["components"] == 1
    assert result.mesh["volume_mm3"] > 0
    assert result.sha256 is not None
    cleanup_workspace(result.workspace)


def test_invalid_syntax_fails():
    result = build_model("this is not scad\n", timeout=30)
    assert result.ok is False
    assert result.stl_path is None or not Path(result.stl_path).exists() or result.error
    cleanup_workspace(result.workspace)


def test_timeout_fails():
    result = build_model("sphere(r=50, $fn=100000);\n", timeout=2)
    assert result.ok is False
    assert "timed out" in (result.error or "")
    cleanup_workspace(result.workspace)


def test_negative_volume_fails():
    # A zero-thickness slab should not produce positive volume.
    result = build_model("cube([10,10,0]);\n", timeout=30)
    # OpenSCAD may drop degenerate geometry; either fail or non-positive volume.
    assert result.ok is False or (result.mesh and result.mesh["volume_mm3"] <= 0)
    cleanup_workspace(result.workspace)
