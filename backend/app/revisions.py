"""Revision versioning, restore, and slice provenance helpers."""
from __future__ import annotations

from typing import Optional

from .models import Revision
from .repository import create_revision, get_revision


def create_revision_child(
    db_path,
    project_id: str,
    parent_id: Optional[str],
    *,
    requirements: dict | None = None,
    assumptions: list | None = None,
    params: dict | None = None,
    source_hash: Optional[str] = None,
    artifact_id: Optional[str] = None,
    validation: dict | None = None,
    run_id: Optional[str] = None,
) -> Revision:
    revision = Revision(
        project_id=project_id,
        parent_id=parent_id,
        requirements=requirements or {},
        assumptions=assumptions or [],
        params=params or {},
        source_hash=source_hash,
        artifact_id=artifact_id,
        validation=validation or {},
        run_id=run_id,
    )
    return create_revision(db_path, revision)


def restore_revision(db_path, revision_id: str) -> Revision:
    """Create a new revision that restores an earlier one, preserving history."""
    original = get_revision(db_path, revision_id)
    if original is None:
        raise ValueError(f"Unknown revision: {revision_id}")
    return create_revision_child(
        db_path,
        project_id=original.project_id,
        parent_id=revision_id,
        requirements=dict(original.requirements),
        assumptions=list(original.assumptions),
        params=dict(original.params),
        source_hash=original.source_hash,
        artifact_id=original.artifact_id,
        validation=dict(original.validation),
    )


def is_slice_stale(
    slice_revision_id: str,
    slice_profile_hash: str,
    current_revision_id: str,
    current_profile_hash: str,
) -> bool:
    return slice_revision_id != current_revision_id or slice_profile_hash != current_profile_hash


def validate_protected_dimensions(
    parent_params: dict,
    child_params: dict,
    protected: list[str],
) -> list[str]:
    violations = []
    for key in protected:
        if key in parent_params and (key not in child_params or parent_params[key] != child_params[key]):
            violations.append(f"protected dimension changed: {key} {parent_params[key]} -> {child_params.get(key, "missing")}")
    return violations
