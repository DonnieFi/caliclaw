"""Bounded PrusaSlicer execution and estimate parsing."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

DEFAULT_TIMEOUT = 300

ALLOWED_ROOTS = [
    Path("/tmp").resolve(),
    Path("/var/tmp").resolve(),
    Path.cwd().resolve(),
    Path(__file__).resolve().parents[2],
]


def _confine_path(path: str | Path, label: str) -> Path:
    resolved = Path(path).resolve()
    if not any(resolved == root or root in resolved.parents for root in ALLOWED_ROOTS):
        raise ValueError(f"{label} is outside the allowed workspace roots")
    return resolved


def _resolve_binary(candidate: str | None, expected: str) -> str:
    name = candidate or expected
    if Path(name).name != expected:
        raise ValueError(f"Unsupported slicer binary: {Path(name).name}")
    resolved = shutil.which(name)
    if not resolved:
        raise FileNotFoundError(f"Slicer binary not found: {expected}")
    return resolved


@dataclass
class SliceResult:
    ok: bool
    stl_path: str
    gcode_path: Optional[str]
    profile_path: str
    profile_sha256: str
    overlay_path: Optional[str]
    elapsed_seconds: float
    estimates: dict
    error: Optional[str]
    returncode: Optional[int]

    def to_dict(self) -> dict:
        return asdict(self)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_estimates(text: str) -> dict:
    estimates: dict[str, str] = {}
    for line in text.splitlines():
        low = line.lower()
        if "estimated printing time" in low:
            estimates["printing_time"] = line.strip().lstrip(";").strip()
        elif "filament used [mm]" in low:
            estimates["filament_mm"] = line.strip().lstrip(";").strip()
        elif "filament used [g]" in low:
            estimates["filament_g"] = line.strip().lstrip(";").strip()
        elif "total filament cost" in low:
            estimates["filament_cost"] = line.strip().lstrip(";").strip()
    return estimates


def slice_model(
    stl_path: str | Path,
    profile_path: str | Path,
    *,
    overlay_path: str | Path | None = None,
    output_path: str | Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    prusa_bin: str = "prusa-slicer",
    center: Optional[str] = None,
    rotate: Optional[float] = None,
    scale: Optional[float] = None,
) -> SliceResult:
    binary = _resolve_binary(prusa_bin, "prusa-slicer")
    stl_path = _confine_path(stl_path, "stl_path")
    profile_path = _confine_path(profile_path, "profile_path")
    overlay_path = _confine_path(overlay_path, "overlay_path") if overlay_path else None
    if not profile_path.exists():
        return SliceResult(
            ok=False, stl_path=str(stl_path), gcode_path=None, profile_path=str(profile_path),
            profile_sha256="", overlay_path=str(overlay_path) if overlay_path else None,
            elapsed_seconds=0.0, estimates={}, error=f"Profile not found: {profile_path}",
            returncode=None,
        )
    if not stl_path.exists():
        return SliceResult(
            ok=False, stl_path=str(stl_path), gcode_path=None, profile_path=str(profile_path),
            profile_sha256=sha256_file(profile_path), overlay_path=str(overlay_path) if overlay_path else None,
            elapsed_seconds=0.0, estimates={}, error=f"STL not found: {stl_path}",
            returncode=None,
        )
    started = time.monotonic()
    owns_output = output_path is None
    if output_path is None:
        out_dir = Path(tempfile.mkdtemp(prefix="caliclaw-slice-"))
        output_path = out_dir / (stl_path.stem + ".gcode")
    output_path = _confine_path(output_path, "output_path")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [binary, "--load", str(profile_path)]
    if overlay_path:
        cmd += ["--load", str(overlay_path)]
    if center:
        cmd += ["--center", center]
    if rotate is not None:
        cmd += ["--rotate", str(rotate)]
    if scale is not None:
        cmd += ["--scale", str(scale)]
    cmd += ["--export-gcode", "--output", str(output_path), str(stl_path)]

    env = {k: v for k, v in os.environ.items() if not any(s in k.lower() for s in ("secret", "token", "password", "api", "key", "auth"))}
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, env=env, start_new_session=True)
        elapsed = time.monotonic() - started
        if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
            return SliceResult(
                ok=False, stl_path=str(stl_path), gcode_path=str(output_path) if output_path.exists() else None,
                profile_path=str(profile_path), profile_sha256=sha256_file(profile_path),
                overlay_path=str(overlay_path) if overlay_path else None, elapsed_seconds=elapsed,
                estimates={}, error=(proc.stderr or proc.stdout or "PrusaSlicer failed").strip(),
                returncode=proc.returncode,
            )
        text = output_path.read_text(errors="replace")
        estimates = _parse_estimates(text)
        return SliceResult(
            ok=True, stl_path=str(stl_path), gcode_path=str(output_path),
            profile_path=str(profile_path), profile_sha256=sha256_file(profile_path),
            overlay_path=str(overlay_path) if overlay_path else None, elapsed_seconds=elapsed,
            estimates=estimates, error=None, returncode=proc.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        if getattr(exc, "pid", None):
            try:
                os.killpg(exc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return SliceResult(
            ok=False, stl_path=str(stl_path), gcode_path=None, profile_path=str(profile_path),
            profile_sha256=sha256_file(profile_path), overlay_path=str(overlay_path) if overlay_path else None,
            elapsed_seconds=elapsed, estimates={}, error=f"PrusaSlicer timed out after {timeout}s",
            returncode=None,
        )
