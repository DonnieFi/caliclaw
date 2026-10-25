"""Proof-of-concept API wiring CaliClaw modules together."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional, Literal

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .collector import SimulatedPrinterState
from .printer_logs import get_log_events
from .db import init_db
from .geometry import validate_stl
from .printer_config import PrinterConfig, active_printer, list_printers, save_printer, select_printer, public_printer
from .printer_discovery import discover_printers, probe_printer, inspect_profile
from .host_checks import CHECK_NAMES, run_check, restart_camera, known_idle
from .print_preparation import selected_profile, profile_snapshot, digest, validate_preparation, printer_identity
from .parts import save_part
from .cad_revision import build_revision
from .conversations import load_conversation, save_conversation
from .repository import get_revision, get_artifact
from .fit import fit_memory_text, project_snapshot, record_fit
from .octoprint import (
    camera_snapshot,
    control_job,
    get_job,
    get_printer,
    set_bed_target,
    set_printhead_factor,
    set_tool_target,
    upload_file,
)
import sqlite3
import uuid

from .provider import ProviderAdapter, reflection_config_from_env, comparison_config_from_env
from .repository import create_artifact, create_project, get_project, list_revisions
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
_uploaded_slice: dict | None = None
_control_lock = threading.Lock()
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
            PROJECT = _cp(DB_PATH, "Workshop")
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
            PROJECT = _cp(DB_PATH, "Workshop")
        except Exception:
            PROJECT = None

_load_state()


WORKBENCH_BRIEF = (
    "You are the workshop assistant for one functional part. "
    "Ask for a missing fit dimension. Label anything you assume. "
    "Change only what the latest fit note asks for, and leave kept features alone. "
    "Build with OpenSCAD through build_model. Slice only after the mesh checks pass. "
    "You may read printer status and logs. Do not start, pause, or cancel a print."
)


class FitRequest(BaseModel):
    note: str
    measured: dict = {}
    keep: list[str] = []


class ChatRequest(BaseModel):
    message: str
    effort: str = "medium"
    model: str | None = None
    phase: Literal["brainstorm", "design", "revise"] = "brainstorm"


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
        s["error"] = "Printer status unavailable."
        return s


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/project")
def project_view():
    if PROJECT is None:
        raise HTTPException(status_code=404, detail="no project")
    stored = get_project(DB_PATH, PROJECT.id)
    return project_snapshot(DB_PATH, PROJECT.id, stored.name if stored else "Workshop")


@router.post("/fit")
def post_fit(req: FitRequest):
    if PROJECT is None:
        raise HTTPException(status_code=404, detail="no project")
    try:
        return record_fit(
            DB_PATH,
            PROJECT.id,
            note=req.note,
            revision_id=_last_revision_id,
            measured=req.measured,
            keep=req.keep,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/printers")
def printers_view():
    return list_printers()


@router.post("/printers/discover")
def printers_discover():
    return discover_printers()


@router.post("/printers/probe")
def printers_probe(config: PrinterConfig):
    if config.id and not config.api_key:
        from .printer_config import get_printer_config
        saved = get_printer_config(config.id)
        if saved and saved.base_url == config.base_url:
            config = config.model_copy(update={'api_key': saved.api_key})
    return probe_printer(config)


@router.get("/printers/{printer_id}/setup")
def printer_setup_view(printer_id: str):
    from .printer_config import get_printer_config
    config = get_printer_config(printer_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Unknown saved printer.")
    return config.model_dump(exclude={"api_key"})


class ProfileInspectRequest(BaseModel):
    path: str


@router.post("/printers/profile/inspect")
def profile_inspect(req: ProfileInspectRequest):
    try:
        return inspect_profile(req.path)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Profile is unavailable or is not a supported INI file.") from exc


@router.post("/printers")
def printers_save(config: PrinterConfig):
    global _last_slice, _uploaded_slice
    with _control_lock:
        try:
            result = save_printer(config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Could not update that printer.") from exc
        _last_slice = None
        _uploaded_slice = None
        return result


class PrinterSelectRequest(BaseModel):
    printer_id: str


@router.post("/printers/select")
def printers_select(req: PrinterSelectRequest):
    global _last_slice, _uploaded_slice
    with _control_lock:
        try:
            result = select_printer(req.printer_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Unknown saved printer.") from exc
        _last_slice = None
        _uploaded_slice = None
        return result


@router.get("/printer")
def get_printer_status():
    with _control_lock:
        return _selected_printer_status()


def _selected_printer_status():
    status = _real_printer_status()
    config = active_printer()
    status['printer'] = public_printer(config) if config else None
    status['printer_id'] = printer_identity()
    return status


@router.get("/camera")
def camera():
    try:
        data = camera_snapshot()
        return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Snapshot unavailable.") from exc


@router.post("/simulate/start")
def start_sim():
    printer.start()
    for _ in range(5):
        printer.advance(0.2)
    return printer.to_dict()


MAX_STL_BYTES = 20 * 1024 * 1024


@router.post("/stl/import")
async def import_stl(file: UploadFile = File(...)):
    global _last_revision_id, _last_slice
    if PROJECT is None:
        raise HTTPException(status_code=404, detail="No project available.")
    if Path(file.filename or "").suffix.lower() != ".stl":
        raise HTTPException(status_code=400, detail="Choose an STL file.")
    with tempfile.TemporaryDirectory(prefix="caliclaw-import-") as folder:
        path = Path(folder) / "import.stl"
        size = 0
        with path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_STL_BYTES:
                    raise HTTPException(status_code=413, detail="STL must be at most 20 MiB.")
                target.write(chunk)
        try:
            report = validate_stl(path)
            if not report.ok:
                raise ValueError("invalid mesh")
        except Exception as exc:
            raise HTTPException(status_code=400, detail="STL must contain one watertight solid with positive volume.") from exc
        validation = report.to_dict()
        validation.pop("path", None)
        rev, art = save_part(DB_PATH, PROJECT.id, _last_revision_id, path,
                             params={"source": "import"}, validation=validation)
    _last_revision_id = rev.id
    _last_stl.clear()
    _last_stl["current"] = art.path
    _last_slice = None
    return {"revision_id": rev.id, "stl_url": f"/api/revisions/{rev.id}/stl", "mesh": validation}


@router.get("/revisions/{revision_id}/stl")
def revision_stl(revision_id: str):
    rev = get_revision(DB_PATH, revision_id)
    art = get_artifact(DB_PATH, rev.artifact_id) if rev and rev.artifact_id else None
    if not rev or PROJECT is None or rev.project_id != PROJECT.id or not art or not art.path or not Path(art.path).is_file():
        raise HTTPException(status_code=404, detail="STL unavailable.")
    return FileResponse(art.path, media_type="model/stl", filename=f"{rev.id}.stl")


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


def preparation_view():
    try:
        profile = selected_profile()
        label = profile["label"]
    except (OSError, ValueError):
        label = "Profile unavailable"
    reason = "Slice the checked part first."
    ready = False
    try:
        validate_preparation(_last_slice, _last_stl.get("current"), _last_revision_id)
        ready = True
        reason = "Checked slice ready to upload."
    except (ValueError, OSError, KeyError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "Preparation unavailable. Slice again."
    uploaded = bool(ready and _uploaded_slice and _last_slice and _uploaded_slice.get("slice_id") == _last_slice.get("id") and _uploaded_slice.get("printer_id") == printer_identity())
    return {"profile": label, "ready": ready, "uploaded": uploaded, "reason": reason,
            "filename": _uploaded_slice["filename"] if uploaded else None,
            "slice_id": _last_slice.get("id") if _last_slice else None,
            "estimates": _last_slice.get("estimates", {}) if _last_slice else {}}


@router.get("/slice/current")
def slice_current():
    return preparation_view()


@router.post("/slice")
def slice_now():
    global _last_slice, _uploaded_slice
    snapshot = None
    overlay_snapshot = None
    try:
        # Capture settings quickly; slicing must not block live pause/cancel controls.
        with _control_lock:
            stl = _last_stl.get("current")
            revision_id = _last_revision_id
            if not stl or not Path(stl).exists():
                raise HTTPException(status_code=400, detail="No checked STL available; build or import first.")
            _uploaded_slice = None
            _last_slice = None
            profile = selected_profile()
            snapshot = profile_snapshot(profile)
            mesh_hash = digest(stl)
            overlay_snapshot = snapshot.parent / 'overlay.ini' if profile['overlay_bytes'] is not None else None
            if overlay_snapshot:
                overlay_snapshot.write_bytes(profile['overlay_bytes'])
            sliced_printer_id = printer_identity()
        r = slice_model(stl, str(snapshot), **({'overlay_path': str(overlay_snapshot)} if overlay_snapshot else {}))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Slicer or profile unavailable.") from exc
    finally:
        if overlay_snapshot:
            overlay_snapshot.unlink(missing_ok=True)
        if snapshot:
            snapshot.unlink(missing_ok=True)
            snapshot.parent.rmdir()
    if not r.ok or not r.gcode_path:
        raise HTTPException(status_code=400, detail="Slice failed. Check the part and profile.")
    with _control_lock:
        if (printer_identity() != sliced_printer_id or revision_id != _last_revision_id
                or _last_stl.get("current") != stl or digest(stl) != mesh_hash):
            raise HTTPException(status_code=409, detail="Printer or part changed during slicing. Slice again.")
        _last_slice = {
            "id": uuid.uuid4().hex, "ok": True, "error": None,
            "estimates": r.estimates, "gcode_path": r.gcode_path,
            "profile_sha256": profile["sha256"], "overlay_sha256": profile["overlay_sha256"],
            "printer_id": sliced_printer_id, "profile_confirmed": profile["confirmed"],
            "mesh_sha256": mesh_hash, "gcode_sha256": digest(r.gcode_path), "revision_id": revision_id,
        }
        return {"ok": True, **preparation_view()}


@router.get("/host/checks/{name}")
def host_check(name: str):
    try:
        return run_check(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unknown host check.") from exc


# OctoPrint explicit controls (require confirm=true for risky actions)
def _require_printer_selection(identity):
    config = active_printer()
    if config and config.id != "environment" and identity != printer_identity():
        raise HTTPException(status_code=409, detail="Selected printer changed. Refresh status and confirm again.")


class ControlRequest(BaseModel):
    confirm: bool = False
    printer_id: str = ""


@router.post("/camera/restart")
def camera_restart(req: ControlRequest):
    with _control_lock:
        _require_printer_selection(req.printer_id)
        return _camera_restart(req)


def _camera_restart(req):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirm camera service restart first.")
    try:
        return restart_camera(_real_printer_status)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def checked_preparation():
    try:
        validate_preparation(_last_slice, _last_stl.get("current"), _last_revision_id)
    except (OSError, ValueError, KeyError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else "Preparation unavailable. Slice again."
        raise HTTPException(status_code=409, detail=detail) from exc
    return _last_slice


@router.post("/printer/upload")
def printer_upload(req: ControlRequest | None = None):
    with _control_lock:
        _require_printer_selection(req.printer_id if req else "")
        return _upload_checked_slice()


def _upload_checked_slice():
    global _uploaded_slice
    preparation = checked_preparation()
    if not known_idle(_real_printer_status()):
        raise HTTPException(status_code=409, detail="Upload requires a known-idle live printer.")
    _uploaded_slice = None
    filename = "caliclaw-" + preparation["id"] + ".gcode"
    try:
        result = upload_file(preparation["gcode_path"], filename, print_after=False)
        remote = result.get("files", {}).get("local", {})
        if remote.get("name") != filename or remote.get("path", filename) != filename:
            raise ValueError("upload identity mismatch")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Checked slice upload could not be verified.") from exc
    _uploaded_slice = {"slice_id": preparation["id"], "filename": filename, "printer_id": printer_identity()}
    return preparation_view()


class StartRequest(ControlRequest):
    filename: str = ""
    slice_id: str = ""


@router.post("/printer/start")
def printer_start(req: StartRequest):
    with _control_lock:
        return _start_checked_print(req)


def _start_checked_print(req):
    global _uploaded_slice
    _require_printer_selection(req.printer_id)
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required")
    preparation = checked_preparation()
    if not _uploaded_slice or _uploaded_slice.get("printer_id") != printer_identity() or _uploaded_slice["slice_id"] != preparation["id"] or req.slice_id != preparation["id"] or req.filename != _uploaded_slice["filename"]:
        raise HTTPException(status_code=409, detail="Upload and confirm the current checked slice first.")
    if not known_idle(_real_printer_status()):
        raise HTTPException(status_code=409, detail="Start requires a known-idle live printer.")
    try:
        job = get_job()
        selected = (job.get("job") or {}).get("file") or {}
        if selected.get("origin") != "local" or selected.get("path") != req.filename:
            raise HTTPException(status_code=409, detail="Selected printer file changed. Upload the checked slice again.")
        if str(job.get("state", "")).lower() not in ("operational", "ready", "idle"):
            raise HTTPException(status_code=409, detail="Printer is no longer idle.")
        # Consume authorization before dispatch: a timeout may still have started the job.
        _uploaded_slice = None
        return control_job("start")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Printer start unavailable.") from exc


def confirmed_job_control(req, action):
    with _control_lock:
        _require_printer_selection(req.printer_id)
        return _confirmed_job_control(req, action)


def _confirmed_job_control(req, action):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required")
    status = _real_printer_status()
    if status.get("simulated") or status.get("source") != "octoprint":
        raise HTTPException(status_code=409, detail="Live printer status required.")
    flags = status.get("flags") or {}
    if action == "resume" and not flags.get("paused"):
        raise HTTPException(status_code=409, detail="Printer is not paused.")
    if action == "pause" and not flags.get("printing"):
        raise HTTPException(status_code=409, detail="Printer is not printing.")
    if action == "cancel" and not (flags.get("printing") or flags.get("paused")):
        raise HTTPException(status_code=409, detail="No active print to cancel.")
    try:
        return control_job(action)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Printer control unavailable.") from exc


@router.post("/printer/pause")
def printer_pause(req: ControlRequest):
    return confirmed_job_control(req, "pause")


@router.post("/printer/resume")
def printer_resume(req: ControlRequest):
    return confirmed_job_control(req, "resume")


TOOL_RANGE = (0, 280)
BED_RANGE = (0, 120)
FACTOR_RANGE = (10, 200)


class TargetsRequest(BaseModel):
    printer_id: str = ""
    tool: float | None = None
    bed: float | None = None


class FactorsRequest(BaseModel):
    printer_id: str = ""
    feedrate: int | None = None
    flowrate: int | None = None


def _in_range(name: str, value: float, lo: float, hi: float) -> None:
    if value < lo or value > hi:
        raise HTTPException(status_code=400, detail=f"{name} must be between {lo} and {hi}")


def _refuse_simulated() -> None:
    status = _real_printer_status()
    if status.get("simulated"):
        raise HTTPException(status_code=400, detail="simulated printer cannot change live settings")


@router.post("/printer/targets")
def printer_targets(req: TargetsRequest):
    with _control_lock:
        _require_printer_selection(req.printer_id)
        return _printer_targets(req)


def _printer_targets(req):
    if req.tool is None and req.bed is None:
        raise HTTPException(status_code=400, detail="set a nozzle or bed target")
    if req.tool is not None:
        _in_range("nozzle", req.tool, *TOOL_RANGE)
    if req.bed is not None:
        _in_range("bed", req.bed, *BED_RANGE)
    _refuse_simulated()
    try:
        if req.tool is not None:
            set_tool_target(req.tool)
        if req.bed is not None:
            set_bed_target(req.bed)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="printer settings were not accepted") from exc
    return {"ok": True}


@router.post("/printer/factors")
def printer_factors(req: FactorsRequest):
    with _control_lock:
        _require_printer_selection(req.printer_id)
        return _printer_factors(req)


def _printer_factors(req):
    if req.feedrate is None and req.flowrate is None:
        raise HTTPException(status_code=400, detail="set a speed or flow")
    if req.feedrate is not None:
        _in_range("speed", req.feedrate, *FACTOR_RANGE)
    if req.flowrate is not None:
        _in_range("flow", req.flowrate, *FACTOR_RANGE)
    _refuse_simulated()
    try:
        if req.feedrate is not None:
            set_printhead_factor("feedrate", req.feedrate)
        if req.flowrate is not None:
            set_printhead_factor("flowrate", req.flowrate)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="printer settings were not accepted") from exc
    return {"ok": True}


@router.post("/printer/cancel")
def printer_cancel(req: ControlRequest):
    return confirmed_job_control(req, "cancel")


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
    history = (load_conversation(DB_PATH, PROJECT.id, session_id) if PROJECT is not None else _sessions.get(session_id, []))
    history = [m for m in history if m.get("role") != "system"]
    history.append({"role": "user", "content": req.message})

    def remember(messages):
        clean = [m for m in messages if m.get("role") != "system"]
        _sessions[session_id] = clean
        if PROJECT is not None:
            save_conversation(DB_PATH, PROJECT.id, session_id, clean)

    remember(history)
    if cfg is None:
        reply = ("Saved your brainstorm. What must the part fit, which dimensions have you measured, and what must stay unchanged? "
                 "Choose Design when ready. A configured model key is needed to build." if req.phase == "brainstorm" else
                 "Your notes are saved. Design and revise need a configured model key; the current part is unchanged.")
        remember(history + [{"role": "assistant", "content": reply}])
        return ChatResponse(reply=reply, tool_calls=0, iterations=0)
    if req.phase == "revise" and not _last_revision_id:
        raise HTTPException(status_code=400, detail="Build or import a part before revising.")
    adapter = ProviderAdapter(cfg)
    built = False
    parent_id = _last_revision_id if req.phase == "revise" else None

    def build(args):
        nonlocal built
        global _last_revision_id, _last_slice
        if built:
            return {"ok": False, "error": "One revision was already built this turn."}
        if PROJECT is None:
            return {"ok": False, "error": "No project available."}
        try:
            r, rev, art = build_revision(DB_PATH, PROJECT.id, parent_id, args.get("scad", ""), args.get("dimensions", {}))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if rev and art:
            _last_stl.clear()
            _last_stl["current"] = art.path
            _last_slice = None
            _last_revision_id = rev.id
            built = True
        return {"ok": r.ok, "error": r.error, "mesh": r.mesh, "sha256": r.sha256}

    def slice_fixed(args):
        try:
            return slice_now()
        except HTTPException as exc:
            return {"ok": False, "error": exc.detail}

    def printer_status(args):
        return _real_printer_status()

    def log_events(args):
        return get_log_events()

    tools = {"build_model": build, "slice_model": slice_fixed, "get_printer_status": printer_status, "get_log_events": log_events}
    schemas = [
        {"type": "function", "function": {"name": "build_model", "description": "Compile OpenSCAD to a validated STL.", "parameters": {"type": "object", "properties": {"scad": {"type": "string"}, "dimensions": {"type": "object", "description": "Named numeric dimensions. Reference these names in scad; do not assign them there."}}, "required": ["scad", "dimensions"]}}},
        {"type": "function", "function": {"name": "slice_model", "description": "Slice the checked bracket STL with the pinned profile.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "get_printer_status", "description": "Get printer status.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "get_log_events", "description": "Read configured collected printer logs, or report unavailable. Check source_updated_at; logs may be stale.", "parameters": {"type": "object", "properties": {}}}},
    ]
    if req.phase == "brainstorm":
        tools = {name: fn for name, fn in tools.items() if name in ("get_printer_status", "get_log_events")}
        schemas = [schema for schema in schemas if schema["function"]["name"] in tools]
    prompt = [{"role": "system", "content": WORKBENCH_BRIEF}]
    prompt.append({"role": "system", "content": (
        "Brainstorm only. Ask about measurements and record assumptions. Do not build or slice." if req.phase == "brainstorm" else
        "The user explicitly selected " + req.phase + ". Build at most one successful revision. Supply named numeric dimensions separately from the CAD body.")})
    if parent_id:
        parent = get_revision(DB_PATH, parent_id)
        if parent:
            prompt.append({"role": "system", "content": "Current part to revise: " + json.dumps(parent.params)})
    if PROJECT is not None:
        memory = fit_memory_text(DB_PATH, PROJECT.id)
        if memory:
            prompt.append({"role": "system", "content": memory})
    loop = ToolLoop(adapter, tools, tool_schemas=schemas, max_iterations=8)
    result = loop.run(prompt + history, effort=req.effort)
    remember(result.messages)

    if result.error:
        raise HTTPException(status_code=502, detail=result.error)

    tool_detail = []
    mesh_bounds = None
    mesh = None
    slice_estimate = None
    for m in result.messages[len(prompt) + len(history):]:
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
