"""Pydantic contracts for CaliClaw persisted entities."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Project(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    description: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class Profile(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    kind: str
    path: Optional[str] = None
    sha256: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    revision_id: Optional[str] = None
    kind: str
    path: Optional[str] = None
    sha256: Optional[str] = None
    bytes: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class Revision(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    project_id: str
    parent_id: Optional[str] = None
    requirements: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[Any] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    source_hash: Optional[str] = None
    artifact_id: Optional[str] = None
    validation: dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)


class Event(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    source_id: str
    cursor: Optional[str] = None
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    observed_at: str = Field(default_factory=utc_now)
    dedup_key: Optional[str] = None


class RunAttempt(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str
    attempt_index: int
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    finish_reason: Optional[str] = None
    started_at: str = Field(default_factory=utc_now)
    finished_at: Optional[str] = None
    usage: dict[str, Any] = Field(default_factory=dict)


class Run(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    project_id: Optional[str] = None
    revision_id: Optional[str] = None
    provider: str
    model: str
    effort: Optional[str] = None
    prompt_version: Optional[str] = None
    tool_version: Optional[str] = None
    status: str
    started_at: str = Field(default_factory=utc_now)
    finished_at: Optional[str] = None
    usage: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)


def to_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def from_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)
