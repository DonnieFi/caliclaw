"""Bounded operations for imported STL meshes."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

ALLOWED_ROOTS = [
    Path("/tmp").resolve(),
    Path("/var/tmp").resolve(),
    Path.cwd().resolve(),
    Path(__file__).resolve().parents[2],
]


def _confine_path(path, label):
    resolved = Path(path).resolve()
    if not any(resolved == root or root in resolved.parents for root in ALLOWED_ROOTS):
        raise ValueError(f"{label} is outside the allowed workspace roots")
    return resolved

import numpy as np
import trimesh


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    path = _confine_path(path, "input_path")
    mesh = trimesh.load(path)
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("Input is not a single mesh")
    return mesh


def scale(mesh: trimesh.Trimesh, factor: float | Tuple[float, float, float]) -> trimesh.Trimesh:
    if isinstance(factor, (int, float)):
        matrix = np.eye(4)
        matrix[:3, :3] *= float(factor)
    else:
        matrix = np.eye(4)
        for i, f in enumerate(factor):
            matrix[i, i] = float(f)
    mesh.apply_transform(matrix)
    return mesh


def rotate(mesh: trimesh.Trimesh, degrees: float, axis: Tuple[float, float, float] = (0, 0, 1)) -> trimesh.Trimesh:
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(degrees), axis))
    return mesh


def cut_box(mesh: trimesh.Trimesh, size: Tuple[float, float, float], center: Tuple[float, float, float] = (0, 0, 0)) -> trimesh.Trimesh:
    box = trimesh.creation.box(extents=size)
    box.apply_translation(center)
    result = mesh.difference(box)
    if result is None or result.is_empty:
        raise ValueError("Boolean difference produced empty mesh")
    return result


def drill_hole(mesh: trimesh.Trimesh, diameter: float, axis: str = "z", center: Tuple[float, float, float] = (0, 0, 0), depth: Optional[float] = None) -> trimesh.Trimesh:
    if axis not in ("x", "y", "z"):
        raise ValueError("axis must be x, y, or z")
    if depth is None:
        if axis == "x":
            depth = (mesh.bounds[1][0] - mesh.bounds[0][0]) + 2.0
        elif axis == "y":
            depth = (mesh.bounds[1][1] - mesh.bounds[0][1]) + 2.0
        else:
            depth = (mesh.bounds[1][2] - mesh.bounds[0][2]) + 2.0
    cylinder = trimesh.creation.cylinder(radius=diameter / 2.0, height=depth, sections=32)
    if axis == "x":
        cylinder.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))
    elif axis == "y":
        cylinder.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    cylinder.apply_translation(center)
    result = mesh.difference(cylinder)
    if result is None or result.is_empty:
        raise ValueError("Drill produced empty mesh")
    return result


def export_mesh(mesh: trimesh.Trimesh, path: str | Path) -> Path:
    path = _confine_path(path, "output_path")
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)
    return path
