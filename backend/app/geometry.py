"""Independent geometry validation for exported meshes."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

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

import trimesh


@dataclass
class GeometryReport:
    ok: bool
    path: str
    watertight: bool
    components: int
    vertices: int
    faces: int
    volume_mm3: float
    bounds_mm: list
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def validate_stl(
    path: str | Path,
    *,
    expected_bounds: Optional[tuple[float, float, float]] = None,
    bounds_tolerance: float = 0.5,
    min_volume: float = 1.0,
    max_components: int = 1,
    require_watertight: bool = True,
) -> GeometryReport:
    path = _confine_path(path, "stl_path")
    errors: list[str] = []
    loaded = trimesh.load(path)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError("Loaded geometry is not a single mesh")
    mesh = loaded
    watertight = bool(mesh.is_watertight)
    components = len(mesh.split())
    bounds = [float(v) for v in (mesh.bounds[1] - mesh.bounds[0])]
    volume = float(mesh.volume)

    if require_watertight and not watertight:
        errors.append("mesh is not watertight")
    if components > max_components:
        errors.append(f"mesh has {components} components, max {max_components}")
    if volume < min_volume:
        errors.append(f"volume {volume:.3f} mm3 is below minimum {min_volume}")
    if expected_bounds is not None:
        for i, (actual, expected) in enumerate(zip(bounds, expected_bounds)):
            if abs(actual - expected) > bounds_tolerance:
                errors.append(
                    f"dimension {i} {actual:.3f} mm differs from expected {expected:.3f} mm "
                    f"by more than {bounds_tolerance} mm"
                )

    return GeometryReport(
        ok=not errors,
        path=str(path),
        watertight=watertight,
        components=components,
        vertices=len(mesh.vertices),
        faces=len(mesh.faces),
        volume_mm3=volume,
        bounds_mm=[[float(v) for v in row] for row in mesh.bounds],
        errors=errors,
    )
