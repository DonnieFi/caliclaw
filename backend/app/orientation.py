"""Orientation recommendation for 3D printing (minimum support heuristic)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List, Tuple

import numpy as np
import trimesh


@dataclass
class OrientationCandidate:
    rotation_degrees: Tuple[int, int, int]
    footprint_area_mm2: float
    height_mm: float
    support_area_mm2: float
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OrientationRecommendation:
    rotation_degrees: Tuple[int, int, int]
    candidates: List[OrientationCandidate]
    rationale: str

    def to_dict(self) -> dict:
        return asdict(self)


_ROTATIONS = [
    (0, 0, 0),
    (90, 0, 0),
    (0, 90, 0),
    (0, 0, 90),
    (180, 0, 0),
    (0, 180, 0),
]


def _support_area(mesh: trimesh.Trimesh) -> float:
    # Area of downward-facing triangles (normals below 45 degrees).
    normals = mesh.face_normals
    areas = mesh.area_faces
    downward = normals[:, 2] < -0.7071
    return float(areas[downward].sum())


def _footprint_and_height(mesh: trimesh.Trimesh) -> Tuple[float, float, float]:
    pts = mesh.vertices.copy()
    min_x, min_y = pts[:, 0].min(), pts[:, 1].min()
    max_x, max_y = pts[:, 0].max(), pts[:, 1].max()
    footprint = float((max_x - min_x) * (max_y - min_y))
    height = float(pts[:, 2].max() - pts[:, 2].min())
    return footprint, height, _support_area(mesh)


def recommend_orientation(mesh: trimesh.Trimesh) -> OrientationRecommendation:
    candidates = []
    for rot in _ROTATIONS:
        m = mesh.copy()
        m.apply_transform(trimesh.transformations.euler_matrix(
            np.deg2rad(rot[0]), np.deg2rad(rot[1]), np.deg2rad(rot[2])
        ))
        # place on bed: min z = 0
        m.apply_translation((0, 0, -m.bounds[0][2]))
        footprint, height, support = _footprint_and_height(m)
        # Prefer larger footprint (stable base), lower height, and less support area.
        score = footprint - 0.5 * height - 2.0 * support
        candidates.append(OrientationCandidate(rot, footprint, height, support, score))

    best = max(candidates, key=lambda c: c.score)
    rationale = (
        f"Selected rotation {best.rotation_degrees} with footprint {best.footprint_area_mm2:.1f} mm2 "
        f"and height {best.height_mm:.1f} mm; largest stable base among tested candidates. "
        "User override is allowed before slicing."
    )
    return OrientationRecommendation(best.rotation_degrees, candidates, rationale)
