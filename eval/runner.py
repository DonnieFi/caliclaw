"""Repeatable evaluation runner and attempt accounting."""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

CASES_PATH = Path(__file__).resolve().parent / "cases.json"


@dataclass
class AttemptRecord:
    case_id: str
    repetition: int
    success: bool
    tokens: Optional[int]
    tool_calls: int
    elapsed_seconds: float
    model: Optional[str] = None
    provider: Optional[str] = None
    finish_reason: Optional[str] = None
    truncated: bool = False
    failure_category: Optional[str] = None
    error: Optional[str] = None


@dataclass
class EvalSummary:
    cases: int
    repetitions: int
    successes: int
    success_rate: float
    total_tokens: int
    tokens_per_success: Optional[float]
    attempts: list[AttemptRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cases": self.cases,
            "repetitions": self.repetitions,
            "successes": self.successes,
            "success_rate": self.success_rate,
            "total_tokens": self.total_tokens,
            "tokens_per_success": self.tokens_per_success,
            "attempts": [asdict(a) for a in self.attempts],
        }


def load_cases(path: Optional[Path] = None) -> list[dict[str, Any]]:
    path = path or CASES_PATH
    data = json.loads(path.read_text())
    return data.get("cases", [])


def run_eval(
    solver: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    repetitions: int = 1,
    cases: Optional[list[dict[str, Any]]] = None,
    budget_tokens: Optional[int] = None,
) -> EvalSummary:
    cases = cases if cases is not None else load_cases()
    attempts: list[AttemptRecord] = []
    successes = 0
    total_tokens = 0
    any_tokens = False
    budget_exceeded = False
    for case in cases:
        if budget_exceeded:
            break
        for rep in range(repetitions):
            if budget_exceeded:
                break
            started = time.monotonic()
            try:
                result = solver(case)
                success = bool(result.get("success", False))
                tokens = result.get("tokens", None)
                if tokens is not None:
                    tokens = int(tokens)
                tool_calls = int(result.get("tool_calls", 0) or 0)
                failure_category = result.get("failure_category")
                error = result.get("error")
                model = result.get("model")
                provider = result.get("provider")
                finish_reason = result.get("finish_reason")
                truncated = bool(result.get("truncated", False))
            except Exception as exc:  # record, don't crash the whole run
                success = False
                tokens = None
                tool_calls = 0
                failure_category = "exception"
                error = str(exc)
                model = None
                provider = None
                finish_reason = None
                truncated = False
            elapsed = time.monotonic() - started
            if success:
                successes += 1
            if tokens is not None:
                total_tokens += tokens
                any_tokens = True
            attempts.append(AttemptRecord(
                case_id=case["id"],
                repetition=rep,
                success=success,
                tokens=tokens,
                tool_calls=tool_calls,
                elapsed_seconds=elapsed,
                model=model,
                provider=provider,
                finish_reason=finish_reason,
                truncated=truncated,
                failure_category=failure_category,
                error=error,
            ))
            if budget_tokens is not None and total_tokens > budget_tokens:
                budget_exceeded = True
                break

    success_rate = successes / len(attempts) if attempts else 0.0
    if successes and any_tokens:
        tokens_per_success = total_tokens / successes
    else:
        tokens_per_success = None
    return EvalSummary(
        cases=len(cases),
        repetitions=repetitions,
        successes=successes,
        success_rate=success_rate,
        total_tokens=total_tokens,
        tokens_per_success=tokens_per_success,
        attempts=attempts,
    )
