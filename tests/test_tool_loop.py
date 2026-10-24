"""Tests for measured-spec tool loop."""
import json

from backend.app.provider import ProviderResponse
from backend.app.tool_loop import ToolLoop


class FakeProvider:
    def __init__(self, responses):
        self.responses = responses
        self.i = 0

    def chat(self, messages, tools=None, effort=None):
        r = self.responses[self.i]
        self.i += 1
        return r


def test_tool_loop_executes_tool_and_finishes():
    tool_calls = [{"id": "1", "function": {"name": "add", "arguments": json.dumps({"a": 2, "b": 3})}}]
    responses = [
        ProviderResponse(content="", tool_calls=tool_calls, finish_reason="tool_calls", usage={"total_tokens": 10}),
        ProviderResponse(content="The result is 5", tool_calls=[], finish_reason="stop", usage={"total_tokens": 5}),
    ]
    provider = FakeProvider(responses)
    loop = ToolLoop(provider, {"add": lambda args: args["a"] + args["b"]}, tool_schemas=[{"type": "function", "function": {"name": "add"}}])
    result = loop.run([{"role": "user", "content": "add 2 and 3"}])
    assert result.final_content == "The result is 5"
    assert result.tool_calls_total == 1
    assert result.iterations == 2
    assert result.usage["total_tokens"] == 15


def test_bounded_repair_stops_at_max():
    tool_calls = [{"id": "1", "function": {"name": "add", "arguments": "{}"}}]
    responses = [ProviderResponse(content="", tool_calls=tool_calls, finish_reason="tool_calls", usage={}) for _ in range(10)]
    provider = FakeProvider(responses)
    loop = ToolLoop(provider, {"add": lambda args: 1}, max_iterations=2)
    result = loop.run([{"role": "user", "content": "loop"}])
    assert result.error == "max_iterations_exceeded"
    assert result.iterations == 2
