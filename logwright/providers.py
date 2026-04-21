from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_OPENAI_MODEL = os.environ.get("LOGWRIGHT_OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_ANTHROPIC_MODEL = os.environ.get(
    "LOGWRIGHT_ANTHROPIC_MODEL", "claude-3-7-sonnet-latest"
)


class ProviderError(RuntimeError):
    pass


@dataclass
class ProviderResponse:
    data: dict[str, Any]
    input_tokens: int | None
    output_tokens: int | None


class BaseProvider:
    name: str

    def __init__(self, model: str) -> None:
        self.model = model

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int = 900,
    ) -> ProviderResponse:
        raise NotImplementedError


def _json_request(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", "ignore")
        raise ProviderError(f"HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(str(exc)) from exc


def _extract_json_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ProviderError("provider returned empty text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ProviderError("provider did not return valid JSON")
        return json.loads(text[start : end + 1])


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, model: str = DEFAULT_OPENAI_MODEL) -> None:
        super().__init__(model=model)
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not set")

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int = 900,
    ) -> ProviderResponse:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        raw = _json_request(
            "https://api.openai.com/v1/responses",
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload,
        )
        for item in raw.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "refusal":
                    raise ProviderError(content.get("refusal", "model refused request"))
                if content.get("type") == "output_text":
                    data = _extract_json_text(content.get("text", ""))
                    usage = raw.get("usage", {})
                    return ProviderResponse(
                        data=data,
                        input_tokens=usage.get("input_tokens"),
                        output_tokens=usage.get("output_tokens"),
                    )
        raise ProviderError("OpenAI response did not contain output_text")


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, model: str = DEFAULT_ANTHROPIC_MODEL) -> None:
        super().__init__(model=model)
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int = 900,
    ) -> ProviderResponse:
        schema_text = json.dumps(schema, sort_keys=True)
        prompt = (
            f"{user_prompt}\n\n"
            "Return JSON only. Do not use markdown fences.\n"
            f"Schema name: {schema_name}\n"
            f"Schema: {schema_text}\n"
        )
        payload = {
            "model": self.model,
            "max_tokens": max_output_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        }
        raw = _json_request(
            "https://api.anthropic.com/v1/messages",
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            payload,
        )
        for content in raw.get("content", []):
            if content.get("type") == "text":
                data = _extract_json_text(content.get("text", ""))
                usage = raw.get("usage", {})
                return ProviderResponse(
                    data=data,
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                )
        raise ProviderError("Anthropic response did not contain text content")


def resolve_provider(provider_name: str, model: str | None = None) -> BaseProvider | None:
    if provider_name == "heuristic":
        return None
    if provider_name == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return AnthropicProvider(model or DEFAULT_ANTHROPIC_MODEL)
        if os.environ.get("OPENAI_API_KEY"):
            return OpenAIProvider(model or DEFAULT_OPENAI_MODEL)
        return None
    if provider_name == "anthropic":
        return AnthropicProvider(model or DEFAULT_ANTHROPIC_MODEL)
    if provider_name == "openai":
        return OpenAIProvider(model or DEFAULT_OPENAI_MODEL)
    raise ProviderError(f"unknown provider: {provider_name}")
