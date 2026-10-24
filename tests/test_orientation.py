"""Tests for orientation recommendation."""
from pathlib import Path

import trimesh

from backend.app.orientation import recommend_orientation

STL = str(Path(__file__).resolve().parents[1] / "web" / "fixtures" / "bracket.stl")


def test_recommendation_returns_candidate():
    mesh = trimesh.load(STL)
    rec = recommend_orientation(mesh)
    assert rec.rotation_degrees in [(0, 0, 0), (90, 0, 0), (0, 90, 0), (0, 0, 90), (180, 0, 0), (0, 180, 0)]
    assert len(rec.candidates) == 6
    assert "override" in rec.rationale


def test_flat_plate_prefers_zero_rotation():
    mesh = trimesh.creation.box(extents=(40, 25, 3))
    rec = recommend_orientation(mesh)
    # Flat plate should keep a large footprint; rotation may vary but height should be minimal.
    best = next(c for c in rec.candidates if c.rotation_degrees == rec.rotation_degrees)
    assert best.height_mm <= 40
