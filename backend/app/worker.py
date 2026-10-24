"""Bounded OpenSCAD execution and artifact validation."""
from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

DEFAULT_TIMEOUT = 60

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
    base = Path(name).name
    if base != expected:
        raise ValueError(f"Unsupported CAD binary: {base}")
    resolved = shutil.which(name)
    if not resolved:
        raise FileNotFoundError(f"CAD binary not found: {expected}")
    return resolved


@dataclass
class BuildResult:
    ok: bool
    workspace: str
    scad_path: str
    stl_path: Optional[str]
    preview_path: Optional[str]
    sha256: Optional[str]
    bytes: Optional[int]
    elapsed_seconds: float
    mesh: Optional[dict]
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


def _validate_source(source: str) -> None:
    import re
    if re.search(r"\b(include|use)\b\s*<", source, re.IGNORECASE):
        raise ValueError("OpenSCAD include/use statements are not allowed")
    if re.search(r"\bimport\s*\(", source, re.IGNORECASE):
        raise ValueError("OpenSCAD import() is not allowed")
    for match in re.finditer(r'"([^"]*)"', source):
        value = match.group(1)
        if value.startswith("/") or ".." in value or "\\" in value:
            raise ValueError("Absolute or traversal paths are not allowed in SCAD strings")


def render_preview(stl_path: str | Path, workspace: Path, timeout: int = 60) -> Optional[str]:
    """Render an STL to a PNG using OpenSCAD under xvfb. Returns path or None."""
    stl_path = Path(stl_path)
    preview_scad = workspace / "preview.scad"
    preview_png = workspace / "preview.png"
    preview_scad.write_text(f'import("{stl_path.name}");\n', encoding="utf-8")
    if stl_path.parent != workspace:
        import shutil as _shutil
        _shutil.copy2(stl_path, workspace / stl_path.name)
    try:
        subprocess.run(
            ["xvfb-run", "-a", "openscad", "--render", "-o", str(preview_png), str(preview_scad)],
            cwd=str(workspace),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except Exception:
        return None
    if preview_png.exists() and preview_png.stat().st_size > 0:
        return str(preview_png)
    return None


def build_model(
    source: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    openscad_bin: str = "openscad",
    workdir: Optional[Path] = None,
) -> BuildResult:
    """Compile SCAD source to STL in an isolated workspace."""
    _validate_source(source)
    started = time.monotonic()
    binary = _resolve_binary(openscad_bin, "openscad")
    owns_workspace = workdir is None
    if workdir is None:
        workspace = Path(tempfile.mkdtemp(prefix="caliclaw-build-"))
    else:
        workspace = _confine_path(workdir, "workdir")
    workspace.mkdir(parents=True, exist_ok=True)
    scad_path = workspace / "input.scad"
    stl_path = workspace / "output.stl"
    scad_path.write_text(source, encoding="utf-8")

    try:
        env = {k: v for k, v in os.environ.items() if not any(s in k.lower() for s in ("secret", "token", "password", "api", "key", "auth"))}

        def _limits():
            try:
                resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
                resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout + 5))
            except (ValueError, resource.error):
                pass

        proc = subprocess.run(
            [binary, "-o", str(stl_path), str(scad_path)],
            cwd=str(workspace),
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
            start_new_session=True,
            preexec_fn=_limits,
        )
        # Cap retained diagnostics.
        if proc.stdout and len(proc.stdout) > 64 * 1024:
            proc.stdout = proc.stdout[:64 * 1024] + "\n...[truncated]"
        if proc.stderr and len(proc.stderr) > 64 * 1024:
            proc.stderr = proc.stderr[:64 * 1024] + "\n...[truncated]"
        elapsed = time.monotonic() - started
        if proc.returncode != 0 or not stl_path.exists():
            if owns_workspace:
                shutil.rmtree(workspace, ignore_errors=True)
            return BuildResult(
                ok=False, workspace=str(workspace), scad_path=str(scad_path),
                stl_path=None, preview_path=None, sha256=None, bytes=None, elapsed_seconds=elapsed,
                mesh=None, error=(proc.stderr or proc.stdout or "OpenSCAD failed").strip(),
                returncode=proc.returncode,
            )

        # Independent geometry validation.
        try:
            import trimesh
        except ImportError as exc:
            if owns_workspace:
                shutil.rmtree(workspace, ignore_errors=True)
            return BuildResult(
                ok=False, workspace=str(workspace), scad_path=str(scad_path),
                stl_path=None, preview_path=None, sha256=None, bytes=None,
                elapsed_seconds=elapsed, mesh=None, error=f"trimesh unavailable: {exc}",
                returncode=proc.returncode,
            )

        mesh = trimesh.load(stl_path)
        if not isinstance(mesh, trimesh.Trimesh):
            if owns_workspace:
                shutil.rmtree(workspace, ignore_errors=True)
            return BuildResult(
                ok=False, workspace=str(workspace), scad_path=str(scad_path),
                stl_path=None, preview_path=None, sha256=None, bytes=None, elapsed_seconds=elapsed,
                mesh=None, error="Loaded geometry is not a single mesh",
                returncode=proc.returncode,
            )
        mesh_info = {
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
            "volume_mm3": float(mesh.volume),
            "bounds_mm": [[float(v) for v in row] for row in mesh.bounds],
            "watertight": bool(mesh.is_watertight),
            "components": len(mesh.split()),
        }
        if not mesh.is_watertight or len(mesh.split()) != 1:
            if owns_workspace:
                shutil.rmtree(workspace, ignore_errors=True)
            return BuildResult(
                ok=False, workspace=str(workspace), scad_path=str(scad_path),
                stl_path=None, preview_path=None, sha256=None,
                bytes=None, elapsed_seconds=elapsed,
                mesh=mesh_info, error="STL is not a single watertight component",
                returncode=proc.returncode,
            )
        if mesh.volume <= 0:
            if owns_workspace:
                shutil.rmtree(workspace, ignore_errors=True)
            return BuildResult(
                ok=False, workspace=str(workspace), scad_path=str(scad_path),
                stl_path=None, preview_path=None, sha256=None,
                bytes=None, elapsed_seconds=elapsed,
                mesh=mesh_info, error="STL has non-positive volume",
                returncode=proc.returncode,
            )

        preview = render_preview(stl_path, workspace)
        return BuildResult(
            ok=True, workspace=str(workspace), scad_path=str(scad_path),
            stl_path=str(stl_path), preview_path=preview, sha256=sha256_file(stl_path),
            bytes=stl_path.stat().st_size, elapsed_seconds=elapsed,
            mesh=mesh_info, error=None, returncode=proc.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        if getattr(exc, "pid", None):
            try:
                os.killpg(exc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if owns_workspace:
            shutil.rmtree(workspace, ignore_errors=True)
        return BuildResult(
            ok=False, workspace=str(workspace), scad_path=str(scad_path),
            stl_path=None, preview_path=None,
            sha256=None, bytes=None, elapsed_seconds=elapsed,
            mesh=None, error=f"OpenSCAD timed out after {timeout}s",
            returncode=None,
        )
    finally:
        pass


def cleanup_workspace(workspace: str | Path) -> None:
    shutil.rmtree(workspace, ignore_errors=True)


def result_to_json(result: BuildResult) -> str:
    return json.dumps(result.to_dict(), sort_keys=True)
