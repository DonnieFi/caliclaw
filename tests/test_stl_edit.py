"""Tests for bounded STL edits."""
from pathlib import Path

import trimesh

from backend.app.stl_edit import cut_box, drill_hole, export_mesh, load_mesh, rotate, scale

STL = str(Path(__file__).resolve().parents[1] / "web" / "fixtures" / "bracket.stl")


def test_scale_and_rotate_preserve_watertight():
    mesh = load_mesh(STL)
    scale(mesh, 2.0)
    rotate(mesh, 90)
    assert mesh.is_watertight
    assert mesh.bounds[1][0] - mesh.bounds[0][0] > 39


def test_drill_hole_reduces_volume():
    mesh = load_mesh(STL)
    original_volume = mesh.volume
    drilled = drill_hole(mesh, diameter=5, axis="z", center=(20, 12.5, 15))
    assert drilled.volume < original_volume
    assert drilled.is_watertight


def test_cut_box():
    mesh = load_mesh(STL)
    original_volume = mesh.volume
    cut = cut_box(mesh, size=(10, 10, 10), center=(5, 5, 5))
    assert cut.volume < original_volume


def test_export_roundtrip(tmp_path):
    mesh = load_mesh(STL)
    out = tmp_path / "edited.stl"
    export_mesh(mesh, out)
    reloaded = trimesh.load(out)
    assert reloaded.is_watertight
