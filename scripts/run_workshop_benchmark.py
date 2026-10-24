#!/usr/bin/env python3
"""Run a reduced workshop benchmark across all ten cases."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.geometry import validate_stl
from backend.app.provider import ProviderAdapter, reflection_config_from_env
from backend.app.revisions import is_slice_stale
from backend.app.slicer import slice_model
from backend.app.tool_loop import ToolLoop
from backend.app.worker import build_model
from eval.runner import run_eval

ROOT = Path(__file__).resolve().parents[1]
cfg = reflection_config_from_env()
adapter = ProviderAdapter(cfg)

LOGS = {
    "log-001": (ROOT / "eval/fixtures/log-001.txt").read_text(),
    "log-002": (ROOT / "eval/fixtures/log-002.txt").read_text(),
}
FW = {
    "fw-001": (ROOT / "eval/fixtures/fw-001.txt").read_text(),
    "fw-002": (ROOT / "eval/fixtures/fw-002.txt").read_text(),
}

def make_tools(case_id):
    def build(args):
        r = build_model(args.get("scad", ""))
        return {"ok": r.ok, "error": r.error, "mesh": r.mesh}
    def slice_fixed(args):
        r = slice_model(str(ROOT / "web" / "fixtures" / "bracket.stl"),
                        str(ROOT / "profiles/ender3-proven-pla.ini"),
                        overlay_path=str(ROOT / "profiles/ender3-speed-preference.ini"))
        # ensure STL exists
        if not (ROOT / "web" / "fixtures" / "bracket.stl").exists():
            build_model((ROOT / "fixtures/bracket.scad").read_text())
        return {"ok": r.ok, "error": r.error, "estimates": r.estimates}
    def get_log(args):
        return {"log": LOGS.get(case_id, "")}
    def get_fw(args):
        return {"firmware": FW.get(case_id, "")}
    return {"build_model": build, "slice_model": slice_fixed, "get_log_events": get_log, "get_firmware_output": get_fw}

SCHEMAS = [
    {"type": "function", "function": {"name": "build_model", "description": "Compile SCAD to STL.", "parameters": {"type": "object", "properties": {"scad": {"type": "string"}}, "required": ["scad"]}}},
    {"type": "function", "function": {"name": "slice_model", "description": "Slice the checked bracket STL with the pinned profile.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_log_events", "description": "Read Pi log events.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_firmware_output", "description": "Read firmware output.", "parameters": {"type": "object", "properties": {}}}},
]

PROMPTS = {
    "log-001": "Explain the likely cause from these Pi log events. Cite evidence and propose one next check. Events: {log}",
    "log-002": "The Pi log is unchanged since the last run. State whether there is new evidence. Events: {log}",
    "fw-001": "Interpret this Klipper firmware output. Distinguish observed settings from inferred state. Output: {fw}",
    "fw-002": "Interpret this partial Klipper status. Output: {fw}",
    "cad-001": "Create an OpenSCAD bracket with bounding box exactly 40 mm wide, 25 mm deep, 30 mm high, with two 5 mm mounting holes spaced 20 mm apart in the base. Do not add flanges or extra features. Call build_model. Report success.",
    "cad-002": "Create a degenerate zero-thickness slab in OpenSCAD and call build_model. Report whether it correctly fails.",
    "rev-001": "Create a revised bracket with bounding box exactly 40 mm wide, 25 mm deep, 40 mm high, preserving 20 mm hole spacing. Do not add flanges. Call build_model. Report success.",
    "rev-002": "Restore the original bracket revision conceptually and explain history preservation.",
    "slice-001": "Slice the checked bracket with the pinned profile using slice_model. Report success and estimates.",
    "slice-002": "Explain why a slice becomes stale when model or profile changes.",
}

def solver(case):
    cid = case["id"]
    tools = make_tools(cid)
    loop = ToolLoop(adapter, tools, tool_schemas=SCHEMAS, max_iterations=6)
    prompt = PROMPTS[cid]
    if "{log}" in prompt:
        prompt = prompt.format(log=LOGS[cid])
    if "{fw}" in prompt:
        prompt = prompt.format(fw=FW[cid])
    result = loop.run([{"role": "user", "content": prompt}], effort="medium")
    if result.error:
        success = False
        return {
            "success": success,
            "tokens": result.usage.get("total_tokens"),
            "tool_calls": result.tool_calls_total,
            "model": cfg.model,
            "provider": cfg.name,
            "finish_reason": result.finish_reason,
            "truncated": False,
            "error": result.error,
            "failure_category": "provider",
        }
    # Grade only assistant/tool outputs, not the user prompt.
    assistant_text = (result.final_content or "").lower()
    tool_text = " ".join(str(m.get("content", "")).lower() for m in result.messages if m.get("role") in ("assistant", "tool"))
    text = assistant_text + " " + tool_text
    success = False
    if cid == "log-001":
        success = "thermal" in text
    elif cid == "log-002":
        success = "insufficient" in text or "no new" in text or "unchanged" in text
    elif cid == "fw-001":
        success = "0.05" in text or "pressure" in text
    elif cid == "fw-002":
        success = "unavailable" in text or "insufficient" in text or "disconnected" in text
    elif cid in ("cad-001", "rev-001"):
        tool_ok = any('"ok": true' in str(m.get("content", "")).lower() for m in result.messages if m.get("role") == "tool")
        # Validate mesh bounds from tool result.
        expected_z = 40.0 if cid == "rev-001" else 30.0
        bounds_ok = False
        for m in result.messages:
            if m.get("role") != "tool":
                continue
            try:
                data = json.loads(m.get("content", ""))
            except Exception:
                continue
            mesh = data.get("mesh") or {}
            bounds = mesh.get("bounds_mm") or mesh.get("bounds")
            if bounds and len(bounds) == 2:
                dx = bounds[1][0] - bounds[0][0]
                dy = bounds[1][1] - bounds[0][1]
                dz = bounds[1][2] - bounds[0][2]
                if abs(dx - 40.0) < 1.0 and abs(dy - 25.0) < 1.0 and abs(dz - expected_z) < 1.0:
                    bounds_ok = True
        success = tool_ok and bounds_ok
    elif cid == "cad-002":
        success = any('"ok": false' in str(m.get("content", "")).lower() for m in result.messages if m.get("role") == "tool")
    elif cid == "slice-001":
        success = any('"ok": true' in str(m.get("content", "")).lower() for m in result.messages if m.get("role") == "tool")
    elif cid in ("rev-002", "slice-002"):
        success = bool((result.final_content or "").strip())
    return {
        "success": success,
        "tokens": result.usage.get("total_tokens"),
        "tool_calls": result.tool_calls_total,
        "model": cfg.model,
        "provider": cfg.name,
        "finish_reason": result.finish_reason,
        "truncated": False,
        "error": result.error,
        "failure_category": None if success else "model",
    }

cases = json.loads((ROOT / "eval/cases.json").read_text())["cases"]
summary = run_eval(solver, repetitions=1, cases=cases)
out = summary.to_dict()
Path(ROOT / "eval/results").mkdir(exist_ok=True)
(ROOT / "eval/results/workshop-benchmark.json").write_text(json.dumps(out, indent=2))
print(json.dumps({"successes": out["successes"], "cases": out["cases"], "success_rate": out["success_rate"], "total_tokens": out["total_tokens"], "tokens_per_success": out["tokens_per_success"]}, indent=2))
