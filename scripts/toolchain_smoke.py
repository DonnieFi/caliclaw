#!/usr/bin/env python3
"""Reproduce the CaliClaw OpenSCAD + PrusaSlicer toolchain spike."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "bracket.scad"
PROFILE = ROOT / "profiles" / "ender3-proven-pla.ini"
OVERLAY = ROOT / "profiles" / "ender3-speed-preference.ini"
OUT_DIR = Path("/tmp/caliclaw-toolchain")
STL = OUT_DIR / "bracket.stl"
GCODE = OUT_DIR / "bracket.gcode"

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for tool in ("openscad", "prusa-slicer"):
        if shutil.which(tool) is None:
            print(f"MISSING TOOL: {tool}", file=sys.stderr)
            return 2

    # 1. Compile SCAD -> STL.
    result = run(["openscad", "-o", str(STL), str(FIXTURE)], timeout=60)
    if result.returncode != 0 or not STL.exists():
        print("OpenSCAD failed:", result.stderr, file=sys.stderr)
        return 1

    # 2. Slice STL -> G-code.
    result = run(
        [
            "prusa-slicer",
            "--load", str(PROFILE),
            "--load", str(OVERLAY),
            "--export-gcode",
            "--output", str(GCODE),
            str(STL),
        ],
        timeout=180,
    )
    if result.returncode != 0 or not GCODE.exists() or GCODE.stat().st_size == 0:
        print("PrusaSlicer failed:", result.stderr, file=sys.stderr)
        return 1

    # 3. Validate STL with trimesh.
    try:
        import trimesh
    except ImportError as exc:
        print("trimesh unavailable:", exc, file=sys.stderr)
        return 1
    mesh = trimesh.load(STL)
    if not mesh.is_watertight or len(mesh.split()) != 1:
        print("STL validation failed: not a single watertight component", file=sys.stderr)
        return 1

    gcode_text = GCODE.read_text(errors="replace")
    summary = {
        "openscad_version": (lambda r: (r.stdout or r.stderr).strip())(run(["openscad", "--version"])),
        "stl": {"path": str(STL), "sha256": sha256_file(STL), "bytes": STL.stat().st_size},
        "gcode": {"path": str(GCODE), "sha256": sha256_file(GCODE), "bytes": GCODE.stat().st_size},
        "mesh": {
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
            "volume_mm3": float(mesh.volume),
            "bounds_mm": [[float(v) for v in row] for row in mesh.bounds],
            "watertight": bool(mesh.is_watertight),
            "components": len(mesh.split()),
        },
        "gcode_estimates": {
            "filament_mm": next((l for l in gcode_text.splitlines() if "filament used [mm]" in l), None),
            "time": next((l for l in gcode_text.splitlines() if "estimated printing time" in l), None),
        },
        "profile_sha256": sha256_file(PROFILE),
    }
    print(json.dumps(summary, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
