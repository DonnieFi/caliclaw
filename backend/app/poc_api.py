"""Proof-of-concept API wiring CaliClaw modules together."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .collector import SimulatedPrinterState
from .db import init_db
from .octoprint import camera_snapshot, control_job, get_job, get_printer, upload_file
import sqlite3
import uuid

from .provider import ProviderAdapter, reflection_config_from_env, comparison_config_from_env
from .repository import create_artifact, create_project, list_revisions
from .revisions import create_revision_child
from .slicer import slice_model
from .tool_loop import ToolLoop
from .worker import build_model

DB_PATH = (
    os.environ.get("CALICLAW_DB")
    or os.environ.get("BEAMBENCH_DB")
    or str(Path(__file__).resolve().parents[2] / "caliclaw.db")
)
init_db(DB_PATH)

router = APIRouter(prefix="/api", tags=["poc"])
printer = SimulatedPrinterState(temperature=200.0, bed_temperature=60.0)
ROOT = Path(__file__).resolve().parents[2]
_last_stl: dict[str, str] = {}
_last_revision_id: str | None = None
_last_slice: dict | None = None
_sessions: dict[str, list[dict]] = {}
_session_messages: list[dict] = []

def _load_state():
    global PROJECT, _last_stl, _last_revision_id
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT id FROM projects ORDER BY created_at DESC LIMIT 1").fetchone()
        if row:
            PROJECT = type("Project", (), {"id": row[0]})()
        else:
            from .repository import create_project as _cp
            PROJECT = _cp(DB_PATH, "POC workbench")
        if PROJECT is not None:
            rrow = conn.execute("SELECT id, artifact_id FROM revisions WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (PROJECT.id,)).fetchone()
            if rrow:
                _last_revision_id = rrow[0]
                if rrow[1]:
                    arow = conn.execute("SELECT path FROM artifacts WHERE id=?", (rrow[1],)).fetchone()
                    if arow and arow[0] and Path(arow[0]).exists():
                        _last_stl["current"] = arow[0]
        conn.close()
    except Exception:
        try:
            from .repository import create_project as _cp
            PROJECT = _cp(DB_PATH, "POC workbench")
        except Exception:
            PROJECT = None

_load_state()


class ChatRequest(BaseModel):
    message: str
    effort: str = "medium"
    model: str | None = None


class ChatResponse(BaseModel):
    reply: str
    tool_calls: int
    tokens: int | None = None
    reasoning_tokens: int | None = None
    iterations: int
    revisions: int = 0
    slice_estimate: str | None = None
    mesh_bounds: list | None = None
    mesh: dict | None = None
    stl_url: str | None = None
    preview_url: str | None = None
    revision_id: str | None = None
    tool_calls_detail: list[dict] = []


def _real_printer_status():
    try:
        p = get_printer()
        j = get_job()
        state = p.get("state", {})
        job = j.get("job", {}) or {}
        progress = (j.get("progress") or {}).get("completion")
        active = bool((state.get("flags") or {}).get("printing") or (state.get("flags") or {}).get("paused"))
        return {
            "source": "octoprint",
            "simulated": False,
            "state": state.get("text", "Unknown"),
            "flags": state.get("flags", {}),
            "hotend": p.get("temperature", {}).get("tool0", {}),
            "bed": p.get("temperature", {}).get("bed", {}),
            "job": (job.get("file") or {}).get("name") if active or job.get("file") else None,
            "progress": progress if active else None,
            "print_time": (j.get("progress") or {}).get("printTime") if active else None,
            "print_time_left": (j.get("progress") or {}).get("printTimeLeft") if active else None,
            "error": j.get("error") or state.get("error") or "",
        }
    except Exception as exc:
        s = printer.to_dict()
        s["source"] = "simulated (octoprint unavailable)"
        s["simulated"] = True
        s["error"] = str(exc)
        return s


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/printer")
def get_printer_status():
    return _real_printer_status()


@router.get("/camera")
def camera():
    try:
        data = camera_snapshot()
        return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/simulate/start")
def start_sim():
    printer.start()
    for _ in range(5):
        printer.advance(0.2)
    return printer.to_dict()


@router.get("/stl/current")
def current_stl():
    p = _last_stl.get("current")
    if not p or not Path(p).exists():
        raise HTTPException(status_code=404, detail="no STL available")
    return FileResponse(p, media_type="model/stl", filename="current.stl")


@router.get("/stl/preview")
def current_preview():
    p = _last_stl.get("preview")
    if not p or not Path(p).exists():
        raise HTTPException(status_code=404, detail="no preview available")
    return FileResponse(p, media_type="image/png")


@router.get("/revisions")
def revisions():
    if PROJECT is None:
        return []
    out = []
    for r in list_revisions(DB_PATH, PROJECT.id):
        out.append({
            "id": r.id,
            "parent_id": r.parent_id,
            "params": r.params,
            "source_hash": r.source_hash,
            "artifact_id": r.artifact_id,
            "validation": r.validation,
            "created_at": r.created_at,
        })
    return out


@router.get("/slice/current")
def slice_current():
    if _last_slice is None:
        raise HTTPException(status_code=404, detail="no slice available")
    return _last_slice


@router.post("/slice")
def slice_now():
    global _last_slice
    stl = _last_stl.get("current")
    if not stl or not Path(stl).exists():
        raise HTTPException(status_code=400, detail="no checked STL available; build first")
    r = slice_model(stl, str(ROOT / "profiles/ender3-proven-pla.ini"), overlay_path=str(ROOT / "profiles/ender3-speed-preference.ini"))
    _last_slice = {
        "ok": r.ok,
        "error": r.error,
        "estimates": r.estimates,
        "gcode_path": r.gcode_path,
        "profile_sha256": r.profile_sha256,
        "revision_id": _last_revision_id,
    }
    return _last_slice


# OctoPrint explicit controls (require confirm=true for risky actions)
class ControlRequest(BaseModel):
    confirm: bool = False


@router.post("/printer/upload")
async def printer_upload(file: UploadFile = File(...)):
    safe_name = Path(file.filename or "upload.gcode").name
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(status_code=400, detail="invalid filename")
    tmp_dir = Path(tempfile.mkdtemp())
    tmp = tmp_dir / safe_name
    tmp.write_bytes(await file.read())
    try:
        res = upload_file(tmp, safe_name, print_after=False)
        return res
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/printer/start")
def printer_start(req: ControlRequest):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required")
    if not _last_stl.get("current"):
        raise HTTPException(status_code=400, detail="no checked preparation available")
    status = _real_printer_status()
    if status.get("simulated"):
        raise HTTPException(status_code=400, detail="simulated printer cannot start live hardware")
    try:
        return control_job("start")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/printer/pause")
def printer_pause():
    status = _real_printer_status()
    if status.get("simulated"):
        raise HTTPException(status_code=400, detail="simulated printer cannot control live hardware")
    try:
        return control_job("pause")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/printer/resume")
def printer_resume():
    try:
        return control_job("resume")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/printer/cancel")
def printer_cancel(req: ControlRequest):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required")
    status = _real_printer_status()
    if status.get("simulated"):
        raise HTTPException(status_code=400, detail="simulated printer cannot control live hardware")
    try:
        return control_job("cancel")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, response: Response):
    global _session_messages, _last_revision_id
    session_id = request.cookies.get("caliclaw_session")
    if not session_id:
        session_id = uuid.uuid4().hex
        response.set_cookie("caliclaw_session", session_id, httponly=True, samesite="lax")
    cfg = None
    if getattr(req, "model", None) == "comparison":
        cfg = comparison_config_from_env()
        if cfg is None:
            base = reflection_config_from_env()
            if base is not None:
                base.name = "comparison"
                cfg = base
    if cfg is None:
        cfg = reflection_config_from_env()
    if cfg is None:
        raise HTTPException(status_code=503, detail="CALICLAW_API_KEY not configured")
    adapter = ProviderAdapter(cfg)

    def build(args):
        global _last_revision_id
        r = build_model(args.get("scad", ""))
        if r.ok and r.stl_path:
            _last_stl["current"] = r.stl_path
            global _last_slice
            _last_slice = None
            if r.preview_path:
                _last_stl["preview"] = r.preview_path
            try:
                rev = create_revision_child(
                    DB_PATH, PROJECT.id, _last_revision_id,
                    params={"scad": args.get("scad", "")[:120]},
                    source_hash=r.sha256,
                    validation={"watertight": (r.mesh or {}).get("watertight"),
                                "components": (r.mesh or {}).get("components"),
                                "bounds": (r.mesh or {}).get("bounds_mm"),
                                "volume": (r.mesh or {}).get("volume_mm3")})
                art = create_artifact(DB_PATH, __import__("backend.app.models", fromlist=["Artifact"]).Artifact(
                    revision_id=rev.id, kind="stl", path=r.stl_path,
                    sha256=r.sha256, bytes=r.bytes, metadata=r.mesh or {}))
                # update revision.artifact_id
                import sqlite3
                conn = sqlite3.connect(DB_PATH)
                conn.execute("UPDATE revisions SET artifact_id=? WHERE id=?", (art.id, rev.id))
                conn.commit()
                conn.close()
                _last_revision_id = rev.id
            except Exception as exc:
                import traceback; traceback.print_exc()
        return {"ok": r.ok, "error": r.error, "mesh": r.mesh, "sha256": r.sha256}

    def slice_fixed(args):
        global _last_slice
        stl = _last_stl.get("current")
        if not stl or not Path(stl).exists():
            return {"ok": False, "error": "no checked STL available; build first"}
        r = slice_model(stl, str(ROOT / "profiles/ender3-proven-pla.ini"), overlay_path=str(ROOT / "profiles/ender3-speed-preference.ini"))
        _last_slice = {
            "ok": r.ok, "error": r.error, "estimates": r.estimates,
            "gcode_path": r.gcode_path, "profile_sha256": r.profile_sha256,
            "revision_id": _last_revision_id,
        }
        return {"ok": r.ok, "error": r.error, "estimates": r.estimates}

    def printer_status(args):
        return _real_printer_status()

    def log_events(args):
        p = ROOT / "eval/fixtures/log-001.txt"
        return {"log": p.read_text() if p.exists() else ""}

    tools = {"build_model": build, "slice_model": slice_fixed, "get_printer_status": printer_status, "get_log_events": log_events}
    schemas = [
        {"type": "function", "function": {"name": "build_model", "description": "Compile OpenSCAD to a validated STL.", "parameters": {"type": "object", "properties": {"scad": {"type": "string"}}, "required": ["scad"]}}},
        {"type": "function", "function": {"name": "slice_model", "description": "Slice the checked bracket STL with the pinned profile.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "get_printer_status", "description": "Get printer status.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "get_log_events", "description": "Read Pi log events.", "parameters": {"type": "object", "properties": {}}}},
    ]
    history = _sessions.setdefault(session_id, [])
    history = history + [{"role": "user", "content": req.message}]
    loop = ToolLoop(adapter, tools, tool_schemas=schemas, max_iterations=8)
    result = loop.run(list(history), effort=req.effort)
    _sessions[session_id] = result.messages

    if result.error:
        raise HTTPException(status_code=502, detail=result.error)

    tool_detail = []
    mesh_bounds = None
    mesh = None
    slice_estimate = None
    for m in result.messages:
        if m.get("role") != "tool":
            continue
        content = m.get("content", "")
        try:
            data = json.loads(content)
        except Exception:
            data = {}
        tool_detail.append({"name": m.get("name"), "ok": bool(data.get("ok", True))})
        if isinstance(data.get("mesh"), dict):
            b = data["mesh"].get("bounds_mm")
            if b:
                mesh_bounds = b
            mesh = data["mesh"]
        if isinstance(data.get("estimates"), dict):
            est = data["estimates"].get("printing_time")
            if est:
                slice_estimate = est

    revs = 0
    try:
        revs = len(list_revisions(DB_PATH, PROJECT.id))
    except Exception:
        pass

    stl_url = "/api/stl/current" if _last_stl.get("current") else None
    preview_url = "/api/stl/preview" if _last_stl.get("preview") else None
    return ChatResponse(
        reply=result.final_content or "",
        tool_calls=result.tool_calls_total,
        tokens=result.usage.get("total_tokens"),
        reasoning_tokens=result.usage.get("reasoning_tokens"),
        iterations=result.iterations,
        revisions=revs,
        slice_estimate=slice_estimate,
        mesh_bounds=mesh_bounds,
        mesh=mesh,
        stl_url=stl_url,
        preview_url=preview_url,
        revision_id=_last_revision_id,
        tool_calls_detail=tool_detail,
    )
