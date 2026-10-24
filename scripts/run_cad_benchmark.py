#!/usr/bin/env python3
"""Small CAD benchmark run (one case, one repetition)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys_path = str(Path(__file__).resolve().parents[1])
import sys
sys.path.insert(0, sys_path)

from backend.app.provider import ProviderAdapter, reflection_config_from_env
from backend.app.tool_loop import ToolLoop
from backend.app.worker import build_model
from eval.runner import run_eval

cfg = reflection_config_from_env()
adapter = ProviderAdapter(cfg)

def solver(case):
    started = time.monotonic()
    tool_calls = {"n": 0}
    def build(args):
        tool_calls["n"] += 1
        r = build_model(args.get("scad", ""))
        return {"ok": r.ok, "error": r.error, "mesh": r.mesh, "sha256": r.sha256}

    tools = {"build_model": build}
    schemas = [{
        "type": "function",
        "function": {
            "name": "build_model",
            "description": "Compile OpenSCAD source to a validated STL.",
            "parameters": {"type": "object", "properties": {"scad": {"type": "string"}}, "required": ["scad"]},
        },
    }]
    loop = ToolLoop(adapter, tools, tool_schemas=schemas, max_iterations=6)
    prompt = (
        "Create an OpenSCAD model for a single-part bracket: "
        "40 mm wide, 25 mm deep, 30 mm high, with two 5 mm mounting holes spaced 20 mm apart in the base. "
        "Call build_model with the complete SCAD source. Report whether it succeeded."
    )
    result = loop.run([{"role": "user", "content": prompt}], effort="medium")
    success = any("true" in str(m.get("content","")).lower() or '"ok": true' in str(m.get("content","")).lower() for m in result.messages) or (result.final_content.lower().find("success") >= 0)
    # More robust: inspect tool results.
    tool_ok = False
    for m in result.messages:
        c = m.get("content", "")
        if isinstance(c, str) and '"ok": true' in c:
            tool_ok = True
    success = tool_ok
    return {
        "success": success,
        "tokens": result.usage.get("total_tokens"),
        "tool_calls": result.tool_calls_total,
        "model": cfg.model,
        "provider": cfg.name,
        "finish_reason": result.finish_reason,
        "truncated": False,
        "error": result.error,
    }

case = {"id": "cad-001", "category": "cad", "title": "Bracket"}
summary = run_eval(solver, repetitions=1, cases=[case])
out = summary.to_dict()
Path("eval/results").mkdir(exist_ok=True)
Path("eval/results/cad-benchmark.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
