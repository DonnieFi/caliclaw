"""Tests for provider adapter usage normalization."""
from unittest.mock import patch

import httpx

from backend.app.provider import ProviderAdapter, ProviderConfig


class FakeClient:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        fake = {
            "choices": [{"message": {"content": "hi", "tool_calls": []}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30, "completion_tokens_details": {"reasoning_tokens": 5}},
        }
        resp = httpx.Response(200, json=fake)
        resp._request = httpx.Request("POST", url)
        return resp


def test_usage_normalization():
    cfg = ProviderConfig(name="t", base_url="https://example.com/v1", api_key="key", model="m")
    adapter = ProviderAdapter(cfg)
    with patch("backend.app.provider.httpx.Client", FakeClient):
        resp = adapter.chat([{"role": "user", "content": "x"}])
    assert resp.content == "hi"
    assert resp.usage["total_tokens"] == 30
    assert resp.usage["reasoning_tokens"] == 5
