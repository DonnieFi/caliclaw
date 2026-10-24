"""Measured-spec tool loop with bounded repair."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

MAX_ITERATIONS = 8


@dataclass
class ToolLoopResult:
    messages: list[dict[str, Any]]
    final_content: str
    tool_calls_total: int
    iterations: int
    usage: dict[str, Any] = field(default_factory=dict)
    finish_reason: Optional[str] = None
    error: Optional[str] = None


class ToolLoop:
    def __init__(
        self,
        provider: Any,
        tools: dict[str, Callable[[dict[str, Any]], Any]],
        tool_schemas: Optional[list[dict[str, Any]]] = None,
        max_iterations: int = MAX_ITERATIONS,
    ):
        self.provider = provider
        self.tools = tools
        self.tool_schemas = tool_schemas or []
        self.max_iterations = max_iterations

    def _validate_args(self, name: str, args: dict[str, Any]) -> Optional[str]:
        schema = None
        for s in self.tool_schemas:
            if s.get("function", {}).get("name") == name:
                schema = s
                break
        if not schema:
            return None
        params = schema.get("function", {}).get("parameters", {})
        for req in params.get("required", []):
            if req not in args:
                return f"missing required argument: {req}"
        props = params.get("properties", {})
        for key, value in args.items():
            if key not in props:
                continue
            typ = props[key].get("type")
            if typ == "string" and not isinstance(value, str):
                return f"argument {key} must be a string"
            if typ == "integer" and not isinstance(value, int):
                return f"argument {key} must be an integer"
            if typ == "number" and not isinstance(value, (int, float)):
                return f"argument {key} must be a number"
            if typ == "object" and not isinstance(value, dict):
                return f"argument {key} must be an object"
            if typ == "array" and not isinstance(value, list):
                return f"argument {key} must be an array"
        return None

    def run(self, messages: list[dict[str, Any]], *, effort: Optional[str] = None) -> ToolLoopResult:
        working = [dict(m) for m in messages]
        total_tool_calls = 0
        accumulated_usage = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None, "reasoning_tokens": None}
        final_content = ""
        finish_reason = None
        for iteration in range(1, self.max_iterations + 1):
            try:
                response = self.provider.chat(working, tools=self.tool_schemas, effort=effort)
            except Exception as exc:
                return ToolLoopResult(
                    messages=working,
                    final_content=final_content,
                    tool_calls_total=total_tool_calls,
                    iterations=iteration,
                    usage=accumulated_usage,
                    finish_reason=finish_reason,
                    error=f"provider_error: {exc}",
                )
            # Accumulate usage.
            for key in accumulated_usage:
                val = response.usage.get(key)
                if isinstance(val, (int, float)):
                    prev = accumulated_usage[key]
                    accumulated_usage[key] = (prev or 0) + val if prev is not None else val
            final_content = response.content
            finish_reason = response.finish_reason
            assistant_msg = {"role": "assistant", "content": response.content}
            if getattr(response, "reasoning_content", None):
                assistant_msg["reasoning_content"] = response.reasoning_content
            if response.tool_calls:
                assistant_msg["tool_calls"] = response.tool_calls
            working.append(assistant_msg)

            if not response.tool_calls:
                error = None
                if not (final_content or "").strip():
                    error = "empty_response"
                elif getattr(response, "truncated", False):
                    error = "truncated_response"
                return ToolLoopResult(
                    messages=working,
                    final_content=final_content,
                    tool_calls_total=total_tool_calls,
                    iterations=iteration,
                    usage=accumulated_usage,
                    finish_reason=finish_reason,
                    error=error,
                )

            for tool_call in response.tool_calls:
                total_tool_calls += 1
                name = tool_call.get("function", {}).get("name")
                args_raw = tool_call.get("function", {}).get("arguments", "{}")
                args = None
                parse_error = None
                try:
                    import json
                    args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                    if not isinstance(args, dict):
                        parse_error = "tool arguments must be a JSON object"
                except Exception as exc:
                    parse_error = f"invalid tool arguments: {exc}"
                if name not in self.tools:
                    result = {"error": f"Unknown tool: {name}"}
                elif parse_error is not None:
                    result = {"error": parse_error}
                else:
                    schema_error = self._validate_args(name, args)
                    if schema_error is not None:
                        result = {"error": schema_error}
                    else:
                        try:
                            result = self.tools[name](args)
                        except Exception as exc:  # bounded: capture, do not crash
                            result = {"error": str(exc)}
                working.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "name": name,
                    "content": _to_content(result),
                })

        return ToolLoopResult(
            messages=working,
            final_content=final_content,
            tool_calls_total=total_tool_calls,
            iterations=self.max_iterations,
            usage=accumulated_usage,
            finish_reason=finish_reason,
            error="max_iterations_exceeded",
        )


def _to_content(result: Any) -> str:
    import json
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, default=str)
    except Exception:
        return str(result)
