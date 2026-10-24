"""Targeted hardening tests."""
import tempfile, os
from pathlib import Path

from backend.app.collector import redact, redact_value
from backend.app.provider import ProviderResponse
from backend.app.stl_edit import drill_hole, load_mesh
from backend.app.tool_loop import ToolLoop


def test_redact_nested_and_header():
    assert "<redacted>" in redact("Authorization: Bearer abc123")
    out = redact_value("cfg", {"api_key": "secret", "nested": {"token": "tok"}})
    assert out["api_key"] == "<redacted>"
    assert out["nested"]["token"] == "<redacted>"


def test_tool_loop_invalid_args_not_executed():
    calls = {"n": 0}

    def tool(args):
        calls["n"] += 1
        return 1

    class P:
        def __init__(self):
            self.i = 0
            self.responses = [
                ProviderResponse(content="", tool_calls=[{"id": "1", "function": {"name": "t", "arguments": "{bad json"}}], finish_reason="tool_calls", usage={}),
                ProviderResponse(content="done", tool_calls=[], finish_reason="stop", usage={}),
            ]

        def chat(self, messages, tools=None, effort=None):
            r = self.responses[self.i]
            self.i += 1
            return r

    loop = ToolLoop(P(), {"t": tool})
    result = loop.run([{"role": "user", "content": "x"}])
    assert calls["n"] == 0
    assert any("invalid tool arguments" in (m.get("content") or "") for m in result.messages)


def test_unknown_usage_stays_none():
    class P:
        def chat(self, messages, tools=None, effort=None):
            return ProviderResponse(content="ok", tool_calls=[], finish_reason="stop", usage={})

    loop = ToolLoop(P(), {})
    result = loop.run([{"role": "user", "content": "x"}])
    assert result.usage["total_tokens"] is None


def test_drill_hole_depth_by_axis():
    mesh = load_mesh(str(Path(__file__).resolve().parents[1] / "web" / "fixtures" / "bracket.stl"))
    original_volume = mesh.volume
    drilled = drill_hole(mesh, diameter=5, axis="x", center=(20, 12.5, 15))
    assert drilled.volume < original_volume
