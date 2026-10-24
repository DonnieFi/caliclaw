"""Small configurable provider adapter for the configured model and comparison models."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str
    supports_tools: bool = True
    supports_reasoning_effort: bool = True
    default_effort: Optional[str] = None


@dataclass
class ProviderResponse:
    content: str
    reasoning_content: Optional[str] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    status_code: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    def __init__(self, status_code: Optional[int], message: str):
        super().__init__(message)
        self.status_code = status_code


class ProviderAdapter:
    def __init__(self, config: ProviderConfig, timeout: float = 120.0):
        self.config = config
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        effort: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> ProviderResponse:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
        }
        if tools and self.config.supports_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if effort and self.config.supports_reasoning_effort:
            payload["reasoning_effort"] = effort
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=self._headers(), json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(exc.response.status_code, str(exc)) from exc
        except httpx.RequestError as exc:
            raise ProviderError(None, str(exc)) from exc

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        # Normalize usage without double-counting reasoning tokens.
        reasoning = usage.get("reasoning_tokens")
        if reasoning is None:
            reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        normalized_usage = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "reasoning_tokens": reasoning,
        }
        # If total missing, derive only when both parts are known.
        if normalized_usage["total_tokens"] is None and normalized_usage["prompt_tokens"] is not None and normalized_usage["completion_tokens"] is not None:
            normalized_usage["total_tokens"] = normalized_usage["prompt_tokens"] + normalized_usage["completion_tokens"]

        finish_reason = choice.get("finish_reason")
        return ProviderResponse(
            content=message.get("content") or "",
            reasoning_content=message.get("reasoning_content"),
            tool_calls=message.get("tool_calls") or [],
            finish_reason=finish_reason,
            usage=normalized_usage,
            truncated=finish_reason in ("length", "max_tokens", "content_filter"),
            status_code=None,
            raw=data,
        )


def reflection_config_from_env() -> Optional[ProviderConfig]:
    api_key = (
        os.environ.get("CALICLAW_API_KEY")
        or os.environ.get("REFLECTION_API_KEY")
        or os.environ.get("BEAM_API_KEY")
    )
    if not api_key:
        return None
    return ProviderConfig(
        name="reflection",
        base_url=os.environ.get("CALICLAW_BASE_URL")
        or os.environ.get("REFLECTION_BASE_URL")
        or "https://api.reflection.ai/openai/v1",
        api_key=api_key,
        model=os.environ.get("CALICLAW_MODEL") or os.environ.get("REFLECTION_MODEL") or "",
    )


def comparison_config_from_env() -> Optional[ProviderConfig]:
    api_key = os.environ.get("COMPARISON_API_KEY")
    if not api_key:
        return None
    return ProviderConfig(
        name=os.environ.get("COMPARISON_PROVIDER", "comparison"),
        base_url=os.environ.get("COMPARISON_BASE_URL", ""),
        api_key=api_key,
        model=os.environ.get("COMPARISON_MODEL", ""),
    )
