#!/usr/bin/env python3
"""Optional live provider smoke test. Requires REFLECTION_API_KEY."""
from __future__ import annotations

import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from backend.app.provider import ProviderAdapter, reflection_config_from_env


def main() -> int:
    cfg = reflection_config_from_env()
    if cfg is None:
        print("SKIP: REFLECTION_API_KEY not set")
        return 0
    adapter = ProviderAdapter(cfg)
    resp = adapter.chat([{"role": "user", "content": "Reply with the single word: pong"}], max_tokens=32)
    print("text:", resp.content)
    print("usage:", json.dumps(resp.usage, sort_keys=True))
    print("finish:", resp.finish_reason, "truncated:", resp.truncated)

    # Tool round trip.
    def tool(args):
        return {"sum": args["a"] + args["b"]}

    tool_schema = [{
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two numbers",
            "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]},
        },
    }]
    r1 = adapter.chat(
        [{"role": "user", "content": "Use the add tool for 2 and 3, then state the result."}],
        tools=tool_schema,
    )
    print("tool_calls:", r1.tool_calls)
    if r1.tool_calls:
        tc = r1.tool_calls[0]
        import json as _json
        args = _json.loads(tc["function"]["arguments"])
        result = tool(args)
        assistant_msg = {"role": "assistant", "content": r1.content, "tool_calls": r1.tool_calls}
        if r1.reasoning_content:
            assistant_msg["reasoning_content"] = r1.reasoning_content
        r2 = adapter.chat([
            {"role": "user", "content": "Use the add tool for 2 and 3, then state the result."},
            assistant_msg,
            {"role": "tool", "tool_call_id": tc.get("id"), "name": tc["function"]["name"], "content": _json.dumps(result)},
        ])
        print("followup:", r2.content)
        print("followup_usage:", json.dumps(r2.usage, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
