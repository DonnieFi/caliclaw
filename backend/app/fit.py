"""Measured fit notes. A note remembers what failed without replacing the part."""
from __future__ import annotations

import uuid
from typing import Any

from .db import connect
from .models import from_json, to_json, utc_now
from .repository import get_revision, list_revisions


def record_fit(
    db_path,
    project_id: str,
    *,
    note: str,
    revision_id: str | None = None,
    measured: dict[str, Any] | None = None,
    keep: list[str] | None = None,
) -> dict[str, Any]:
    text = (note or "").strip()
    if not text:
        raise ValueError("a fit note needs what you measured")
    kept = [str(name).strip() for name in (keep or []) if str(name).strip()]
    report_id = uuid.uuid4().hex
    created_at = utc_now()
    measured_values = measured or {}
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO fit_reports
            (id, project_id, revision_id, note, measured_json, keep_json, created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (
                report_id,
                project_id,
                revision_id,
                text,
                to_json(measured_values),
                to_json(kept),
                created_at,
            ),
        )
    return {
        "id": report_id,
        "project_id": project_id,
        "revision_id": revision_id,
        "note": text,
        "measured": measured_values,
        "keep": kept,
        "created_at": created_at,
    }


def list_fit(db_path, project_id: str) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM fit_reports WHERE project_id=? ORDER BY created_at",
            (project_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "project_id": row["project_id"],
            "revision_id": row["revision_id"],
            "note": row["note"],
            "measured": from_json(row["measured_json"], {}),
            "keep": from_json(row["keep_json"], []),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def protected_names(reports: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for report in reports:
        for name in report.get("keep") or []:
            if name not in names:
                names.append(name)
    return names


def project_snapshot(db_path, project_id: str, name: str) -> dict[str, Any]:
    revisions = list_revisions(db_path, project_id)
    latest = revisions[-1] if revisions else None
    reports = list_fit(db_path, project_id)
    revision_view = None
    if latest is not None:
        loaded = get_revision(db_path, latest.id) or latest
        revision_view = {
            "id": loaded.id,
            "parent_id": loaded.parent_id,
            "requirements": loaded.requirements,
            "assumptions": loaded.assumptions,
            "params": loaded.params,
            "validation": loaded.validation,
            "created_at": loaded.created_at,
        }
    return {
        "id": project_id,
        "name": name,
        "revision": revision_view,
        "fit": reports,
        "keep": protected_names(reports),
    }


def fit_memory_text(db_path, project_id: str) -> str:
    reports = list_fit(db_path, project_id)
    if not reports:
        return ""
    lines = [
        "Measured fit notes for this part. Change only what a note asks for.",
        "Do not redesign kept features.",
    ]
    keep = protected_names(reports)
    if keep:
        lines.append("Keep unchanged: " + ", ".join(keep) + ".")
    for report in reports:
        measured = report["measured"] or {}
        detail = ""
        if measured:
            detail = " Measured: " + ", ".join(f"{key}={value}" for key, value in measured.items()) + "."
        lines.append(f"- {report['note']}{detail}")
    return "\n".join(lines)
