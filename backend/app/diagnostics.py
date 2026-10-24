"""Evidence-backed diagnostic helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List, Optional


@dataclass
class Evidence:
    source: str
    excerpt: str
    kind: str = "observed"  # observed | inferred | missing
    cursor: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Diagnosis:
    summary: str
    evidence: List[Evidence]
    hypotheses: List[str]
    uncertainty: str
    next_checks: List[str]
    stale: bool = False
    read_only: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def build_diagnosis(
    summary: str,
    evidence: list[dict],
    uncertainty: str,
    next_checks: list[str],
    hypotheses: list[str] | None = None,
    stale: bool = False,
) -> Diagnosis:
    return Diagnosis(
        summary=summary,
        evidence=[Evidence(**e) for e in evidence],
        hypotheses=hypotheses or [],
        uncertainty=uncertainty,
        next_checks=next_checks,
        stale=stale,
        read_only=True,
    )
