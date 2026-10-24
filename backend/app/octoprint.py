"""Read-only (and explicitly controlled) OctoPrint client."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def base_url() -> str:
    url = os.environ.get("OCTOPRINT_BASE_URL", "").strip().rstrip("/")
    if not url:
        raise RuntimeError("OCTOPRINT_BASE_URL not configured")
    return url


def api_key() -> str:
    key = os.environ.get("OCTOPRINT_API_KEY", "")
    if not key:
        raise RuntimeError("OCTOPRINT_API_KEY not configured")
    return key


def _headers() -> dict[str, str]:
    return {"X-Api-Key": api_key()}


def get_version() -> dict[str, Any]:
    r = httpx.get(base_url() + "/api/version", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def get_printer() -> dict[str, Any]:
    r = httpx.get(base_url() + "/api/printer", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def get_job() -> dict[str, Any]:
    r = httpx.get(base_url() + "/api/job", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def camera_snapshot() -> bytes:
    r = httpx.get(base_url() + "/webcam/?action=snapshot", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.content


def list_files() -> dict[str, Any]:
    r = httpx.get(base_url() + "/api/files", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def upload_file(path: str | Path, filename: Optional[str] = None, *, print_after: bool = False) -> dict[str, Any]:
    path = Path(path)
    safe_name = Path(filename or path.name).name
    if not safe_name or safe_name in (".", ".."):
        raise ValueError("invalid upload filename")
    with path.open("rb") as f:
        files = {"file": (safe_name, f, "application/octet-stream")}
        data = {"select": "true", "print": "true" if print_after else "false"}
        r = httpx.post(base_url() + "/api/files/local", headers=_headers(), files=files, data=data, timeout=60)
    r.raise_for_status()
    return r.json()


def _post_job(payload: dict[str, Any]) -> dict[str, Any]:
    r = httpx.post(base_url() + "/api/job", headers=_headers(), json=payload, timeout=10)
    r.raise_for_status()
    if not r.content:
        return {}
    try:
        return r.json()
    except Exception:
        return {}


def start_job() -> dict[str, Any]:
    return _post_job({"command": "start"})


def pause_job() -> dict[str, Any]:
    return _post_job({"command": "pause", "action": "pause"})


def resume_job() -> dict[str, Any]:
    return _post_job({"command": "pause", "action": "resume"})


def cancel_job() -> dict[str, Any]:
    return _post_job({"command": "cancel"})


def restart_job() -> dict[str, Any]:
    return _post_job({"command": "restart"})


def control_job(command: str) -> dict[str, Any]:
    if command == "start":
        return start_job()
    if command == "pause":
        return pause_job()
    if command == "resume":
        return resume_job()
    if command == "cancel":
        return cancel_job()
    if command == "restart":
        return restart_job()
    raise ValueError(f"unknown job command: {command}")
