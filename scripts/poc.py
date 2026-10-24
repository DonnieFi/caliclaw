#!/usr/bin/env python3
"""End-to-end CaliClaw proof of concept using the configured model."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.collector import SimulatedPrinterState
from backend.app.provider import ProviderAdapter, reflection_config_from_env
from backend.app.revisions import create_revision_child
from backend.app.slicer import slice_model
from backend.app.tool_loop import ToolLoop
from backend.app.worker import build_model
from backend.app.db import init_db
from backend.app.repository import create_project

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "poc.db"
if DB.exists():
    DB.unlink()
init_db(DB)

cfg = reflection_config_from_env()
adapter = ProviderAdapter(cfg)
printer = SimulatedPrinterState(temperature=200.0, bed_temperature=60.0)

project = create_project(str(DB), "POC bracket")

def build(args):
    r = build_model(args.get("scad", ""))
    if r.ok:
        create_revision_child(str(DB), project.id, None, params={"scad": args.get("scad", "")[:80]}, source_hash=r.sha256, artifact_id=None)
    return {"ok": r.ok, "error": r.error, "mesh": r.mesh, "sha256": r.sha256}

def slice_fixed(args):
    stl = ROOT / "web" / "fixtures" / "bracket.stl"
    if not stl.exists():
        build({"scad": (ROOT / "fixtures/bracket.scad").read_text()})
    r = slice_model(str(stl), str(ROOT / "profiles/ender3-proven-pla.ini"), overlay_path=str(ROOT / "profiles/ender3-speed-preference.ini"))
    return {"ok": r.ok, "error": r.error, "estimates": r.estimates}

def printer_status(args):
    return printer.to_dict()

def log_events(args):
    return {"log": (ROOT / "eval/fixtures/log-001.txt").read_text()}

tools = {"build_model": build, "slice_model": slice_fixed, "get_printer_status": printer_status, "get_log_events": log_events}
schemas = [
    {"type": "function", "function": {"name": "build_model", "description": "Compile OpenSCAD to a validated STL.", "parameters": {"type": "object", "properties": {"scad": {"type": "string"}}, "required": ["scad"]}}},
    {"type": "function", "function": {"name": "slice_model", "description": "Slice the checked bracket STL with the pinned profile.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_printer_status", "description": "Get simulated printer status.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_log_events", "description": "Read Pi log events.", "parameters": {"type": "object", "properties": {}}}},
]

loop = ToolLoop(adapter, tools, tool_schemas=schemas, max_iterations=8)
prompt = (
    "Build a measured bracket: 40 mm wide, 25 mm deep, 30 mm high, with 5 mm holes spaced 20 mm apart. "
    "First call build_model with complete OpenSCAD. Then slice_model. Then get_printer_status. "
    "Report the mesh bounds, slice time estimate, and printer state."
)
print("Running CaliClaw POC...")
result = loop.run([{"role": "user", "content": prompt}], effort="medium")
print("\nFINAL:\n" + (result.final_content or ""))
print("\nTool calls:", result.tool_calls_total)
print("Tokens:", result.usage.get("total_tokens"))
print("Reasoning tokens:", result.usage.get("reasoning_tokens"))
print("Elapsed iterations:", result.iterations)

# Simulated print
printer.start()
for _ in range(5):
    printer.advance(0.2)
print("Simulated print state:", printer.to_dict())
